# Public South African TBProfiler validation

This is a **separate validation environment**, not a JLIGHT runtime dependency. JLIGHT does not process raw FASTA/FASTQ reads. It receives authorised, externally generated bioinformatics results and preserves their provenance for review.

## Dataset and subset

- ENA study: `PRJEB57919`
- Organism: *Mycobacterium tuberculosis*
- Public paired-end Illumina runs:
  - `ERR10610053` — paired FASTQ files, approximately 396 MB total
  - `ERR10610083` — paired FASTQ files, approximately 151 MB total
- The subset deliberately includes one higher-coverage and one lower-coverage run to exercise QC reporting. The public TB-Profiler results page for `ERR10610083` warns that median coverage is below 30x; low coverage can cause mutations to be missed.
- No patient identifiers, clinical narratives, or raw FASTQ files are imported into JLIGHT.

## Reproducible environment

The environment pins TBProfiler 6.7.0 from Bioconda. The workflow updates the TBProfiler mutation database, records the package and database update metadata, downloads only the two listed public runs, executes the external pipeline, validates its JSON output, and creates a JLIGHT-compatible CSV.

TBProfiler and its mutation database are versioned independently. The workflow records both wherever the tool exposes them. If a database revision cannot be recovered from the tool output, it is explicitly reported as unavailable rather than invented.

## JLIGHT import format

The normalizer writes `jlight_bioruns_import.csv` using the existing JLIGHT Bioinformatics `bioRuns` source-import fields:

`analysisType,outputType,status,qualityStatus,summary,createdAt,sourceSystem,sourceRecordId`

The `summary` field contains a compact JSON evidence summary with the ENA dataset/run accession, TBProfiler version, database version, lineage, resistance profile, QC values, variant counts and warnings. The importer does not treat a genotype prediction as a clinical diagnosis.

## Interpretation limits

- These are public, previously generated bacterial sequencing runs. They are not patient records and are not linked to a JLIGHT patient.
- TBProfiler output is a genotypic prediction, not phenotypic drug-susceptibility testing.
- Low coverage must be surfaced as a limitation; a low-coverage "sensitive" call must not be presented as definitive.
- This is an integration and data-quality validation, not clinical performance validation or regulatory clearance.
- TBProfiler's web service is explicitly Research Use Only and disclaims clinical diagnosis/patient-management use. See the official project and tool documentation.

## Run locally

Create the pinned environment, download the two paired FASTQ runs from ENA, run `tb-profiler profile` on each, then:

```bash
python validation/tbprofiler/normalize_results.py \
  --results-dir work/results \
  --dataset-accession PRJEB57919 \
  --tool-version 6.7.0 \
  --db-version "recorded-by-workflow" \
  --output work/jlight_bioruns_import.csv
```

The GitHub Actions workflow performs this validation in an isolated runner and publishes the normalised result and provenance report as artifacts.
