## Summary

Describe the behavior changed and why.

## Validation

- [ ] `python -m scripts.scan_secrets`
- [ ] `python -m ruff format --check .`
- [ ] `python -m ruff check .`
- [ ] `python -m mypy app scripts tests`
- [ ] `python -m pytest`
- [ ] Database migrations were tested when applicable

## Safety and scope

- [ ] No credentials, private candidate data, databases, generated applications, or local artifacts are included
- [ ] Tests do not contact live job boards
- [ ] Public collector changes respect platform access controls and documented endpoints
- [ ] Planned features are not presented as implemented
