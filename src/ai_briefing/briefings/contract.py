"""How a document is validated against a briefing contract schema.

JSON Schema treats ``format`` as an annotation unless the validator is told to assert it,
and a pattern cannot know how many days a month has. So the contract is the schema *and*
these two format checks: a ``date`` must be a real calendar date and a ``date-time`` a real
instant. Everything that validates a briefing, here and in the tests, uses
:func:`contract_validator`, so "valid" has one meaning.

A consumer validating the export file must assert the same two formats.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

# Start empty: only the formats defined here are asserted, whatever optional packages
# happen to be installed.
FORMAT_CHECKER = FormatChecker(formats=())


@FORMAT_CHECKER.checks("date", raises=ValueError)
def _is_calendar_date(value: object) -> bool:
    if isinstance(value, str):
        date.fromisoformat(value)
    return True


@FORMAT_CHECKER.checks("date-time", raises=ValueError)
def _is_real_instant(value: object) -> bool:
    if isinstance(value, str):
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


def contract_validator(schema: dict[str, Any]) -> Draft202012Validator:
    """A validator for a contract schema that also asserts its date formats."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
