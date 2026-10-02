"""Snapshot comparison: one test per kind of change (D16)."""

from pbo_workforce.db.tables import ClosedReason
from pbo_workforce.ingest.versioning import StoredVersion, diff_snapshot

# Keys are opaque to diff_snapshot; short strings keep the tests readable.
ASC_TERM = "asc/2021-12/term"
ASC_STUDENT = "asc/2021-12/student"
PCO_TERM = "pco/2015-11/term"


def test_same_values_are_unchanged():
    diff = diff_snapshot(
        {ASC_TERM: StoredVersion(1, (9, 7.33))}, {ASC_TERM: (9, 7.33)}, set()
    )
    assert (diff.unchanged, diff.added, diff.revised, diff.closed) == (
        [ASC_TERM],
        [],
        [],
        {},
    )


def test_new_key_is_added():
    diff = diff_snapshot({}, {ASC_TERM: (9, 7.33)}, set())
    assert diff.added == [ASC_TERM]


def test_changed_fte_is_revised():
    diff = diff_snapshot(
        {ASC_TERM: StoredVersion(1, (9, 7.33))}, {ASC_TERM: (9, 7.5)}, set()
    )
    assert (diff.revised, diff.unchanged, diff.closed) == ([ASC_TERM], [], {})


def test_changed_headcount_is_revised():
    diff = diff_snapshot(
        {ASC_TERM: StoredVersion(1, (9, 7.33))}, {ASC_TERM: (10, 7.33)}, set()
    )
    assert diff.revised == [ASC_TERM]


def test_comparison_is_exact():
    # Any change in the source is a revision; there is no tolerance.
    diff = diff_snapshot(
        {ASC_TERM: StoredVersion(1, (9, 7.333333333333335))},
        {ASC_TERM: (9, 7.333333333333334)},
        set(),
    )
    assert diff.revised == [ASC_TERM]


def test_missing_key_is_closed_as_absent():
    diff = diff_snapshot({ASC_TERM: StoredVersion(1, (9, 7.33))}, {}, set())
    assert diff.closed == {ClosedReason.ABSENT: [ASC_TERM]}


def test_quarantined_key_is_closed_as_rejected():
    diff = diff_snapshot({PCO_TERM: StoredVersion(1, (20, 15.8))}, {}, {PCO_TERM})
    assert diff.closed == {ClosedReason.REJECTED: [PCO_TERM]}


def test_rejected_key_that_was_never_stored_changes_nothing():
    diff = diff_snapshot({}, {}, {PCO_TERM})
    assert (diff.added, diff.revised, diff.closed) == ([], [], {})


def test_headcount_only_rows_compare_with_none_fte():
    diff = diff_snapshot(
        {"rcmp": StoredVersion(1, (20130, None))}, {"rcmp": (20130, None)}, set()
    )
    assert diff.unchanged == ["rcmp"]


def test_order_follows_incoming_then_current():
    current = {
        ASC_STUDENT: StoredVersion(2, (2, 1.0)),
        PCO_TERM: StoredVersion(3, (20, 15.8)),
        ASC_TERM: StoredVersion(1, (9, 7.33)),
    }
    incoming = {ASC_TERM: (9, 7.5), "new": (1, 1.0), ASC_STUDENT: (2, 1.0)}

    diff = diff_snapshot(current, incoming, set())

    assert diff.revised == [ASC_TERM]
    assert diff.added == ["new"]
    assert diff.unchanged == [ASC_STUDENT]
    assert diff.closed == {ClosedReason.ABSENT: [PCO_TERM]}
