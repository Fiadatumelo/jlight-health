#!/usr/bin/env python3
"""Reproducible research-only MTB FASTQ pipeline wrapper.

Requires FastQC, MultiQC and tb-profiler installed in the execution environment.
This script never claims clinical validation. It records provenance and refuses
to mark a run successful if any required stage fails.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def validate_fastq(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"FASTQ is missing or empty: {path.name}")
    if path.suffix == ".gz":
        opener = gzip.open
    elif path.suffix in {".fastq", ".fq"}:
        opener = open
    else:
        raise ValueError(f"Unsupported FASTQ extension: {path.name}")
    # Consume the entire stream to detect truncated gzip files, and validate
    # FASTQ record structure without loading the complete file into memory.
    try:
        with opener(path, "rt", encoding="ascii", errors="strict") as handle:
            line_no, record = 0, []
            for line in handle:
                line_no += 1
                record.append(line.rstrip("\r\n"))
                if len(record) == 4:
                    header, sequence, plus, quality = record
                    if not header.startswith("@") or not plus.startswith("+"):
                        raise ValueError(f"Invalid FASTQ record structure at line {line_no - 3}: {path.name}")
                    if not sequence or len(sequence) != len(quality):
                        raise ValueError(f"Invalid FASTQ sequence/quality length at line {line_no - 2}: {path.name}")
                    record = []
            if record:
                raise ValueError(f"Truncated FASTQ record at end of file: {path.name}")
            if line_no == 0:
                raise ValueError(f"FASTQ is empty: {path.name}")
    except (OSError, EOFError, UnicodeError) as exc:
        raise ValueError(f"Invalid or truncated FASTQ file: {path.name}") from exc

def version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return (result.stdout or result.stderr).strip().splitlines()[0][:300]
    except Exception as exc:
        raise RuntimeError(f"Required tool unavailable: {' '.join(command)} ({exc})") from exc

def run_stage(name: str, command: list[str], out: Path, log: Path) -> dict:
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=out, stdout=stream, stderr=subprocess.STDOUT, text=True)
    stage = {"name": name, "command": command, "exit_code": result.returncode, "log": str(log)}
    if result.returncode:
        raise RuntimeError(f"Stage {name} failed with exit code {result.returncode}; inspect {log}")
    return stage

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--r1", required=True, type=Path)
    parser.add_argument("--r2", type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--single-end", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--db", default="who_v2+", help="Installed TBProfiler database identifier")
    args = parser.parse_args()
    if not args.sample_id.strip() or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in args.sample_id):
        parser.error("sample-id may contain only letters, digits, dot, underscore and hyphen")
    if args.single_end == bool(args.r2):
        parser.error("Provide --r2 for paired-end data, or --single-end for single-end data")
    if args.threads < 1 or args.threads > 64:
        parser.error("--threads must be between 1 and 64")
    if not args.db.strip() or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-" for c in args.db):
        parser.error("--db must be an installed database identifier using letters, digits, dot, underscore, plus or hyphen")
    args.r1 = args.r1.resolve()
    if args.r2:
        args.r2 = args.r2.resolve()
    args.outdir = args.outdir.resolve()
    args.outdir.mkdir(parents=True, exist_ok=True)
    logs = args.outdir / "logs"
    qc = args.outdir / "qc"
    results = args.outdir / "results"
    for directory in (logs, qc, results):
        directory.mkdir(exist_ok=True)
    reads = [args.r1] + ([] if args.single_end else [args.r2])
    try:
        for read in reads:
            validate_fastq(read)
        tool_versions = {
            "fastqc": version(["fastqc", "--version"]),
            "multiqc": version(["multiqc", "--version"]),
            "tb-profiler": version(["tb-profiler", "--version"]),
        }
        manifest = {
            "schema_version": "1.0",
            "sample_id": args.sample_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "workflow": "jlight-mtb-research",
            "platform": "illumina",
            "database": args.db,
            "database_version": "not independently resolved by this wrapper; pin the installed TBProfiler database in the worker image before release",
            "threads": args.threads,
            "intended_use": "research_and_technical_review_only",
            "status": "running",
            "input_files": [{"name": p.name, "size_bytes": p.stat().st_size, "sha256": sha256(p)} for p in reads],
            "tools": tool_versions,
            "stages": [],
            "limitations": [
                "Not clinically validated by this wrapper.",
                "Genotypic resistance predictions are not phenotypic susceptibility testing.",
                "QC failure or pipeline failure must not be interpreted as a negative result.",
            ],
        }
        (args.outdir / "run-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for read in reads:
            manifest["stages"].append(run_stage(
                "fastqc:" + read.name,
                ["fastqc", "--outdir", str(qc), str(read)],
                args.outdir, logs / ("fastqc-" + read.name.replace("/", "_") + ".log")))
        manifest["stages"].append(run_stage(
            "multiqc", ["multiqc", str(qc), "--outdir", str(qc)],
            args.outdir, logs / "multiqc.log"))
        cmd = ["tb-profiler", "profile", "-1", str(args.r1), "-t", str(args.threads), "--db", args.db, "--prefix", args.sample_id]
        if not args.single_end:
            cmd.extend(["-2", str(args.r2)])
        manifest["stages"].append(run_stage("tb-profiler", cmd, args.outdir, logs / "tb-profiler.log"))
        manifest["status"] = "completed_pending_expert_review"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        (args.outdir / "run-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps({"status": manifest["status"], "manifest": str(args.outdir / "run-manifest.json"), "results": str(results)}))
        return 0
    except Exception as exc:
        manifest_path = args.outdir / "run-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
            "schema_version": "1.0", "sample_id": args.sample_id, "workflow": "jlight-mtb-research",
            "intended_use": "research_and_technical_review_only", "input_files": [],
            "tools": {}, "stages": [], "limitations": []
        }
        manifest.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        manifest.setdefault("sample_id", args.sample_id)
        manifest.setdefault("input_files", [])
        manifest.setdefault("tools", {})
        manifest.setdefault("stages", [])
        manifest.setdefault("limitations", ["Not clinically validated by this wrapper.", "Pipeline failure must not be interpreted as a negative result."])
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps({"status": "failed", "error": str(exc), "manifest": str(manifest_path)}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
