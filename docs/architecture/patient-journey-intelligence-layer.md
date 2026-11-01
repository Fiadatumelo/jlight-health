# JLIGHT Patient Journey and Intelligence-Layer Architecture

**Status:** Staging implementation specification aligned to the enterprise platform architecture  
**Applies to:** Hospital, Laboratory, and Bioinformatics workspaces  
**Connected boundary:** Clinical Trials has an independently permissioned participant domain and a governed recruitment link to Hospital  
**Production:** No production code, schema, data, configuration, or deployment changes are authorised by this document.

## 1. Product definition

JLIGHT is a software-based Health Intelligence Platform. It is not a laboratory instrument, analyser, diagnostic device, specimen-processing system, sequencing instrument, or replacement for an existing LIS, HIS, LIMS, CTMS, or laboratory equipment.

JLIGHT does not collect, prepare, test, analyse, process, or sequence physical specimens. It does not control laboratory instruments or generate primary analytical measurements.

JLIGHT works with information supplied through supported integrations, imports, and authorised manual entry. Depending on the site and available systems, inputs may include existing LIS/HIS/CTMS records, HL7/FHIR messages, structured CSV/TSV files, genomics/bioinformatics quality metrics and pipeline outputs, and manually entered operational events.

The platform analyses those records and events to identify missing steps, inconsistencies, delays, quality-control signals, patterns, risks, and governance gaps. It presents findings as traceable alerts or Decision Cards for review and action by authorised people. JLIGHT outputs are decision-support and operational-intelligence signals; they do not replace professional judgement or issue autonomous clinical diagnoses.

## 2. Workspace boundaries

Hospital, Laboratory, and Bioinformatics are independent operational workspaces. Each has its own functions, records, permissions, and data scope.

The Patient Journey is the controlled integration layer that links relevant, authorised records across those three workspaces for the same patient and care episode. It is not a fourth operational workspace, a shared unrestricted database, or a permission-granting mechanism.

Clinical Trials is a separate workspace with its own participant identity, consent, membership, permissions, study records, and data boundary. It is not part of the routine Hospital–Laboratory–Bioinformatics Patient Journey. Multi-pathway organisation membership must not create automatic links between patient records and trial participant records.

## 3. Patient Journey: the only cross-workspace bridge for routine care

The Patient Journey provides a longitudinal, traceable view of relevant events as a patient moves through care. It links references to source records; it does not copy entire workspace databases or give every workspace unrestricted access to the others.

Illustrative routine-care flow:

1. **Hospital:** an authorised hospital user or connected HIS supplies patient registration, encounter/admission, ward, clinical request, and relevant action/acknowledgement events.
2. **Laboratory:** an authorised laboratory user or connected LIS supplies order, specimen identification, collection/receipt/transport status where available, accession, QC status, result, validation, dispatch, and critical-result communication events.
3. **Bioinformatics:** where relevant and authorised, the bioinformatics workspace supplies references to sequencing/genomics jobs, QC metrics, pipeline status, and reports associated with the same patient episode or specimen reference.
4. **Patient Journey:** JLIGHT links the permitted references and timestamps into a coherent sequence, identifies missing or inconsistent transitions, and displays traceable alerts to users who are authorised to see the relevant information.

The sequence above is illustrative, not a mandatory workflow. Not every patient journey includes every workspace or every event. A site may operate one entitled workspace independently. Cross-workspace linkage is available only where the organisation has the relevant approved entitlements, the records can be reliably matched, and the user has permission to view each source record.

## 4. Linking and identity controls

Link records using governed identifiers and explicit matching rules, such as:
- verified patient identifier or approved pseudonymous patient key;
- encounter/admission identifier;
- laboratory order and accession identifiers;
- specimen identifier and parent/aliquot references where supplied;
- source-system record identifiers;
- timestamps, facility/site identifiers, and other approved context.

Do not link records solely because names, dates of birth, or other weak demographic attributes appear similar. Ambiguous matches must be flagged for authorised human reconciliation and must not silently merge patient records.

Every link must retain its source workspace, source-system identifier, event type, timestamp, matching basis, and audit history. Corrections and unlinking must be auditable. Access to a journey summary must not bypass the source workspace's authorisation rules: users may see only the data and source details for which they have explicit permission.

