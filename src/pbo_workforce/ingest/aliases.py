"""Reviewed map of known department-name misspellings (D6).

Each entry maps a *normalized* variant (``normalize_name_key``) to the
canonical English long name in the Departments sheet. Entries are added only
after a person has confirmed the variant in the source data; there is no
fuzzy matching, so any other unknown name is quarantined as
``UNKNOWN_DEPARTMENT`` for review. The importer copies this map into the
``department_alias`` table so the database records which aliases were used.
"""

from collections.abc import Mapping

KNOWN_ALIASES: Mapping[str, str] = {
    # Federal Public Service sheet, 201511 / Term (Excel row 2672): doubled
    # final "e". Confirmed against data/data.xlsx; no department of that name.
    "Privy Council Officee": "Privy Council Office",
}
