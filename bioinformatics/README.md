# JLIGHT Bioinformatics Research Pipeline

This directory contains the first executable pathogen workflow wrapper: MTB FASTQ quality control and TBProfiler-based genotypic profiling. It is a research/technical pipeline, not a validated diagnostic service.

## Requirements

- Python 3.10+
- FastQC
- MultiQC
- TBProfiler (install from its maintained official distribution and configure its reference/mutation database before use)
- Sufficient isolated compute, scratch storage and private data storage for the dataset size

The wrapper deliberately does not download tools, containers, reference databases or sequence data automatically. Deployment must pin the exact software/container digests and TBProfiler database version in the approved environment. It records tool versions, the selected database identifier, checksums, stage commands, logs and run status in a manifest. The wrapper does not independently resolve the exact TBProfiler database release; the worker image must pin and document that database version before any benchmark or production run.

## Example

```bash
python bioinformatics/tb_pipeline.py \
  --sample-id SA-TB-RESEARCH-001 \
  --r1 /private-input/sample_R1.fastq.gz \
  --r2 /private-input/sample_R2.fastq.gz \
  --outdir /private-runs/SA-TB-RESEARCH-001
```

For single-end reads, replace `--r2 ...` with `--single-end`. The sample identifier is restricted to safe filename characters. Inputs must be supplied by an authorised user, and must be stored outside the public web root.

## Outputs

- `run-manifest.json`: status, input checksums, tool information, stage exit codes, and explicit limitations.
- `qc/`: FastQC outputs and MultiQC report.
- `results/`: TBProfiler outputs.
- `logs/`: per-stage logs.

A successful execution is marked `completed_pending_expert_review`, not clinically approved. A failure writes a `failed` manifest and exits non-zero. Do not interpret failed or low-quality runs as negative findings.

## Before production

This wrapper is not yet wired to the JLIGHT UI, a queue, a private object store, or a hardened worker. Production use requires an isolated worker, tenant-scoped permissions, short-lived signed file access, resource limits, cancellation/retry, retention/deletion policy, audit trails, pinned container/database digests, benchmark comparison and laboratory/ethics/regulatory review where applicable. Never run real patient sequence data on a developer workstation or in general-purpose AI prompts.

## Tests

Run input-validation tests with:

```bash
python -m unittest bioinformatics/test_tb_pipeline.py -v
```
