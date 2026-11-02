# Patient-journey reconciliation and discrepancy review

This engine reconciles records only after an authorised workflow has assigned the same verified JLIGHT patient ID. It does not link people using names, dates of birth, or fuzzy similarity.

## Required source evidence
Hospital, Laboratory and Bioinformatics records should carry stable source record identifiers and, where applicable, encounter, order, specimen and accession identifiers. A missing identifier is an incomplete-evidence flag, not proof of an incorrect patient match.

## Findings
- Missing journey section: one or more of Hospital, Laboratory or Bioinformatics is absent.
- Cross-system identifier conflict: two source systems provide different explicit values for the same correlation field.
- Missing source linkage reference: a Laboratory or Bioinformatics record has no order, specimen or accession reference.
- Duplicate source record: repeated source key is counted and not silently added twice.

Findings are review flags. JLIGHT preserves original source records and provenance and must not silently correct identifiers or make clinical decisions.

## Isolation
Clinical Trials records are excluded from the patient journey. Unlinked records remain unlinked. Only verified JLIGHT patient links are grouped.

## Validation boundary
Tests use synthetic fixtures. A passing synthetic test demonstrates the reconciliation rules, not a live hospital/LIS/FHIR/CTMS integration or a real-patient journey. Production validation requires authenticated, tenant-scoped source feeds and authorised partner test data.
