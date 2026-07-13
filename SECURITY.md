# Security policy

## Supported versions

CareerOS is pre-1.0. Security fixes are applied to the current `main` branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or exposed credential. Use GitHub's private security
advisory reporting for this repository when available, or contact the repository owner through the
public profile at <https://github.com/tayyabnasir01112-debug> without including secrets in the first
message.

Include affected versions, reproduction steps, impact, and a minimal proof of concept. Remove API
keys, webhook tokens, candidate information, cookies, and private job data. You can expect an
acknowledgement within seven days, followed by a remediation assessment.

## Operational boundaries

- Store runtime credentials only in an ignored local `.env` file or an appropriate secret manager.
- Never commit `.env`, databases, resumes, generated applications, or collected private data.
- Collectors may access only documented public job-board endpoints. They must not bypass
  authentication, CAPTCHA, rate limits, robots rules, or platform access controls.
- Rotate a credential immediately if it appears in a commit, log, issue, or build artifact. Removing
  it from a later commit does not make the original credential safe.
