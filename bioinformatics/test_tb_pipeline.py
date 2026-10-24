import gzip
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

MODULE = Path(__file__).with_name("tb_pipeline.py")
spec = importlib.util.spec_from_file_location("tb_pipeline", MODULE)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

class FastqValidationTests(unittest.TestCase):
    def test_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.fastq"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                pipeline.validate_fastq(path)

    def test_rejects_invalid_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.fastq.gz"
            path.write_bytes(b"not gzip")
            with self.assertRaisesRegex(ValueError, "Invalid or truncated FASTQ"):
                pipeline.validate_fastq(path)

    def test_accepts_nonempty_gzip_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reads.fastq.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(b"@r1\nACGT\n+\n!!!!\n")
            pipeline.validate_fastq(path)

    def test_rejects_invalid_fastq_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.fastq"
            path.write_text("not-a-header\nACGT\n+\n!!!!\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "record structure"):
                pipeline.validate_fastq(path)

    def test_rejects_truncated_fastq_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.fastq"
            path.write_text("@r1\nACGT\n+\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "sequence/quality length|Truncated FASTQ"):
                pipeline.validate_fastq(path)


    def test_mocked_tb_run_writes_manifest_and_records_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            scripts = {
                "fastqc": """#!/usr/bin/env python3
import pathlib, sys
if "--version" in sys.argv:
 print("FastQC v0.test"); raise SystemExit(0)
out = pathlib.Path(sys.argv[sys.argv.index("--outdir")+1]); out.mkdir(parents=True, exist_ok=True)
(out / (pathlib.Path(sys.argv[-1]).name + ".html")).write_text("mock qc")
""",
                "multiqc": """#!/usr/bin/env python3
import pathlib, sys
if "--version" in sys.argv:
 print("multiqc, version 0.test"); raise SystemExit(0)
out = pathlib.Path(sys.argv[sys.argv.index("--outdir")+1]); out.mkdir(parents=True, exist_ok=True)
(out / "multiqc_report.html").write_text("mock summary")
""",
                "tb-profiler": """#!/usr/bin/env python3
import pathlib, sys
if "--version" in sys.argv:
 print("tb-profiler version 0.test"); raise SystemExit(0)
if len(sys.argv) > 1 and sys.argv[1] == "profile":
 prefix = sys.argv[sys.argv.index("--prefix")+1]
 out = pathlib.Path("results"); out.mkdir(parents=True, exist_ok=True)
 (out / (prefix + ".results.json")).write_text('{"mock": true}')
""",
            }
            for name, source in scripts.items():
                path = bin_dir / name
                path.write_text(source, encoding="utf-8")
                path.chmod(0o755)
            r1 = root / "sample_R1.fastq.gz"
            r2 = root / "sample_R2.fastq.gz"
            for path in (r1, r2):
                with gzip.open(path, "wb") as handle:
                    handle.write(b"@r1\\nACGT\\n+\\n!!!!\\n")
            outdir = root / "run"
            with patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}):
                with patch("sys.argv", ["tb_pipeline.py", "--sample-id", "SYNTHETIC-TB-01", "--r1", str(r1), "--r2", str(r2), "--outdir", str(outdir), "--threads", "2"]):
                    self.assertEqual(pipeline.main(), 0)
            manifest = __import__("json").loads((outdir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed_pending_expert_review")
            self.assertEqual(manifest["database"], "who_v2+")
            self.assertEqual(manifest["threads"], 2)
            self.assertEqual(manifest["tools"]["tb-profiler"], "tb-profiler version 0.test")
            self.assertEqual(len(manifest["input_files"]), 2)
            self.assertEqual(len(manifest["stages"]), 4)
            self.assertTrue((outdir / "qc" / "multiqc_report.html").exists())

    def test_rejects_wrong_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reads.bam"
            path.write_bytes(b"data")
            with self.assertRaisesRegex(ValueError, "Unsupported FASTQ"):
                pipeline.validate_fastq(path)

if __name__ == "__main__":
    unittest.main(verbosity=2)
