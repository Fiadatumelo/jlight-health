# JLIGHT interoperability and resilience foundation

## Objective
JLIGHT is an interoperability and health-intelligence layer that works alongside existing systems and supports defined standalone workflows. It must not require wholesale replacement of hospital, laboratory, pharmacy, radiology, bioinformatics, or clinical-trial systems.

## Canonical record contract
Each ingested record preserves:
- source system and source record ID (the stable source key is `source_system::source_record_id`);
- domain and record type;
- source update timestamp with timezone;
- the original supplied source values;
- explicit JLIGHT patient-link ID only when established through an approved identity/crosswalk process;
- ingestion timestamp, freshness state, and provenance.

JLIGHT does not infer identity from names, dates of birth, addresses, or approximate similarity. Unmatched records remain unlinked for review. The original source remains authoritative.

## Patient journey boundaries
Hospital, Laboratory, and Bioinformatics records may appear in the shared patient journey only when they have a verified JLIGHT patient link. Clinical Trials records are kept in a separate participant/protocol workflow and never enter the general patient journey through this foundation.

## Connection health and stale data
Connection state and data freshness are separate. A live connection does not make old data current. A source is marked stale when its last successful synchronisation exceeds the configured threshold. An unavailable source is never reported as currently usable, even if a recent successful sync exists. The UI should display source status and last successful sync time.

## Synchronisation and conflict safety
- Exact repeats are no-ops.
- A changed payload with the same source key and source timestamp is held as a conflict.
- A newer source version is only a version candidate; the adapter must preserve history and apply source-specific reconciliation policy before promotion.
- Never silently overwrite source values or resolve clinical conflicts without authorised rules and review.
- Offline queue persistence, encryption, multi-device sync and production recovery still require environment-specific implementation and tests; this module defines the validation rules, not proof of deployed offline capability.

## Connector strategy
Implement and validate one connector at a time:
1. file-based synthetic fixture for the canonical contract;
2. synthetic HIS-style source;
3. synthetic LIS/LIMS-style source;
4. synthetic bioinformatics output;
5. separate synthetic CTMS participant workflow;
6. then an authorised test integration using the actual vendor interface (FHIR, HL7 v2, API or approved export).

The included fixtures and tests are synthetic. They demonstrate data-contract and safety behaviour only; they do not establish clinical validity, a production connector, or a real-world hospital deployment.
