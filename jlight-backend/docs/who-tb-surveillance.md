# WHO TB aggregate surveillance integration

## Purpose
The WHO CSV bundle is a population-surveillance evidence source for JLIGHT TB Intelligence. It supports country-level burden, incidence/mortality trends, notifications, treatment outcomes, laboratory capacity, age/sex stratification and drug-resistance surveillance. It is not patient-level data.

## Supported inputs
The loader expects one CSV for each of these WHO extracts: country burden, MDR/RR-TB burden estimates, notifications, treatment outcomes, drug-resistance surveillance, laboratory capacity, burden by age/sex and outcomes by age/sex. The supplied data dictionary remains the field-definition authority. The loader validates required columns, scopes rows by ISO3 (default ZAF), preserves missing values and lower/upper uncertainty bounds, and records source filename, row count and year coverage.

## Use
From `jlight-backend`:

```python
from engine.who_tb_surveillance import load_who_tb_bundle, build_tb_intelligence_cards

bundle = load_who_tb_bundle("/path/to/who/csvs", iso3="ZAF")
cards = build_tb_intelligence_cards(bundle)
```

## Governance
- WHO country aggregates must be stored and displayed as aggregate surveillance evidence, not patient records.
- Never create a JLIGHT patient, link an accession to a patient, or route an aggregate into a patient journey from these files.
- Never interpret missing values as zero.
- Keep estimated incidence, notified cases, laboratory-confirmed cases and treatment cohorts as distinct measures.
- Display estimate intervals wherever supplied.
- Drug-resistance percentages and case estimates are population-level surveillance signals, not individual DST calls or treatment recommendations.
- Clinical Trials remains isolated. These files must not populate participant records.
- The loader is a backend data-engine component; it does not by itself establish a live WHO API feed, persistent tenant-scoped database storage, or a production dashboard route.

## Validation boundary
The loader is suitable for reproducible aggregate-data ingestion and analytical QA. Patient matching, clinical workflow, and individual resistance-call validation require separate authorised patient-level datasets and their own privacy/security controls.
