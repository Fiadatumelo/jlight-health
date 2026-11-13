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

1. **TBProfiler-to-canonical AMR mapping:** the UI normaliser produces resistance evidence with `drug`, `confidence` (text), and gene/mutation annotations. The import/link payload currently maps `antibioticClass`/ `drugClass` but not `drug`; the backend stores `antibiotic_class`. The backend parses confidence as numeric, so textual confidence labels may be stored as null. Define a scientifically faithful mapping; do not invent numeric confidence or silently discard the source label.
2. **Mean coverage mapping:** the normaliser retains `meanDepth`, but the canonical payload reads `coverageMean`. The current UI hydration path does not expose a confirmed mean-coverage field either. Median depth must never be relabelled as mean coverage. Decide whether to preserve mean depth separately using existing schema/API support or leave it explicitly unavailable.
3. **QC/AMR replacement semantics:** the canonical upsert deletes existing QC and AMR rows for a run before inserting the submitted set. Existing schema constraints do not establish whether these are current snapshots or historical evidence. Inspect migrations, readers, reports and tests before changing this behaviour.
4. **Canonical versus compatibility persistence:** the importer saves canonical run data and then invokes the existing domain sync for `bioRuns`. Verify what the compatibility sync writes, which screens read each source, and that a failed canonical save cannot be masked by a legacy copy.
5. **Live verification:** authenticated staging import/readback, patient-link readback, Patient Journey/report visibility and cross-organisation/permission denials remain unverified. Mocks/source guards do not satisfy these release gates.


6. **AMR evidence fidelity:** the database currently has `gene`, `antibiotic_class`, `resistance_level`, numeric `confidence` and `database_version`, but no dedicated drug, mutation, source annotation, or textual-confidence columns. The current Bioinformatics UI also keeps richer TBProfiler variant evidence in the imported `bioRuns` payload. A faithful canonical/report contract must be agreed before extending or mapping these fields; do not mislabel an individual drug as an antibiotic class or coerce textual confidence to a number.
7. **Mean-depth field mismatch:** the normaliser retains source mean depth as `meanDepth`; the canonical importer reads `coverageMean`. The canonical QC schema has `coverage_mean`, but the frontend currently does not populate it from `meanDepth`. Preserve the metric's source meaning and units if a supported mapping is added.

## Completion loop

- [ ] Trace every Bioinformatics UI action to its API/database source and back to its read path.
- [ ] Resolve the confirmed result-mapping and persistence semantics without weakening tenant/workspace controls.
- [ ] Add or update focused tests for each corrected contract.
- [ ] Run the public TBProfiler reference/normalisation tests and relevant API/frontend tests.
- [ ] Perform authenticated staging end-to-end verification using authorised test records only.
- [ ] Verify Patient Journey and reports show the canonical, provenance-backed results.
- [ ] Verify cross-organisation and insufficient-permission requests fail closed.
- [ ] Repeat affected tests until clean; then prepare a PR into staging for review.

## Change controls

- No direct changes to `main`, the Render staging deployment branch, or production.
- No database migration or staging data mutation until the need and exact semantics are established.
- Preserve existing branches, worktrees, PRs, backups and completed work.
- Do not add a new workflow engine or recreate primary sequencing analysis inside JLIGHT.
