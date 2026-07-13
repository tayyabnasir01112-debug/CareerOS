from app.services.deduplication import FingerprintInput, JobDeduplicationService


def test_fingerprint_is_stable_across_formatting_and_company_suffixes() -> None:
    first = FingerprintInput(
        title="Senior Python Engineer", company="Example, Inc.", location="Worldwide Remote"
    )
    second = FingerprintInput(
        title="  SENIOR Python-Engineer ", company="Example Corporation", location="Remote"
    )

    assert JobDeduplicationService.fingerprint(first) == JobDeduplicationService.fingerprint(second)


def test_materially_different_jobs_have_different_fingerprints() -> None:
    backend = FingerprintInput("Python Engineer", "Example", "Remote")
    mobile = FingerprintInput("Mobile Engineer", "Example", "Remote")

    assert JobDeduplicationService.fingerprint(backend) != JobDeduplicationService.fingerprint(
        mobile
    )
