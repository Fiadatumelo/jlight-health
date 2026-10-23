# JLIGHT — Health Intelligence Platform

JLIGHT is a health-intelligence and traceability platform for South African healthcare settings. It analyses data from existing systems and workflows to identify gaps, risks, delays, and patterns that need human review.

**JLIGHT is not a laboratory analyser.** It does not collect or process specimens, perform diagnostic tests, control instruments, or independently produce laboratory measurements. Laboratory results and other source data must come from authorised people or existing systems.

## Proposal-aligned scope

JLIGHT follows one traceable intelligence journey across the relevant domains:

1. **Ingest** — receive data entered by users or supplied by existing systems and files.
2. **Baseline** — organise available data and establish relevant reference patterns.
3. **Detect** — identify potential omissions, inconsistencies, unusual trends, delays, and risks.
4. **Reason** — present the detected signal, context, and supporting data for review.
5. **Deliver** — create Decision Cards, alerts, and traceable reports for authorised users.

## Domains

- **Laboratory / LIMS:** operational workflow visibility, specimen and order traceability, result-status tracking, data-quality checks, and intelligence based on data supplied by existing laboratory workflows. JLIGHT does not perform the test or analyse a specimen physically.
- **Hospital / Health Informatics:** patient-journey visibility, order/result completeness, turnaround-time monitoring, and cross-section traceability.
- **Clinical Trials:** protocol visit-window tracking, safety-event deadline visibility, participant follow-up signals, and trial auditability.
- **Bioinformatics:** analysis of imported or supplied bioinformatics outputs and quality metrics. JLIGHT is not a sequencing instrument or a wet-lab system.

Clinical-trial workflows remain distinct where protocol and regulatory requirements demand it. The other domains can contribute to a coherent patient journey when authorised data and integrations are available.

## Decision Cards and traceability

Decision Cards should make the signal, source data, rationale, recommended next step, status, and audit history visible. They support professional review and do not replace clinical judgement, laboratory validation, or regulated source systems.

## Integrations and readiness

CSV/file ingestion and standards-based interfaces may be used where implemented and validated. An interface must not be described as live, automatic, or production-ready unless that capability has been tested end-to-end in the target environment. JLIGHT does not claim an integration merely because a protocol is supported in principle.

## Technical implementation

The repository contains the JLIGHT web application and supporting database schema. Deployment, integrations, security controls, and data persistence must be verified in the target environment before release claims are made.

## Product boundary

**JLIGHT receives and interprets data; it does not process samples.** Features that imply instrument control, physical testing, or JLIGHT-generated diagnostic measurements are outside the product scope and should not be presented as capabilities.

---

Built in South Africa. For South Africa.
