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


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        category: EvaluationErrorCategory,
        summary: str,
        *,
        retryable: bool = False,
        fatal: bool = False,
    ) -> None:
        super().__init__(redact_sensitive_text(summary)[:500])
        self.category = category
        self.retryable = retryable
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
                max_output_tokens=2500,
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
        except (ValidationError, BadRequestError) as exc:
            raise ProviderFailure(
                EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
                "OpenAI did not return a valid recruiter evaluation",
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
            raise ProviderFailure(
                EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
                "OpenAI response did not contain parsed structured output",
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
        for attempt in range(self.max_retries + 1):
            try:
                return await self.provider.evaluate(prepared_input)
            except ProviderFailure as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                delay = self.retry_base_seconds * (2**attempt)
                jitter = delay * 0.25 * self.random_value()
                await self.sleep(delay + jitter)
        raise AssertionError("evaluation retry loop terminated unexpectedly")
