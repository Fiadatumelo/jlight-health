# Read-only Bioinformatics staging catalog check

Run from the repository root with the existing backend requirements installed:

```sh
python jlight-backend/scripts/inspect_bioinformatics_schema.py
```

The check reads `JLIGHT_STAGING_DATABASE_URL` from the environment. Do not put a
connection string in a command, source file or report. Without this variable it
returns `BLOCKED` with exit status 2 and does not connect or invent a schema.
`JLIGHT_STAGING_PROJECT_REF` is optional: the default is the staging reference
already pinned by the existing RLS tests; an explicitly different value is refused.
Direct Supabase and pooler connections must match that reference. Host-address
overrides, implicit libpq service overrides and non-TLS connections are refused.

Connection and statement timeouts are bounded. The connection requests read-only
mode before its first transaction, verifies it before inspecting catalogs, and
rolls back and closes on completion or failure. It does not insert fixtures, run
migrations, change roles, grant permissions, or read patient/evidence records.

The JSON output records canonical table presence, columns/defaults, constraints,
indexes, RLS flags/policies, visible table grants, triggers, permission-helper
metadata, the connection role's bypass flags, and the two relevant migration
ledger versions when readable. Function bodies and SQL literal values are not
exported. Errors omit connection/driver details. Catalog visibility can depend on
the connecting role; inaccessible catalogs yield `BLOCKED`, not fabricated results.

`INCOMPLETE_SCHEMA` means one or more expected tables were not found. Both this
state and `BLOCKED` return exit status 2. `CATALOG_INSPECTED` returns 0, but means
only that the catalog query completed and the expected tables were present. It
does **not** validate constraints against the application contract or pass a release
gate. `live_workflow_verified` always remains false.

Reconcile the output against the historical PR #92 implementation before changing
application writes. Lineage/variant storage, immutable audit and evidence revision
semantics, report storage, effective API privileges and staging migration state
still require explicit verification. Never use this command's catalog result as
proof that authenticated import, readback, linking, reporting or RLS tests passed.

`tests/test_bioinformatics_schema_inspection.py` uses a synthetic connection to
test the inspector's safety paths. It deliberately supplies no invented canonical
table definitions or patient records and is not a live database integration test.
