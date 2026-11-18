# JLIGHT Synthea FHIR R4 validation datasets

This directory tracks the identity and integrity metadata for the two owner-supplied synthetic Synthea FHIR R4 archives used by JLIGHT interoperability validation.

## Required archives

| Archive | Size (bytes) | SHA-256 |
|---|---:|---|
| `synthea_sample_data_fhir_latest.zip` | 24052464 | `66141b772671452f590f9b7bb999eb201f1f16beb94a84ab0885ed723b36b315` |
| `synthea_sample_data_fhir_r4_nov2021(1).zip` | 94887125 | `6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778` |

Both source archives were checked locally with ZIP integrity testing. These checks do not constitute FHIR validation; the repository validator must still be run against both complete archives.

## Handling

- Keep the original ZIP files outside the normal source tree and do not add them to Git history.
- Publish the ZIPs as binary GitHub Release assets (recommended) or place them in an approved private dataset store.
- The release or asset URLs should be recorded here after the files are uploaded.
- Verify the SHA-256 values above after downloading the assets into the OpenCode workspace.
- Run `jlight-backend/scripts/validate_synthea_archive.py` against each complete archive.
- Keep validation read-only. Do not automatically import either dataset into staging or production.
- Do not include patient-like synthetic fixture content in production.

## Validation status

Pending full-archive validation. Prior inventory counts are historical context only and must not be reported as current validator results until the two exact files have been processed.

## Why this branch exists

This is a data-support branch only. It is not a production or staging release branch and must not trigger application deployment.
