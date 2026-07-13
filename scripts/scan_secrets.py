import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    line_number: int
    rule: str


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    (
        "Discord webhook",
        re.compile(r"https?://(?:canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+", re.I),
    ),
    ("GitHub token", re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer credential", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*", re.I)),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "populated secret assignment",
        re.compile(
            r"\b(?:api[_-]?key|password|client[_-]?secret|access[_-]?token|bearer[_-]?token)"
            r"\b\s*[:=]\s*(?:\"[^\"\r\n]{8,}\"|'[^'\r\n]{8,}'|[A-Za-z0-9_/-]{12,})",
            re.I,
        ),
    ),
)

_TEXT_SUFFIXES = {
    "",
    ".ini",
    ".json",
    ".md",
    ".mako",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def scan_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for rule, pattern in _RULES:
                if pattern.search(line):
                    findings.append(Finding(path, line_number, rule))
    return findings


def repository_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def main() -> int:
    root = Path.cwd()
    findings = scan_paths(repository_files(root))
    for finding in findings:
        relative = finding.path.relative_to(root)
        print(f"{relative}:{finding.line_number}: possible {finding.rule}")
    if findings:
        print(f"Secret scan failed with {len(findings)} possible finding(s).")
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
