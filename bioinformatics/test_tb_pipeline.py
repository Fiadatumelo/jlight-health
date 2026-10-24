import gzip
import importlib.util
import tempfile
import unittest
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

    def test_rejects_wrong_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reads.bam"
            path.write_bytes(b"data")
            with self.assertRaisesRegex(ValueError, "Unsupported FASTQ"):
                pipeline.validate_fastq(path)

if __name__ == "__main__":
    unittest.main(verbosity=2)
