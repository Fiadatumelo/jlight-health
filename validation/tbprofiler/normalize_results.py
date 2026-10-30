#!/usr/bin/env python3
"""Normalize external TBProfiler JSON results into JLIGHT's bioRuns CSV schema.

This script does not call TBProfiler, analyse reads, or make clinical decisions.
It only maps already-generated, versioned TBProfiler result files to the existing
JLIGHT Bioinformatics source-import contract.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COLUMNS = [
    "analysisType",
    "outputType",
    "status",
    "qualityStatus",
    "summary",
    "createdAt",
    "sourceSystem",
    "sourceRecordId",
]


def first_value(obj: Any, names: tuple[str, ...]) -> Any:
    if not isinstance(obj, dict):
        return None
    for name in names:
        value = obj.get(name)
        if value not in (None, "", []):
            return value
    return None


def number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = first_value(value, ("value", "median", "mean", "percent"))
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "")
            if not value:
                return None
        return float(value)
    except (TypeError, ValueError):
        return None


def jsonable_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def compact_variant(variant: Any) -> dict[str, Any]:
    if not isinstance(variant, dict):
        return {"sourceValue": variant}
    drugs = variant.get("drugs") or []
    annotations = variant.get("annotations") or []
    return {
        "gene": first_value(variant, ("gene", "locus_tag")),
        "position": first_value(variant, ("genome_pos", "position", "pos")),
        "mutation": first_value(variant, ("mutation", "nucleotide_change", "protein_change")),
        "type": first_value(variant, ("type", "variant_type", "consequence")),
        "frequency": number(first_value(variant, ("freq", "frequency", "allele_frequency"))),
        "drugs": drugs,
        "annotations": annotations,
    }


def normalize_one(path: Path, dataset_accession: str, tool_version: str, db_version: str) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as handle:
        result = json.load(handle)
    if not isinstance(result, dict):
        raise ValueError(f"{path.name}: TBProfiler result must be a JSON object")

    run_id = first_value(result, ("id", "sample", "sample_id", "run_id"))
    if not run_id:
        raise ValueError(f"{path.name}: no run/sample identifier in TBProfiler output")

    pipeline = result.get("pipeline") if isinstance(result.get("pipeline"), dict) else {}
    qc = result.get("qc") if isinstance(result.get("qc"), dict) else {}
    lineage = first_value(result, ("lineage", "strain", "sublineage"))
    drtype = first_value(result, ("drtype", "drug_resistance", "drug-resistance"))
    median_coverage = number(first_value(qc, (
        "median_coverage", "median_depth", "median_depth_of_coverage",
        "coverage_median", "coverage",
    )))
    mapping_rate = number(first_value(qc, (
        "percentage_reads_mapped", "percent_reads_mapped", "pct_mapped",
        "mapping_rate", "mapped_percent",
    )))
    read_count = number(first_value(qc, (
        "num_reads", "number_of_reads", "total_reads", "reads",
    )))

    dr_variants = result.get("dr_variants") or []
    other_variants = result.get("other_variants") or []
    if not isinstance(dr_variants, list):
        raise ValueError(f"{path.name}: dr_variants must be an array")
    if not isinstance(other_variants, list):
        raise ValueError(f"{path.name}: other_variants must be an array")

    warnings: list[str] = []
    if median_coverage is not None and median_coverage < 30:
        warnings.append(
            f"Median coverage {median_coverage:g}x is below the 30x review threshold; "
            "some mutations may not be detected."
        )
        quality_status = "review_required_low_coverage"
    elif median_coverage is None:
        warnings.append("Median coverage was not present in the imported QC fields.")
        quality_status = "qc_not_reported"
    else:
        quality_status = "qc_reported_review_required"

    pipeline_version = (
        first_value(pipeline, ("version", "pipeline_version"))
        or first_value(result, ("pipeline_version", "version"))
        or tool_version
    )
    database_version = (
        first_value(pipeline, ("db_version", "database_version", "tbdb_version"))
        or first_value(result, ("db_version", "database_version"))
        or db_version
    )
    source_date = first_value(result, ("date", "created_at", "timestamp"))

    summary = {
        "datasetAccession": dataset_accession,
        "runAccession": str(run_id),
        "pipeline": "TBProfiler",
        "pipelineVersion": jsonable_text(pipeline_version),
        "databaseVersion": jsonable_text(database_version),
        "lineage": jsonable_text(lineage),
        "drugResistanceType": jsonable_text(drtype),
        "medianCoverage": median_coverage,
        "mappingRatePercent": mapping_rate,
        "readCount": read_count,
        "resistanceVariantCount": len(dr_variants),
        "resistanceVariants": [compact_variant(item) for item in dr_variants],
        "otherVariantCount": len(other_variants),
        "qcWarnings": warnings,
        "sourceResultFile": path.name,
        "sourceDate": jsonable_text(source_date),
        "interpretationLimit": (
            "External genotypic prediction only; not phenotypic DST or a clinical diagnosis."
        ),
    }

    return {
        "analysisType": "Mycobacterium tuberculosis WGS",
        "outputType": "TBProfiler JSON summary",
        "status": "completed",
        "qualityStatus": quality_status,
        "summary": json.dumps(summary, ensure_ascii=False, sort_keys=True),
        "createdAt": jsonable_text(source_date) or datetime.now(timezone.utc).isoformat(),
        "sourceSystem": "TBProfiler",
        "sourceRecordId": str(run_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--dataset-accession", required=True)
    parser.add_argument("--tool-version", default=os.environ.get("TBPROFILER_VERSION", "not_reported"))
    parser.add_argument("--db-version", default=os.environ.get("TBPROFILER_DB_VERSION", "not_reported"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    paths = sorted(args.results_dir.glob("*.results.json"))
    if not paths:
        raise SystemExit(f"No *.results.json files found in {args.results_dir}")

    rows = [
        normalize_one(path, args.dataset_accession, args.tool_version, args.db_version)
        for path in paths
    ]
    ids = [row["sourceRecordId"] for row in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate TBProfiler sourceRecordId values found")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "datasetAccession": args.dataset_accession,
        "pipeline": "TBProfiler",
        "pipelineVersion": args.tool_version,
        "databaseVersion": args.db_version,
        "samples": [
            {
                "sourceRecordId": row["sourceRecordId"],
                "qualityStatus": row["qualityStatus"],
                "summary": json.loads(row["summary"]),
            }
            for row in rows
        ],
        "jlightImportFile": str(args.output),
    }
    report_path = args.output.with_name("tbprofiler_validation_report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
