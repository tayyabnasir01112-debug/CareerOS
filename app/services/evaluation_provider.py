import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError

from app.core.security import redact_sensitive_text
from app.schemas.evaluation import (
    EvaluationErrorCategory,
    PreparedEvaluationInput,
    ProviderEvaluation,
    RecruiterEvaluationResult,
)

_STRUCTURED_OUTPUT_REPAIR_INSTRUCTION = """Return exactly one schema-valid object. Use only the
declared enum values. Do not exceed list limits: 12 matched skills, 10 missing skills, 8
transferable skills, 6 evidence items, 8 concerns, and 4 portfolio projects. Keep every item and
both summary strings brief. Use verified evidence only. Do not add commentary outside the object."""


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        category: EvaluationErrorCategory,
        summary: str,
        *,
        retryable: bool = False,
        repairable: bool = False,
        fatal: bool = False,
    ) -> None:
        super().__init__(redact_sensitive_text(summary)[:500])
        self.category = category
        self.retryable = retryable
        self.repairable = repairable
        self.fatal = fatal


class RecruiterEvaluationProvider(Protocol):
    async def evaluate(self, prepared_input: PreparedEvaluationInput) -> ProviderEvaluation: ...


class OpenAIRecruiterEvaluationProvider:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )

    async def evaluate(self, prepared_input: PreparedEvaluationInput) -> ProviderEvaluation:
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=prepared_input.system_prompt,
                input=prepared_input.user_prompt,
                text_format=RecruiterEvaluationResult,
                tools=[],
                store=False,
                max_output_tokens=3500,
            )
        except AuthenticationError as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.AUTHENTICATION_ERROR,
                "OpenAI authentication failed",
                fatal=True,
            ) from exc
        except PermissionDeniedError as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.PERMISSION_ERROR,
                "OpenAI permission was denied for the configured model or project",
                fatal=True,
            ) from exc
        except RateLimitError as exc:
            if self._is_quota_error(exc):
                raise ProviderFailure(
                    EvaluationErrorCategory.QUOTA_ERROR,
                    "OpenAI quota is exhausted",
                    fatal=True,
                ) from exc
            raise ProviderFailure(
                EvaluationErrorCategory.RATE_LIMIT_ERROR,
                "OpenAI rate limit was reached",
                retryable=True,
            ) from exc
        except APITimeoutError as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.TIMEOUT_ERROR,
                "OpenAI request timed out",
                retryable=True,
            ) from exc
        except (APIConnectionError, InternalServerError) as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.TRANSIENT_PROVIDER_ERROR,
                "OpenAI was temporarily unavailable",
                retryable=True,
            ) from exc
        except ValidationError as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
                self._validation_error_summary(exc),
                repairable=True,
            ) from exc
        except BadRequestError as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
                self._bad_request_summary(exc),
            ) from exc
        except APIStatusError as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.UNKNOWN_PROVIDER_ERROR,
                f"OpenAI returned HTTP {exc.status_code}",
                fatal=400 <= exc.status_code < 500,
            ) from exc
        except Exception as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.UNKNOWN_PROVIDER_ERROR,
                f"OpenAI request failed with {type(exc).__name__}",
            ) from exc

        result = response.output_parsed
        if result is None:
            status = str(getattr(response, "status", "unknown"))
            details = getattr(response, "incomplete_details", None)
            reason = str(getattr(details, "reason", "none"))
            raise ProviderFailure(
                EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
                f"OpenAI parsed output was missing (status={status}, reason={reason})",
                repairable=True,
            )
        usage = response.usage
        return ProviderEvaluation(
            result=result,
            response_id=response.id,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )

    async def close(self) -> None:
        await self.client.close()

    @staticmethod
    def _is_quota_error(exc: RateLimitError) -> bool:
        body = exc.body
        if isinstance(body, dict):
            code = body.get("code")
            if code == "insufficient_quota":
                return True
            error = body.get("error")
            return isinstance(error, dict) and error.get("code") == "insufficient_quota"
        return False

    @staticmethod
    def _validation_error_summary(exc: ValidationError) -> str:
        failures: list[str] = []
        for error in exc.errors(include_input=False, include_url=False)[:8]:
            path = ".".join(str(item) for item in error.get("loc", ())) or "root"
            error_type = str(error.get("type", "validation_error"))
            failures.append(f"{path}:{error_type}")
        fields = ", ".join(failures) or "unknown field"
        return f"Structured output validation failed at {fields}"

    @staticmethod
    def _bad_request_summary(exc: BadRequestError) -> str:
        safe_parts: list[str] = []
        for name in ("code", "param", "type"):
            value = getattr(exc, name, None)
            if value is not None:
                safe_value = "".join(char for char in str(value) if char.isalnum() or char in "._-")
                if safe_value:
                    safe_parts.append(f"{name}={safe_value[:80]}")
        details = ", ".join(safe_parts) or "no safe field metadata"
        return f"OpenAI rejected the structured-output request ({details})"


class FakeRecruiterEvaluationProvider:
    def __init__(self, outcomes: Sequence[ProviderEvaluation | ProviderFailure]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[PreparedEvaluationInput] = []

    async def evaluate(self, prepared_input: PreparedEvaluationInput) -> ProviderEvaluation:
        self.calls.append(prepared_input)
        if not self.outcomes:
            raise ProviderFailure(
                EvaluationErrorCategory.UNKNOWN_PROVIDER_ERROR,
                "Fake provider has no configured outcome",
            )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ProviderFailure):
            raise outcome
        return outcome


class RecruiterEvaluator:
    def __init__(
        self,
        provider: RecruiterEvaluationProvider,
        *,
        max_retries: int,
        retry_base_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.provider = provider
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.sleep = sleep
        self.random_value = random_value

    async def evaluate(self, prepared_input: PreparedEvaluationInput) -> ProviderEvaluation:
        transient_attempt = 0
        repair_attempted = False
        current_input = prepared_input
        while True:
            try:
                return await self.provider.evaluate(current_input)
            except ProviderFailure as exc:
                if exc.repairable and not repair_attempted:
                    repair_attempted = True
                    current_input = prepared_input.model_copy(
                        update={
                            "system_prompt": (
                                f"{prepared_input.system_prompt}\n\nREPAIR INSTRUCTION:\n"
                                f"{_STRUCTURED_OUTPUT_REPAIR_INSTRUCTION}"
                            )
                        }
                    )
                    continue
                if not exc.retryable or transient_attempt >= self.max_retries:
                    raise
                delay = self.retry_base_seconds * (2**transient_attempt)
                jitter = delay * 0.25 * self.random_value()
                await self.sleep(delay + jitter)
                transient_attempt += 1
