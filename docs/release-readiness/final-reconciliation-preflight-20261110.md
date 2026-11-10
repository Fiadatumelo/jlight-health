# JLIGHT reconciliation preflight — 2026-11-10

Release status: **BLOCKED**. This is an inventory, not staging acceptance. No source integration, database changes, merge, or deployment was performed.

## Baseline evidence

The supplied workspace HEAD is `9e05dca7d3c280c1b9d536e6a28513295b069666`, matching the production deployment SHA supplied with this run. The requested staging baseline is `ba5a9539c724b9b1cf18dc7ef4a79a1e8911b52e`. Branch creation is disabled by the execution environment. Applying release changes here would violate the required staging-first process.

GitHub API read-only observations:

- `staging/unified-main-20261101`: `ba5a9539c724b9b1cf18dc7ef4a79a1e8911b52e`.
- `integration/jlight-unified-reconciliation-20261106`: `e0d53e9580080dd031d5aa609cc659b3527b7c77`.
- `main`: `9e05dca7d3c280c1b9d536e6a28513295b069666`.

| PR | State | Target | Head |
|---|---|---|---|
| [#89](https://github.com/Fiadatumelo/jlight-health/pull/89) | OPEN | `staging/unified-main-20261101` | `e0d53e9580080dd031d5aa609cc659b3527b7c77` |
| [#91](https://github.com/Fiadatumelo/jlight-health/pull/91) | OPEN | `integration/jlight-unified-reconciliation-20261106` | `f37ae3563d531f453a2bba026ab3ed5e7c7313ef` |
| [#92](https://github.com/Fiadatumelo/jlight-health/pull/92) | MERGED | `integration/jlight-unified-reconciliation-20261106` | `04d59f0f5662ff0ab06fa9edd90a900bb9fbc463` |
| [#93](https://github.com/Fiadatumelo/jlight-health/pull/93) | MERGED | `staging/unified-main-20261101` | `ba183a30a4b70ae17b51442eb9b8c9285df04ce1` |

## File inventory for referenced pull requests

This table records GitHub file metadata only. It does not establish semantic compatibility or approve retaining any implementation. Full contents at pinned staging and integration commits, migration dependencies, and applicable tests require review in the correct staging-based workspace. Repeated PR references identify potential overlaps, not proven conflicts.

| File | PR change references | Retention decision / required work |
|---|---|---|
| `.github/workflows/bioinformatics-tests.yml` | #89 (added), #91 (modified), #92 (modified), #93 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `.github/workflows/jlight-authenticated-rls.yml` | #89 (modified), #92 (modified), #93 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `.github/workflows/jlight-safe-regression.yml` | #89 (modified), #92 (modified), #93 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `.github/workflows/jlight-tb-worker-image.yml` | #89 (added), #91 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `.github/workflows/tb-public-benchmark.yml` | #89 (added), #91 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `.github/workflows/tbprofiler-public-data-validation.yml` | #89 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `bioinformatics/Dockerfile.worker` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `bioinformatics/README.md` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `bioinformatics/TB_BENCHMARK_VALIDATION.md` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `bioinformatics/environment.yml` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `bioinformatics/tb_pipeline.py` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `bioinformatics/test_tb_pipeline.py` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `docs/bioinformatics-analysis-spec.md` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `index.html` | #89 (modified), #91 (modified), #92 (modified), #93 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-backend/api/app.py` | #89 (modified), #91 (modified), #92 (modified), #93 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-backend/tests/test_authenticated_supabase_rls.py` | #89 (modified), #92 (modified), #93 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-backend/tests/test_bioinformatics_release_guards.py` | #89 (added), #91 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-backend/tests/test_canonical_patient_bioinformatics_api.py` | #89 (added), #92 (added), #93 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-backend/tests/test_canonical_patient_bioinformatics_connection.py` | #89 (added), #91 (added), #92 (added), #93 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-backend/tests/test_patient_journey_release_guards.py` | #89 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `jlight-email-logo.svg` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `supabase/migrations/20261028190000_report_permissions_use_org_grants.sql` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `supabase/migrations/20261106194021_report_permissions_generate_and_trial_scope_correction.sql` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `supabase/migrations/20261108170100_bioinformatics_patient_identity_access.sql` | #89 (added), #92 (added), #93 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `supabase/tests/report_permissions_org_grants_assertions.sql` | #89 (added) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |
| `validation/tbprofiler/environment.yml` | #89 (modified) | BLOCKED: compare pinned staging and integration implementations before editing; preserve staging pending review. |

## Database and deployment boundaries

The verified staging Supabase project is `ampkysrzliwjtvbigsvu`. Applied migration state was not queried. Preserve `20261109132502_bioinformatics_patient_identity_access`; neither reapplication nor replacement was attempted. The unrelated preview project must not be used. No new database, queue, auth system, storage system, or service was introduced.

The supplied Netlify site is `jlight-health` (`08244605-5902-4291-a08f-e0aa0f466f56`), serving `https://jlight-health.co.za`. Its supplied production deployment SHA matches this checkout; live staging frontend URL, deployment branch and SHA remain unverified. Render staging service `jlight-backend-staging` and endpoint `https://jlight-backend-staging.onrender.com` were supplied by the request; deployed backend SHA and deployment ID remain unverified.

## Release gate register

| Area / test | Status | Evidence / blocker |
|---|---|---|
| Baseline identity | FAIL | Workspace is production SHA rather than required staging SHA. |
| Referenced PR states and file inventory | PASS | Read-only GitHub API metadata for #89, #91, #92, #93; semantic review remains outstanding. |
| File-by-file semantic reconciliation and other relevant PRs | BLOCKED | Correct staging workspace required; inventory above is partial evidence only. |
| Clean release-candidate branch and consolidated staging PR | BLOCKED | Environment disables branch creation and handles commits/PRs; staging-based run required. |
| Passwordless authentication and Mailbux | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Organisation onboarding, invitations and revocation | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Workspace switching and entitlement permissions | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Hospital workflows | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Laboratory workflows and imports | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Bioinformatics authenticated execution, queue and private storage | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Worker execution, isolation, retries, cancellation and cleanup | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Patient Journey exact UUID linking and reports | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Clinical Trials isolation and workflows | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| JC tool permissions and approval gates | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| RLS, tenant isolation and API security | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Report export and download permissions | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Retention, deletion and audit history | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Complete automated regression suite and CI | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Authenticated staging end-to-end tests | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| TBProfiler public-data benchmark | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Netlify staging deployment and commit alignment | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Render staging deployment, health and database connectivity | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Migration ledger and individual SECURITY DEFINER review | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Passwordless relevance of leaked-password protection warning | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |
| Rollback recovery rehearsal | NOT RUN | Required release-candidate baseline is not checked out; no acceptance evidence obtained. |

## Recovery and next action

Original branches and history were preserved. No application rollback is needed because application code was not changed. A verified recovery procedure remains NOT RUN: it must pin prior frontend/backend artifacts, confirm database compatibility and backup recovery, and exercise restoration in staging before release acceptance.

Resume in a staging-based workspace pinned to the requested baseline, confirm the staging frontend target, then complete semantic reconciliation before any source changes. Keep all mandatory gates closed until evidence is recorded. Production release remains outside this staging task.