## 5. Intelligence-layer responsibilities

JLIGHT's intelligence layer evaluates available records and events; it does not perform the underlying clinical or laboratory operation.

Examples aligned with the executive proposal:

| Intelligence capability | Information JLIGHT evaluates | What JLIGHT does not do |
|---|---|---|
| Laboratory QC / Westgard signals | QC results and run-status data supplied by existing laboratory systems or authorised users | Does not run QC material or operate an analyser |
| Delta-check | Consecutive patient-result records and approved patient matching | Does not measure or generate the test result |
| Predictive QC drift | Historical QC measurements and time-series records | Does not adjust, calibrate, or stop an instrument |
| Specimen traceability / completeness | Order, collection, transport, receipt, accession, and status events where recorded | Does not collect, transport, prepare, or process specimens |
| Critical-result follow-up / Patient Journey | Result communication, acknowledgement, escalation, and documented clinical-action events | Does not make the clinical decision or treat the patient |
| Turnaround-time monitoring | Event timestamps and configured priority targets | Does not perform the laboratory test |
| HAI cluster signals | Approved patient, pathogen-result, ward, and time-window records | Does not diagnose an infection or replace infection-control review |
| NGS quality intelligence | Sequencing QC metrics and bioinformatics pipeline outputs supplied by the relevant tools | Does not sequence samples or imply that JLIGHT itself runs a sequencing instrument or pipeline |
| Clinical-trial oversight | Separately permissioned study, visit, consent, and AE/SAE records | Does not merge participant records into the routine patient journey |

An alert describes the observed signal, source evidence, relevant rule/threshold, severity, and recommended review or operational next step. It must preserve provenance and must not present an inferred signal as a confirmed diagnosis or proven root cause.

## 6. Data flow and system integration

JLIGHT may receive information from existing LIS, HIS, CTMS, LIMS, HL7/FHIR interfaces, structured file imports, or authorised manual entry, depending on what a validation site supports.

Integration adapters must:
- authenticate and validate the sending source;
- validate message/file structure and required identifiers;
- preserve source-system provenance and timestamps;
- handle duplicate, delayed, out-of-order, and corrected events safely;
- record ingestion and processing outcomes;
- reject or quarantine malformed or unauthorised data;
- avoid representing an unavailable integration as live or real-time.

Where no integration exists, the platform may use supported structured imports or authorised manual entry. The proposal's five-minute monitoring interval is an intended processing cadence only where the required data feed and deployment configuration support it; it must not be described as universal live connectivity.

JLIGHT must not send commands to instruments or laboratory equipment. Any future outbound integration must be separately specified, reviewed, and authorised; it must not imply instrument control or specimen processing.

## 7. Clinical Trials: participant timeline and hospital recruitment link

Clinical Trials has its own **Clinical Trial Participant Timeline**. It is not a filtered view of the routine Patient Journey. The timeline is built from trial-domain events associated with the internal trial participant record and study: referral hand-off where authorised, screening milestones, enrolment/status, protocol and consent milestones, scheduled/completed/missed visits, deviations, AE/SAE follow-up, retention signals and study close-out.

The Hospital-to-Clinical-Trial connection is intentional:
1. An authorised hospital/research user may identify a patient as a potential candidate under an approved recruitment process.
2. JLIGHT may compare permitted minimum-necessary attributes with protocol-approved recruitment criteria and prioritise candidates for human review. AI must not make final eligibility decisions, enrol people or contact them autonomously.
3. An authorised user creates a referral to a named study and authorised trial site. Referral provenance, purpose, source, actor, timestamp, status and disclosure scope are recorded.
4. The trial team receives only the minimum information permitted by the study's ethics approval, lawful basis, site governance and consent requirements.
5. Authorised research personnel perform screening. Informed consent is obtained and recorded according to the approved study process before enrolment and applicable study procedures.
6. If enrolled, the person receives a study-specific participant identifier. Trial events are associated with the internal participant record and study, not by searching or joining the routine patient registry.

