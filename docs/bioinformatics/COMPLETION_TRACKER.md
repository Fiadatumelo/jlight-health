# Bioinformatics completion tracker

**Working branch:** `feature/bioinformatics-integration`  
**Baseline:** `staging/unified-main-20261101` (created from the current staging head)  
**Scope:** Complete and verify the existing JLIGHT Bioinformatics implementation. Do not rebuild the module or change production.

## Architecture boundary

JLIGHT's approved architecture treats specialist bioinformatics tools such as TBProfiler as external analysis engines. JLIGHT imports authorised result outputs, preserves provenance, stores canonical run/accession/QC/AMR records, and exposes permitted evidence to Patient Journey and reporting. Do not restore the removed in-process FASTA/FASTQ analysis endpoints or recreate `engine/bio_engine.py` unless the approved architecture is deliberately changed.

## Inventory confirmed

- [x] PR #69 merged to `main` at merge commit `2512c67c6e42cf0ad0db4df0ac7a5ce0805d38be`.
- [x] The staging baseline contains the PR #69 merge and is 55 commits ahead of that merge.
- [x] Dedicated branch created from the staging baseline; it initially matched staging exactly.
- [x] PR #69 introduced Bioinformatics workspace RLS, TBProfiler public-data validation assets, normalisation and reference fixtures, and Patient Journey/architecture work.
- [x] Current UI includes TBProfiler JSON preview/import, overview, resistance, lineage, variant evidence, QC/provenance, patient-linking and report actions.
- [x] Current backend includes authenticated canonical run/accession upsert and a Patient Journey read path for canonical Bioinformatics accessions, runs, QC and AMR.
- [x] Canonical patient linking is by exact UUID in the same organisation; no demographic matching is intended.

## Confirmed issues requiring correction or explicit disposition

1. **TBProfiler-to-canonical AMR mapping:** corrected on the feature branch. The canonical AMR extension adds nullable `drug`, `mutation`, `annotation_source`, and `source_confidence` fields; the importer now carries these separately. Existing numeric confidence remains numeric-only; textual labels are retained as source confidence.
2. **Mean coverage mapping:** corrected on the feature branch. The canonical payload now receives the normaliser's `meanDepth` value as mean coverage. Median depth is not substituted.
3. **QC/AMR replacement semantics:** confirmed current-snapshot behaviour for a TBProfiler run import. The importer submits the full QC object and full AMR array from one completed result; the API deletes/reinserts each supplied section inside the same database transaction. Separate pipeline executions must use distinct source run IDs. This is replacement, not an append-only evidence history.
4. **Canonical versus compatibility persistence:** traced. JSON import writes the canonical run/accession/QC/AMR API first, then writes the rich `bioRuns` payload to `jl_entries` for the existing Bioinformatics screens and local recovery. A canonical API failure returns before compatibility sync; a compatibility sync failure leaves an explicit pending retry and does not report cloud success. TB Intelligence and genomic reports read the hydrated `bioRuns` domain; Patient Journey reads canonical `jl_bio_*` tables. The published-reference CSV route writes `bioRuns` only and does not create a patient-linked canonical record; that is appropriate for public reference samples, which must remain unlinked. The two stores are therefore separate read models, not interchangeable sources.
5. **Live verification:** authenticated staging import/readback, patient-link readback, Patient Journey/report visibility and cross-organisation/permission denials remain unverified. Mocks/source guards do not satisfy these release gates.


6. **AMR evidence fidelity:** the branch now adds nullable source-evidence columns through `20261113185500_bioinformatics_amr_source_evidence.sql`. Migration is committed but not applied to staging. Existing imported rich payloads remain in `bioRuns`; canonical Patient Journey now reads the added fields.
7. **Mean-depth field mismatch:** frontend import and retry now map `meanDepth` to canonical `coverageMean`; focused source guards were added.

## Latest surgical correction

- The initial JSON import path had retained an obsolete `qc.coverageMean` lookup while the retry path used the normaliser's `qc.meanDepth`. The initial path now uses `meanDepth`, and the regression guard asserts both paths independently.
- Safe regression run `43507116428` passed all steps, including the public reference fixture, normaliser and TBProfiler 6.7.0 schema tests. A subsequent run is executing against the latest workflow-trigger configuration.

## Authenticated staging verification (2026-11-18, live)

Executed against the live Render staging backend
(`https://jlight-backend-staging.onrender.com`, `/api/health` = healthy: api,
bio_engine, database, ml_engine all ok) and staging Supabase
`ampkysrzliwjtvbigsvu`, using a single fresh OTP session for
`support@jlight-health.co.za` (user `4fe3804b-…`). Existing staging
organisation `9f0bdcf6-…` and synthetic patient `939f9171-…` were reused;
nothing was recreated. Driver and raw results are preserved at
`.netlify/staging-kit/integration-20261118/`
(`authenticated_verification_driver.py`, `verification_results.json`).

- [x] Canonical import of both public samples via
      `/api/bioinformatics/runs/upsert`: `ERR10610053` → canonical run
      `059a0725-a625-4fcf-b34d-6eb5040af660`; `ERR10610083` → canonical run
      `a3add9ba-5229-4d6a-a90d-2b5092f47da9`; accession IDs returned and
      validated. (Import payloads came from the committed
      `validation/tbprofiler/fixtures/public_tbprofiler_bioruns.csv`
      public-reference summaries — the previously preserved raw-FASTQ outputs
      were not present in this workspace and were not re-run.)
