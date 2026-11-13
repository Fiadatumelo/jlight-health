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
4. **Canonical versus compatibility persistence:** the importer saves canonical run data and then invokes the existing domain sync for `bioRuns`. Verify what the compatibility sync writes, which screens read each source, and that a failed canonical save cannot be masked by a legacy copy.
5. **Live verification:** authenticated staging import/readback, patient-link readback, Patient Journey/report visibility and cross-organisation/permission denials remain unverified. Mocks/source guards do not satisfy these release gates.


6. **AMR evidence fidelity:** the branch now adds nullable source-evidence columns through `20261113185500_bioinformatics_amr_source_evidence.sql`. Migration is committed but not applied to staging. Existing imported rich payloads remain in `bioRuns`; canonical Patient Journey now reads the added fields.
7. **Mean-depth field mismatch:** frontend import and retry now map `meanDepth` to canonical `coverageMean`; focused source guards were added.

## Completion loop

- [ ] Trace every Bioinformatics UI action to its API/database source and back to its read path.
- [x] Resolve the confirmed result-mapping contract without weakening tenant/workspace controls (AMR migration still awaits staging review/application).
- [x] Document QC/AMR upsert as current per-run snapshot replacement: a complete TBProfiler result represents the current run result; API replacement is transaction-scoped. Historical pipeline reruns remain separate run IDs.
- [x] Add focused API and frontend source-guard tests for AMR evidence preservation and mean-depth mapping (safe regression workflow passed on 2026-11-13).
- [x] Run relevant API/frontend and broader safe regression workflow (passed 2026-11-13).
- [ ] Run the public TBProfiler reference/normalisation fixture suite separately.
- [ ] Perform authenticated staging end-to-end verification using authorised test records only.
- [ ] Verify Patient Journey and reports show the canonical, provenance-backed results.
- [ ] Verify cross-organisation and insufficient-permission requests fail closed.
- [ ] Repeat affected tests until clean; then prepare a PR into staging for review.

## Change controls

- No direct changes to `main`, the Render staging deployment branch, or production.
- No database migration or staging data mutation without explicit release review; the AMR extension migration is committed to the feature branch only and is not applied to staging or production.
- Preserve existing branches, worktrees, PRs, backups and completed work.
- Do not add a new workflow engine or recreate primary sequencing analysis inside JLIGHT.
