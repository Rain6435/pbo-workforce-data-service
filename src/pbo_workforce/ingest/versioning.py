"""Compare a sheet's accepted rows with the stored current versions (D16).

Imports never delete or overwrite workforce rows. For each natural key, the
new file either leaves the current version as it is, adds a version, or
closes the current one: because the values changed (``revised``), because
the key is no longer in the file (``absent``), or because its row is now
quarantined (``rejected``). This module decides which; the loader applies it.
"""

from collections.abc import Hashable, Mapping, Set
from dataclasses import dataclass, field

from pbo_workforce.db.tables import ClosedReason

# The values a version holds: headcount and FTE (None for RCMP/CAF).
type Measures = tuple[int, float | None]


@dataclass(frozen=True)
class StoredVersion:
    """A current version as stored in ``workforce_monthly``."""

    id: int
    measures: Measures


@dataclass(frozen=True)
class SnapshotDiff[K: Hashable]:
    """What one import changes for one source, by natural key."""

    unchanged: list[K] = field(default_factory=list[K])
    added: list[K] = field(default_factory=list[K])
    # Closed with reason ``revised`` and re-inserted with the new values.
    revised: list[K] = field(default_factory=list[K])
    # Closed with reason ``absent`` or ``rejected``, not re-inserted.
    closed: dict[ClosedReason, list[K]] = field(
        default_factory=dict[ClosedReason, list[K]]
    )


def diff_snapshot[K: Hashable](
    current: Mapping[K, StoredVersion],
    incoming: Mapping[K, Measures],
    rejected: Set[K],
) -> SnapshotDiff[K]:
    """Classify every key of ``current`` and ``incoming``.

    ``incoming`` holds the file's accepted rows; ``rejected`` the keys of its
    quarantined rows whose key could be read. Values are compared exactly: any
    change in the source is a revision. Order follows ``incoming``, then
    ``current``, so the report is deterministic.
    """
    diff = SnapshotDiff[K]()
    for key, measures in incoming.items():
        stored = current.get(key)
        if stored is None:
            diff.added.append(key)
        elif stored.measures == measures:
            diff.unchanged.append(key)
        else:
            diff.revised.append(key)
    for key in current:
        if key in incoming:
            continue
        reason = ClosedReason.REJECTED if key in rejected else ClosedReason.ABSENT
        diff.closed.setdefault(reason, []).append(key)
    return diff
