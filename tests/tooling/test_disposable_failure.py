"""Disposable. Exists only to confirm that a failing test blocks a merge. Never merge."""


def test_intentional_failure_for_safeguard_validation() -> None:
    values = [1, 2]
    assert sum(values) == 4, "intentional failure: validating that CI blocks merging"