The hospital patient identity and trial participant identity remain distinct. A secure, restricted relationship may connect them for the approved recruitment purpose, but there is no automatic identity merge, broad patient-record copy or unrestricted trial-team access to hospital records. A person may participate in multiple studies, each with its own participant identity.

The routine Patient Journey and Clinical Trial Participant Timeline require separate navigation, data loaders, APIs/RPC scopes, report generation, exports, search and access checks. The recruitment link is the only approved bridge for this purpose; it does not create pathway entitlement or member permission.

The current database has both a direct patient reference on the legacy trial participant model and a separate trial-participant model. Their constraints, RLS, payloads and usage must be reconciled before selecting one canonical linkage design. Do not silently rely on the direct foreign key or create a competing participant registry.
## 8. Organisation entitlements and user permissions

Organisation registration and pathway entitlement determine which operational workspaces the organisation may use. Member-level permissions determine which users may access which workspace operations and records. Patient Journey linkage is a data relationship and must never create an entitlement or grant access.

All API and database access must enforce:
- verified user identity and active organisation membership;
- active organisation entitlement for the requested workspace;
- active member permission for the requested operation;
- tenant, workspace, and record-level scope;
- separate Clinical Trials controls.

A user who can view a journey shell but lacks permission for a linked source record must not receive that record's protected contents through the journey API, report, export, search, notification, or Decision Card. Hospital-to-trial recruitment linkage is a separate purpose-specific permission and must disclose only approved minimum-necessary fields; it never grants full Hospital record access.

## 9. Required staging implementation and acceptance checks

1. Inventory existing patient, encounter, order, specimen, result, sequencing-job, report, and event identifiers before changing schemas.
2. Map current workspace tables and APIs to the source-record references needed by Patient Journey.
3. Define a canonical journey-event contract with source provenance, tenant scope, event time, ingestion time, record references, and correction history.
4. Implement linking as references to authorised source records; do not duplicate whole workspace datasets.
5. Enforce deterministic matching and a human-review path for ambiguous matches.
6. Enforce permission checks on every journey read, report, export, search result, notification, and Decision Card.
7. Test partial deployments: Laboratory-only, Hospital-only, and combinations of approved workspaces.
8. Test that a user cannot access a linked source record without source-workspace permission.
9. Test that specimen lifecycle events are represented as supplied records only; no code path may claim JLIGHT physically processes or analyses a specimen.
10. Test that Clinical Trial Participant Timeline remains independent from routine Patient Journey, while the separately authorised hospital-to-trial recruitment referral and linkage flow works with minimum-necessary disclosure.
11. Test referral states, protocol-specific participant IDs, consent milestones, multiple studies per patient, link correction/revocation, ambiguous identity matching and audit history using synthetic staging data. Real patient data requires the applicable ethics, legal, site, privacy, and data-governance approvals.
12. Record actual integration availability and processing cadence accurately; do not claim live HL7/FHIR or instrument connectivity unless implemented and verified.

## 10. Explicit non-goals

- No specimen collection, preparation, testing, analysis, processing, or sequencing by JLIGHT.
- No instrument/analyser control, calibration, or result generation.
- No replacement of LIS, HIS, LIMS, CTMS, or specialist bioinformatics pipelines.
- No autonomous diagnosis or autonomous clinical action.
- No unrestricted sharing of patient data between workspaces.
- No automatic patient/participant identity merge or unrestricted Clinical Trials access to routine patient journeys. A governed, purpose-limited recruitment link is permitted.
- No production database migration, production data mutation, merge to `main`, or production deployment as part of this specification.

## 11. Relationship to the Executive Proposal

This specification preserves the proposal's positioning of JLIGHT as an AI-enabled Health Intelligence Platform. Existing systems and data feeds supply the JLIGHT Intelligence Layer, which evaluates operational and scientific records across four workspaces and produces traceable Decision Cards. The Patient Journey and Clinical Trials recruitment connection are distinct but governed pathways. See docs/architecture/jlight-enterprise-platform-architecture.md for the authoritative organisation/workspace, recruitment, AI, scale and governance architecture. The engines analyse supplied records and metrics; they do not require JLIGHT to be a physical laboratory instrument.

The implementation must make this distinction explicit in product copy, diagrams, APIs, data contracts, demonstrations, validation protocols, and funding materials.
