"""Tenure label parsing (D7)."""

import pytest

from pbo_workforce.domain.tenure import API_FIELD, FTE_TENURES, Tenure, parse_tenure


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Indeterminate", Tenure.INDETERMINATE),
        ("Term", Tenure.TERM),
        ("Casual", Tenure.CASUAL),
        ("Student", Tenure.STUDENT),
        ("Missing", Tenure.MISSING),
        ("Combined", Tenure.COMBINED),
        ("Term ", Tenure.TERM),  # variant found in the source
        ("Indeterminate ", Tenure.INDETERMINATE),  # variant found in the source
        ("  casual\t", Tenure.CASUAL),
        ("STUDENT", Tenure.STUDENT),
    ],
)
def test_parse_tenure_known_labels(raw: str, expected: Tenure):
    assert parse_tenure(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "Permanent", "Terms", "Term-ish"])
def test_parse_tenure_blank_or_unknown_is_none(raw: str | None):
    assert parse_tenure(raw) is None


def test_blank_is_not_mapped_to_missing():
    # D7: "Missing" is a reported category; blank is a data error.
    assert parse_tenure("") is not Tenure.MISSING


def test_fte_tenures_have_api_fields_in_order():
    assert [API_FIELD[t] for t in FTE_TENURES] == [
        "indeterminate",
        "term",
        "casual",
        "student",
        "missing",
    ]
    assert Tenure.COMBINED not in FTE_TENURES
