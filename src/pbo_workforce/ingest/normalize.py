"""Department-name normalization and resolution (D6).

Two different operations, kept apart on purpose:

* ``canonical_name`` is what we *store*: the Departments-sheet name with only
  outer whitespace removed, so the typographic apostrophe (U+2019) is preserved.
* ``normalize_name_key`` is what we *compare*: it also absorbs the layout
  noise found in the sources (doubled spaces, apostrophe style).
"""

import unicodedata
from collections.abc import Iterable, Mapping

# Apostrophe variants treated as the same character when matching.
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'"})


class AliasConfigError(Exception):
    """``KNOWN_ALIASES`` is inconsistent with the Departments sheet."""


def canonical_name(raw: str) -> str:
    """The name as stored: the source text without outer whitespace."""
    return raw.strip()


def normalize_name_key(raw: str) -> str:
    """The key used to match names across sheets.

    Unicode NFC (so composed and decomposed accents compare equal), internal
    whitespace collapsed to one space, outer whitespace removed, and curly
    apostrophes compared as straight ones. Case is *not* folded: no case
    variants occur in the sources, and every relaxation is a chance to merge
    two names that should stay distinct.
    """
    text = unicodedata.normalize("NFC", raw).translate(_APOSTROPHES)
    return " ".join(text.split())


class DepartmentResolver:
    """Resolves raw department names to canonical English long names."""

    def __init__(self, names: Iterable[str], aliases: Mapping[str, str]) -> None:
        """Build from canonical names and the reviewed alias map.

        Raises:
            AliasConfigError: if an alias points at a name that is not a
                department, or shadows a real department's key. Either means
                the alias map no longer matches the data and needs review.
        """
        self._by_key: dict[str, str] = {normalize_name_key(n): n for n in names}
        self._alias_targets: dict[str, str] = {}
        for alias, target in aliases.items():
            alias_key = normalize_name_key(alias)
            target_name = self._by_key.get(normalize_name_key(target))
            if target_name is None:
                raise AliasConfigError(
                    f"alias {alias!r} points to unknown department {target!r}"
                )
            if alias_key in self._by_key:
                raise AliasConfigError(f"alias {alias!r} is itself a department")
            self._alias_targets[alias_key] = target_name

    def resolve(self, raw: str) -> str | None:
        """Canonical English name for ``raw``, or ``None`` if unknown."""
        key = normalize_name_key(raw)
        return self._by_key.get(key) or self._alias_targets.get(key)

    @property
    def aliases(self) -> Mapping[str, str]:
        """Normalized alias key -> canonical English name, for persistence."""
        return dict(self._alias_targets)
