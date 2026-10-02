"""Department-name normalization and resolution (D6)."""

import unicodedata

import pytest

from pbo_workforce.ingest.aliases import KNOWN_ALIASES
from pbo_workforce.ingest.normalize import (
    AliasConfigError,
    DepartmentResolver,
    canonical_name,
    normalize_name_key,
)

CURLY = "\u2019"


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("Public Service  Commission of Canada", "Public Service Commission of Canada"),
        (" Global Affairs Canada", "Global Affairs Canada"),
        ("Canadian Armed Forces ", "Canadian Armed Forces"),
        ("\tA \n B ", "A B"),
        (f"Normes d{CURLY}accessibilité Canada", "Normes d'accessibilité Canada"),
        ("Normes d'accessibilité Canada", "Normes d'accessibilité Canada"),
    ],
)
def test_normalize_name_key(raw: str, key: str):
    assert normalize_name_key(raw) == key


def test_curly_and_straight_apostrophes_match():
    assert normalize_name_key(f"d{CURLY}inspection") == normalize_name_key(
        "d'inspection"
    )


def test_key_keeps_case():
    assert normalize_name_key("privy council office") != normalize_name_key(
        "Privy Council Office"
    )


def test_canonical_name_strips_only_outer_whitespace():
    raw = f"  Normes d{CURLY}accessibilité  Canada "
    assert canonical_name(raw) == f"Normes d{CURLY}accessibilité  Canada"


def test_decomposed_accents_are_composed_for_matching():
    decomposed = unicodedata.normalize("NFD", "Forces armées")
    assert normalize_name_key(decomposed) == "Forces armées"


@pytest.fixture
def resolver() -> DepartmentResolver:
    return DepartmentResolver(
        ["Privy Council Office", "Public Service Commission of Canada"],
        KNOWN_ALIASES,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "Privy Council Office",
        " Privy Council Office ",
        "Privy  Council Office",
        "Privy Council Officee",  # reviewed alias
    ],
)
def test_resolver_resolves_variants(resolver: DepartmentResolver, raw: str):
    assert resolver.resolve(raw) == "Privy Council Office"


@pytest.mark.parametrize(
    "raw", ["Privy Council Offic", "privy council office", "PCO", ""]
)
def test_resolver_does_no_fuzzy_matching(resolver: DepartmentResolver, raw: str):
    assert resolver.resolve(raw) is None


def test_resolver_exposes_aliases_for_persistence(resolver: DepartmentResolver):
    assert resolver.aliases == {"Privy Council Officee": "Privy Council Office"}


def test_alias_to_unknown_department_fails():
    with pytest.raises(AliasConfigError, match="unknown department"):
        DepartmentResolver(["Global Affairs Canada"], KNOWN_ALIASES)


def test_alias_that_is_a_real_department_fails():
    with pytest.raises(AliasConfigError, match="is itself a department"):
        DepartmentResolver(
            ["Privy Council Office", "Privy Council Officee"], KNOWN_ALIASES
        )
