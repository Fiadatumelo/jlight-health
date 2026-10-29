# JLIGHT TB benchmark validation protocol (research-only)

## Purpose

Validate the TB-only pipeline against publicly accessible, reproducible sequence data before any production release. This protocol does not authorise clinical use, patient management, or a claim of diagnostic performance.

## First benchmark: public reference-strain reads

Start with a public *M. tuberculosis* H37Rv reference-strain run (a laboratory reference strain, not a participant/patient cohort), for example SRA accession **SRR20082812**, reported as H37Rv sequence data in a published methods paper. Verify accession metadata, read layout, downloadable files, and the source paper before use; if the accession is withdrawn, unavailable, or its metadata conflicts, stop and select another public reference-strain accession with documented provenance.

Sources:
- NCBI SRA public read archive: https://www.ncbi.nlm.nih.gov/sra
- Published data availability listing SRR20082812 among H37Rv isolates: https://pmc.ncbi.nlm.nih.gov/articles/PMC11389143/
- TB-Profiler research-use-only statement and official tool: https://tbdr.lshtm.ac.uk/ and https://github.com/jodyphelan/TBProfiler

Public accessibility is not a blanket licence for every use of every linked metadata field. Use sequence reads and metadata only where the archive's access status and the source terms permit the planned research validation. Do not download controlled-access data.

## Pseudonymous labels

Within JLIGHT validation reports, label the benchmark sample **PATION-001** (then PATION-002, etc.). The label is a project alias, not a claim that the sequence came from a patient. Keep the public accession and source citation in a separate benchmark provenance file, not in end-user-facing patient records. Do not import names, dates of birth, addresses, precise locations, clinical histories, or other participant identifiers.

For a public clinical-isolate dataset, do not assume that replacing names with PATION IDs anonymises genomic data: pathogen genomes and linked metadata may still permit re-identification or disclose sensitive information. Use only an access-cleared dataset, minimise metadata, assess linkage risk, and obtain the necessary institutional/ethics and data-governance approvals before any clinical-isolate cohort is used. The first benchmark should therefore use a reference strain rather than human-participant metadata.

## Execution gates

1. Record the accession, source URL/DOI, retrieval date, archive access status, read layout, file checksums, and any reuse restrictions.
2. Download reads into a private, temporary benchmark workspace. Never put raw FASTQ files in the public web root, frontend bundle, ordinary application tables, logs, analytics, or AI prompts.
3. Use the pinned environment from `environment.yml`; additionally record the exact worker image digest and exact TBProfiler mutation database release/commit. Stop if the database release cannot be identified.
4. Run FASTQ structural checks, paired-read count/name synchronisation, FastQC, MultiQC and TBProfiler. Save full stdout/stderr logs and the run manifest in restricted storage.
5. Independently compare output to a trusted reference/expected profile for that exact accession and version. Record discrepancies, QC failures, tool/database versions and any deviations. A reference-strain smoke test verifies execution and provenance, not sensitivity/specificity or clinical validity.
6. Repeat a deliberately malformed-input and deliberate tool-failure test. Verify failures are clearly labelled and never rendered as a negative TB or resistance result.
7. Delete temporary raw reads under the benchmark retention policy after checksums and approved outputs are retained. Record deletion.
8. Keep production deployment blocked until the real-data run is reviewed, tenant isolation and private storage are verified, and the full authenticated upload-to-report path passes in staging.

## Acceptance report template

- Benchmark alias: PATION-001
- Public accession and source citation (restricted provenance record):
- Retrieval date / access status / reuse conditions:
- Read layout / file checksums / read counts:
- FastQC / MultiQC status:
- TBProfiler version:
- Mutation database release/commit:
- Expected profile source and version:
- Observed lineage and resistance output (technical review only):
- Agreement / discrepancies:
- Failure-path test:
- Reviewer and review date:
- Data deletion confirmation:
- Outcome: PASS / FAIL / BLOCKED

**Do not mark this protocol as executed until actual tool logs and results have been reviewed.** The CI mock-tool tests are not a substitute for this benchmark.
