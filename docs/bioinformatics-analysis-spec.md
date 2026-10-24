# JLIGHT Bioinformatics Analysis — implementation specification

## Purpose and boundary

Bioinformatics Analysis is the only JLIGHT domain permitted to receive and process raw patient-derived sequence data. This is a computational workflow, not an AI-generated interpretation of uploaded text and not a sequencing instrument. Sequencing/base-calling and wet-lab work remain in the source laboratory. JLIGHT analyses sequence files supplied by an authorised laboratory or researcher.

The first release is a research/technical workflow. It must not be presented as a validated diagnostic device or used as the sole basis for treatment decisions. Clinical use requires assay-specific validation, quality management, authorised review, and applicable regulatory, ethics and governance approval.

## South African priority order

1. **Tuberculosis, including drug-resistant TB — first pipeline.** NICD's Centre for Tuberculosis performs national surveillance and reference-laboratory work, including genomic surveillance and targeted NGS work on drug resistance. Start with Mycobacterium tuberculosis complex Illumina FASTQ and a version-pinned TBProfiler workflow for lineage and resistance-associated variant prediction.
2. **HIV-1 drug-resistance sequencing.** South Africa has substantial HIV laboratory/genotyping capacity. Use a maintained, versioned HIVDR workflow/database and subtype-aware QC; do not implement resistance rules from scratch or treat arbitrary FASTA as a validated clinical result.
3. **Priority respiratory viruses and outbreak surveillance.** SARS-CoV-2 and influenza where suitable sequencing design and validated references exist. Use nf-core/viralrecon or an equivalent pinned, independently tested pipeline selected per library preparation and sequencing platform.
4. **Healthcare-associated and priority antimicrobial-resistant organisms.** Expand to organism-specific workflows for pathogens such as carbapenem-resistant Enterobacterales and other ESKAPEE organisms. Species identification, resistance inference and outbreak clustering need separate validated methods and databases.
5. **Other locally relevant pathogens.** Malaria, HPV and emerging/outbreak pathogens only after input assay, references, evidence sources and validation criteria are defined.

These are prioritisation tiers, not a claim that all pipelines are already implemented.

## User experience

- **New analysis:** choose a supported organism/workflow and sequencing platform; see required input types and intended use before uploading.
- **Import files:** accept paired or single-end FASTQ (fastq.gz/fq.gz), or consensus FASTA/VCF only where that workflow explicitly supports it. Validate compression, pairing, sample sheet, file size, checksums and metadata. Reject unsupported formats clearly.
- **Connect data:** add authorised SFTP/S3-compatible storage or source-system connectors. Use least-privilege credentials stored server-side; test the connection and list eligible files before starting a run. Never ask users to paste tokens into ordinary form fields.
- **Preflight:** show sample IDs, pair matching, platform/library type, runtime/resource class, reference/database version, data location, authority/consent attestation, and estimated cost where applicable.
- **Run:** create an immutable job record, queue work to an isolated compute worker, show stage-level status, and support cancellation/retry without duplicate publication.
- **Results:** QC summary, read counts, coverage/depth and limitations; pipeline/tool/database versions; lineage or variants/resistance predictions only where supported; downloadable machine-readable outputs and a human-readable report. Link every result to its run, input checksums, parameters, logs and quality flags.
- **Review:** mark findings pending review, accepted, rejected or requiring repeat. Preserve reviewer, timestamp and reason in the audit trail.
- **Export to JLIGHT intelligence:** publish only allow-listed, minimum-necessary derived results after review policy (e.g. pathogen/lineage/resistance marker, QC status, time period, approved geographic granularity, provenance). Do not copy raw reads, FASTQ/FASTA, full variant files, patient identifiers or free-text clinical metadata into Hospital/Laboratory/general intelligence. Cross-domain linkage uses a pseudonymous study/patient key and explicit policy.
- **Research and surveillance:** permissioned, disclosure-controlled cohort summaries; distinguish counts from rates; do not trigger an outbreak alert from one sequence alone.

## Real pipeline architecture

1. **Web app:** upload to a private quarantine bucket using short-lived signed URLs. Never place raw sequence bytes in browser logs, analytics, telemetry or ordinary database rows.
2. **API/control plane:** validate role, organisation/tenant, workflow eligibility, file size/type/checksum, authority/consent metadata, and create a run manifest. Enforce tenant isolation on every object and API operation.
3. **Queue and isolated worker:** run Nextflow in pinned containers on a worker with no public ingress and narrowly scoped egress. Never execute uploaded content. Apply resource/time quotas, cancellation, retries and per-job scratch storage.
4. **Workflow registry:** allow-listed workflow IDs and immutable version/digest; never accept arbitrary shell commands, container images, references or workflow parameters from the client.
5. **Versioned references/databases:** pin approved reference genomes and variant/resistance databases, record versions/licences, and update through review.
6. **Results store:** raw/intermediate data stay in the isolated bioinformatics workspace. Publish results atomically after QC/completion; mark partial/failed outputs clearly. Require short-lived signed downloads, encryption, retention/deletion policy and access audit.
7. **JLIGHT intelligence adapter:** separate service boundary receives only approved derived fields after validation and review. It can detect cross-run trends, data-quality anomalies and potential clusters, but cannot rewrite pipeline results or make autonomous diagnoses.