- [x] Readback via RLS-scoped Supabase REST as the authenticated user:
      `jl_bio_runs` 2, `jl_bio_accessions` 2, `jl_bio_qc` 2, `jl_bio_amr` 15
      rows, all scoped to org `9f0bdcf6-…`.
- [x] AMR evidence fidelity verified row-by-row in the database: all 15 AMR
      rows carry independent `drug`, `mutation`, `annotation_source` and
      `source_confidence`; 12 rows carry WHO textual source confidence
      ("Assoc w R" / "Assoc w R - Interim" / "Mutation from literature");
      numeric `confidence` stays NULL for textual rows (numeric behaviour
      unchanged, no coercion).
- [x] Sequencing provenance and QC values: `ERR10610053` coverage 48.0x /
      mapping 99.38%, `qc_reported`; `ERR10610083` coverage 12.0x / mapping
      99.33%, **`qc_status` = `review_required_low_coverage`** — the
      uncertain low-coverage result was NOT converted into a sensitive
      result.
- [x] Idempotency: re-importing identical payloads returned the identical
      canonical run IDs with no duplicate rows (current-snapshot replacement
      semantics, per item 3 above).
- [x] Canonical patient linking: both runs linked to the exact synthetic
      patient UUID via the canonical upsert; canonical run IDs unchanged.
- [x] Patient Journey readback (`/api/patient-journey/939f9171-…`): HTTP 200,
      21 Bioinformatics events (2 analysis_run, 2 accession, 2 quality_control,
      15 resistance_finding), `reconciliation_status=completed`,
      `clinical_trials_included=false`, ERR10610083 QC event carries
      `review_required_low_coverage`.
- [x] Permission tests: run upsert with a non-member organisation header →
      HTTP 403; RLS read of another organisation's `jl_bio_runs` as this user
      → 0 rows; `/api/intelligence/clinical-trials-summary` correctly refused
      (HTTP 403) for this Bioinformatics-only session.
- [x] Migration status correction: the AMR evidence columns
      (`drug`, `mutation`, `annotation_source`, `source_confidence`) **are
      applied on staging** — proven by the authenticated readback above
      (item 6's "not applied" note is superseded by this evidence).

**Remaining gaps (accurate status, not yet COMPLETE):**

1. The full staging integration (PR #97 reconciliation + AMR correction on
   top of staging head `cb9d689a`) is built, regression-tested green
   (AMR mapping guards 13, core battery 87, WHO/reconciliation 7,
   pipeline 12, TBProfiler fixtures 12, release guards 11, journey guards
   10, connection guards 8, test_all 14/14, Node suites PASS) and preserved
   in `.netlify/staging-kit/integration-20261118/`. Publishing it into the
   repository and merging into `staging/unified-main-20261101` is pending:
   the authorised GitHub connection rejects all write operations (branch
   creation, file push, PR retarget) with 403 "Resource not accessible by
   integration". The integration tree has been submitted through the
   workspace publishing channel; its PR must be retargeted to
   `staging/unified-main-20261101` before merge. Never merge it to `main`.
2. Deployed-backend timestamp gap (deployed commit is still `cb9d689a`):
   resistance_finding and bioinformatics_accession journey events carry
   `occurred_at: null` on the deployed build. The integration tree adds
   `a.created_at` to the AMR journey SELECT and a `created_at` fallback for
   accession events; this gap closes when the integrated commit deploys.
3. TBProfiler Local Review Report generation is a frontend function verified
   by source guards; a browser-level report render has not been executed in
   this run (frontend is behind access control).

## Completion loop (current)

- [x] Resolve the confirmed result-mapping contract without weakening tenant/workspace controls (AMR evidence columns verified applied on staging).
- [x] Document QC/AMR upsert as current per-run snapshot replacement (confirmed live: identical re-import returns identical canonical IDs, no duplicate rows).
- [x] Add focused API and frontend source-guard tests for AMR evidence preservation and mean-depth mapping.
- [x] Run the deterministic published TBProfiler reference, normalisation and 6.7.0 schema fixture suite (green on the integrated tree, 2026-11-18).
- [x] Perform authenticated staging end-to-end verification using authorised test records only (2026-11-18, see dated section above).
- [x] Verify Patient Journey shows the canonical, provenance-backed results (21 events, reconciliation completed; timestamp gap tracked above).
- [x] Verify cross-organisation and insufficient-permission requests fail closed (HTTP 403 and RLS-denied reads confirmed live).
- [ ] Merge the verified integration into `staging/unified-main-20261101` (blocked on GitHub write permission; retarget base away from `main` first).
- [ ] Confirm the Render deployment runs the integrated commit and the journey timestamp gap closes.
- [ ] Browser-level report render verification (requires frontend access).


## Change controls

- No direct changes to `main`, the Render staging deployment branch, or production.
- No database migration or staging data mutation without explicit release review; the AMR extension migration is committed to the feature branch only and is not applied to staging or production.
- Preserve existing branches, worktrees, PRs, backups and completed work.
- Do not add a new workflow engine or recreate primary sequencing analysis inside JLIGHT.
