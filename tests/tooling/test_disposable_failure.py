"""Disposable. Exists only to confirm that a failing test blocks a merge. Never merge."""


def test_intentional_failure_for_safeguard_validation() -> None:
    expected = 3
    assert 1 + 1 == expected, "intentional failure: validating that CI blocks merging"
