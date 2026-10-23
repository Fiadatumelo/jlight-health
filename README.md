# JLIGHT — Health Intelligence and Workflow Platform

JLIGHT is a health-intelligence and traceability platform intended to work above existing healthcare systems. It organises and analyses authorised operational data to help teams identify gaps, delays, inconsistencies, and patterns that require review.

## Product boundary

**JLIGHT is not a laboratory analyser.** It does not collect or physically process specimens, perform diagnostic tests, operate or control analysers, or independently generate laboratory measurements. Laboratory results and QC records must originate from authorised people or existing systems.

## Intelligence journey

1. **Ingest** authorised data from supported workflows or configured source systems.
2. **Baseline** the available records and establish relevant reference patterns.
3. **Detect** potential omissions, inconsistencies, unusual trends, delays, and risks.
4. **Reason** by presenting the signal, supporting context, and source records for human review.
5. **Deliver** traceable Decision Cards, alerts, and reports for authorised users.

## Domains

- **Laboratory / LIMS:** workflow and accession traceability, order/result status visibility, data-quality checks, turnaround-time monitoring, and intelligence over imported or authorised recorded data. JLIGHT does not perform tests.
- **Hospital / Health Informatics:** patient-journey visibility, order/result completeness, turnaround-time monitoring, ward workflow signals, and cross-section traceability.
- **Clinical Trials:** protocol visit-window tracking, consent and deviation visibility, safety-event deadline monitoring, participant follow-up signals, and trial auditability. Clinical-trial workflows remain distinct where protocol or regulatory requirements demand it.
- **Bioinformatics:** analysis of imported or supplied bioinformatics outputs and quality metrics. JLIGHT is not a sequencing instrument or wet-lab system.

The non-trial domains should contribute to one traceable patient journey when authorised data and validated integrations are available.

## Decision Cards and auditability

Decision Cards should make the signal, source data, rationale, recommended next step, status, and audit history visible. They support professional review and do not replace clinical judgement, laboratory validation, or regulated source systems.

## User entry and shared journey

On entry, users choose Laboratory, Hospital / Health Informatics, Bioinformatics, or Clinical Trials. The shared Patient Journey view connects authorised non-trial records by existing patient ID across Hospital, Laboratory, and Bioinformatics. It reports missing or unmatched links without inferring identity from names or demographics. Clinical Trials use a separate participant workflow and are excluded from the shared non-trial journey.

## Integrations and readiness

- **CSV / TSV source import is implemented** for patient registry, laboratory order status, imported laboratory result records, hospital admissions/orders, and bioinformatics outputs. It validates headers and required fields, previews before saving, skips duplicate source IDs, reports unmatched patient references, records an audit event, and reports cloud-sync failures. Offline imports require a de-identification attestation and reject direct-identifying columns.
- **HL7, FHIR, CTMS, HIS, and custom REST/API adapters are not claimed to be live.** They still require configuration, permissions, field mapping, error handling, audit logging, and end-to-end validation in the target environment.
- A connector label or protocol name is not proof of a working integration. Source systems remain authoritative; JLIGHT stores and analyses supplied records and does not perform diagnostic tests or generate laboratory measurements.

## Deployment and release

The repository contains the web application and supporting domain workflows. Database migrations, persistence, access controls, integrations, browser journeys, and production deployment must be independently verified in the target environment before a release is declared complete.

Built in South Africa. For South Africa.