## Initial TB workflow stages

- Validate sample sheet and paired/single-end FASTQ inputs.
- Verify checksums and compression; report empty/corrupt files.
- Run FastQC and MultiQC.
- Run a pinned TBProfiler version/database for M. tuberculosis complex lineage and drug-resistance-associated variant prediction on supported input types.
- Preserve raw tool outputs, JSON/CSV, logs, tool/database versions and run manifest.
- Gate publication on pipeline exit status and configured QC thresholds. QC failure must never be silently converted to a negative result.
- Label resistance output as a bioinformatics prediction requiring interpretation under the laboratory's validated method; never claim phenotypic susceptibility testing was performed.

A separate viral workflow should use nf-core/viralrecon only for compatible virus/library/platform combinations. Human germline/somatic analysis (e.g. nf-core/sarek) is not part of this pathogen-first release and needs separate governance and consent controls.

## Raw sequence data safeguards

- Raw sequence files are sensitive and may be identifying; pseudonymisation does not make genomic data intrinsically anonymous.
- Require role/tenant access, purpose limitation, authority/consent attestation, ethics approval where applicable, retention/deletion controls, data-sharing agreements, and cross-border transfer review.
- Prefer South Africa-hosted processing/storage where feasible and approved. International transfer requires legal and institutional review, including applicable POPIA requirements.
- Raw sequence access is denied to Hospital, Laboratory and Clinical Trials roles by default. No shared patient-journey endpoint may return raw files, raw reads, full variant data or direct identifiers.
- Never send raw sequence data to general-purpose LLM prompts, external analytics, telemetry, error trackers or support tickets.
- Separate synthetic fixtures from real data and test cross-tenant isolation, signed URL expiry, failed uploads, cancellation, deletion, audit records and denied-access paths.

## Validation and release gates

Before calling a pipeline production-ready: pin workflow/container/tool/database versions and verify licences; run upstream test profiles and project-owned fixtures for paired/single-end reads, malformed/corrupt and empty files, mismatched pairs, low-quality samples and known reference materials; compare outputs against documented expected results and an independently reviewed reference set; measure repeatability, provenance, failure recovery, concurrency/resource limits, cancellation and partial-output handling; complete a threat model and tenant/role security tests; verify raw sequence cannot leak through logs, exports, cross-domain views or object-store policies; complete laboratory validation and applicable ethics/regulatory/clinical governance before clinical claims. Use synthetic/public benchmark data in staging first, never identifiable patient reads as development fixtures.

## Delivery sequence

**Phase 1 — TB research MVP:** private upload, file validation, run manifest, isolated Nextflow worker, FastQC/MultiQC, pinned TBProfiler, versioned results/report, audit log, synthetic/public benchmark validation. No live clinical claims.

**Phase 2 — Secure connectors and operations:** SFTP/S3-compatible connectors, signed uploads/downloads, quotas, retention/deletion, job monitoring, retry/cancel and operational alerting.

**Phase 3 — HIV drug-resistance workflow:** select and validate a maintained pipeline/database with HIV subtype coverage, assay-specific thresholds and expert review.

**Phase 4 — Viral and AMR surveillance:** compatible viral workflows and selected bacterial WGS workflows; then cohort-level intelligence and controlled cluster signals.

## Research basis

- NICD Centre for Tuberculosis: https://www.nicd.ac.za/centres/centre-for-tuberculosis/
- NICD CHARM / antimicrobial resistance: https://www.nicd.ac.za/centres/centre-for-healthcare-associated-infections-antimicrobial-resistance-and-mycoses/
- NHLS Priority Programmes (HIV, TB, HPV): https://www.nhls.ac.za/priority-programmes/
- nf-core/viralrecon documentation: https://nf-co.re/viralrecon/dev/
- TBProfiler module documentation: https://nf-co.re/modules/tbprofiler_profile
- Stanford HIV Drug Resistance Database: https://hivdb.stanford.edu/
- South African National Department of Health, Ethics in Health Research Guidelines (2024): https://ftp.knowledgehub.health.gov.za/elibrary/south-african-ethics-health-research-guidelines-principles-processes-and-structures-2024
- Academy of Science of South Africa, POPIA Compliance Framework for Research: https://www.assaf.org.za/popia/

This document defines the implementation target. It does not assert that the workflow, secure compute worker or source connectors are already deployed.