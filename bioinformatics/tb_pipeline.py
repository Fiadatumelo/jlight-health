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
import os
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


def validate_private_path(path: Path, private_root: Path, repo_root: Path) -> None:
    """Fail closed unless all sequence inputs and outputs stay outside the web/repository tree."""
    resolved = path.resolve()
    root = private_root.resolve()
    repository = repo_root.resolve()
    if root == repository or root.is_relative_to(repository) or repository.is_relative_to(root):
        raise ValueError("JLIGHT_PRIVATE_DATA_ROOT must be an isolated private directory outside the repository and web root")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Sequence inputs and outputs must be located inside JLIGHT_PRIVATE_DATA_ROOT") from exc

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

def _fastq_records(path: Path):
    """Yield normalised read identifiers after structural validation."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="ascii", errors="strict") as handle:
        while True:
            header = handle.readline()
            if not header:
                return
            sequence = handle.readline()
            plus = handle.readline()
            quality = handle.readline()
            if not quality:
                raise ValueError(f"Truncated FASTQ record at end of file: {path.name}")
            token = header[1:].strip().split()[0]
            # Illumina identifiers can encode mate as /1 or /2, or as a
            # second whitespace-delimited token (1:N:... / 2:N:...).
            token = token.removesuffix("/1").removesuffix("/2")
            yield token


def validate_paired_fastq(r1: Path, r2: Path) -> int:
    """Validate pair counts and read-name synchronization without loading reads."""
    left = _fastq_records(r1)
    right = _fastq_records(r2)
    count = 0
    while True:
        a = next(left, None)
        b = next(right, None)
        if a is None and b is None:
            return count
        if a is None or b is None:
            raise ValueError("Paired FASTQ files contain different record counts")
        if a != b:
            raise ValueError(f"Paired FASTQ read names are out of sync at record {count + 1}")
        count += 1


def version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return (result.stdout or result.stderr).strip().splitlines()[0][:300]
    except Exception as exc:
        raise RuntimeError(f"Required tool unavailable: {' '.join(command)} ({exc})") from exc

def run_stage(name: str, command: list[str], out: Path, log: Path) -> dict:
    """Run one tool and return provenance even when it exits unsuccessfully."""
    try:
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(
                command, cwd=out, stdout=stream, stderr=subprocess.STDOUT,
                text=True, timeout=None, check=False,
            )
        stage = {
            "name": name,
            "command": command,
            "exit_code": result.returncode,
            "log": str(log),
            "status": "completed" if result.returncode == 0 else "failed",
        }
    except Exception as exc:
        stage = {
            "name": name, "command": command, "exit_code": None,
            "log": str(log), "status": "failed", "error": str(exc)[:1000],
        }
        raise StageFailure(f"Stage {name} could not complete: {exc}", stage) from exc
    if result.returncode:
        raise StageFailure(
            f"Stage {name} failed with exit code {result.returncode}; inspect {log}",
            stage,
        )
    return stage


class StageFailure(RuntimeError):
    """A failed stage that carries its provenance for the run manifest."""
    def __init__(self, message: str, stage: dict):
        super().__init__(message)
        self.stage = stage

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--r1", required=True, type=Path)
    parser.add_argument("--r2", type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--single-end", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--db", default="who_v2+", help="Installed TBProfiler database identifier")
    parser.add_argument("--db-version", default=os.environ.get("TBPROFILER_DB_COMMIT"), help="Exact TBProfiler mutation database commit loaded in this environment")
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
    private_root_raw = os.environ.get("JLIGHT_PRIVATE_DATA_ROOT")
    if not private_root_raw:
        parser.error("JLIGHT_PRIVATE_DATA_ROOT must point to an isolated private storage directory")
    private_root = Path(private_root_raw).resolve()
    if not private_root.is_dir():
        parser.error("JLIGHT_PRIVATE_DATA_ROOT must exist and be a directory")
    repository_root = Path(__file__).resolve().parents[1]
    try:
        for protected_path in [args.r1, args.outdir] + ([args.r2] if args.r2 else []):
            validate_private_path(protected_path, private_root, repository_root)
    except ValueError as exc:
        parser.error(str(exc))
    os.umask(0o077)
    args.outdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.outdir.chmod(0o700)
    logs = args.outdir / "logs"
    qc = args.outdir / "qc"
    results = args.outdir / "results"
    for directory in (logs, qc, results):
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    reads = [args.r1] + ([] if args.single_end else [args.r2])
    try:
        for read in reads:
            validate_fastq(read)
        paired_record_count = None
        if not args.single_end:
            paired_record_count = validate_paired_fastq(args.r1, args.r2)
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
            "database_version": args.db_version or "UNPINNED: exact mutation database commit was not supplied",
            "threads": args.threads,
            "paired_record_count": paired_record_count,
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
        if isinstance(exc, StageFailure):
            manifest.setdefault("stages", []).append(exc.stage)
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
