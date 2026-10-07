"""Resolve the ``ecod_commons.versions`` row that new rows must be stamped with.

Exists because ``domains``, ``f_group_assignments`` and ``t_group_only_assignments``
were all inserted without ``version_id``. ``ecod_commons.current_ecod`` inner-joins
``versions``, so 246,767 F-group assignments (exact propagation 2026-04-01, plus 20
auto-accessioned 2026-07-21) silently vanished from it. The rows were backfilled on
2026-10-06 and ``fga_version_id_not_null`` now rejects a NULL; see
``/data/ecod/database_versions/active_issues/2026-10-06_pyecod_prod_version_id.md``.

The version is the one the current development release points at
(``ecod_rep.releases.is_current_development`` -> ``ecod_version_id``). Point releases
(v295.2) have no ``versions`` row of their own by convention and map to their major
(v295). There is no fallback: if no development release is registered, inserting
would mean guessing, so this raises instead.
"""

from __future__ import annotations


class NoDevelopmentReleaseError(RuntimeError):
    """No usable current development release is registered in ecod_rep.releases."""


def current_development_version_id(conn) -> int:
    """Return the ``ecod_commons.versions.id`` of the current development release.

    Uses its own cursor on ``conn`` and does not commit.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT r.release_name, r.ecod_version_id, v.id
              FROM ecod_rep.releases r
              LEFT JOIN ecod_commons.versions v ON v.id = r.ecod_version_id
             WHERE r.is_current_development
        """)
        row = cursor.fetchone()
    finally:
        cursor.close()

    if row is None:
        raise NoDevelopmentReleaseError(
            "no ecod_rep.releases row has is_current_development = true; register the "
            "release being built before inserting domains"
        )
    release_name, ecod_version_id, version_id = row
    if version_id is None:
        raise NoDevelopmentReleaseError(
            f"current development release {release_name} has ecod_version_id="
            f"{ecod_version_id!r}, which is not a row in ecod_commons.versions"
        )
    return version_id
