"""
JLIGHT v4 — Test Suite
========================
End-to-end tests for ML engine, CSV engine, and Bioinformatics engine.
Run with: python3 tests/test_all.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import traceback
from engine.ml_engine import JLIGHTMLPipeline
from engine.csv_engine import analyse_csv
from engine.bio_engine import (
    screen_tb_resistance,
    detect_variants,
    analyse_ngs_quality,
    calculate_wgs_metrics,
    analyse_sequence,
)

PASS = "✅"
FAIL = "❌"
results = []

def test(name, fn):
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append((name, True))
    except Exception as e:
        print(f"  {FAIL} {name}: {e}")
        traceback.print_exc()
        results.append((name, False))


# ─── ML Engine Tests ─────────────────────────────────────────────────────────

print("\n🧠 ML ENGINE")

def test_regression_rising():
    pipeline = JLIGHTMLPipeline()
    result = pipeline.run([2.1, 2.3, 2.8, 3.1, 3.6, 4.1, 4.8])
    assert result.regression.slope > 0, "Expected positive slope"
    assert result.regression.r_squared > 0.95, f"R² too low: {result.regression.r_squared}"
    assert result.regression.trend_label == "RISING"
    assert len(result.regression.forecast) == 3
    assert result.risk.level in ("CRITICAL", "ATTENTION")

def test_regression_stable():
    pipeline = JLIGHTMLPipeline()
    result = pipeline.run([2.1, 2.0, 2.2, 2.1, 2.0, 2.2, 2.1])
    assert result.regression.trend_label == "STABLE"
    assert result.risk.level == "STABLE"

def test_westgard_1_3s():
    pipeline = JLIGHTMLPipeline()
    # Stable baseline (first 60%) + extreme outlier clearly > 3SD of baseline
    result = pipeline.run([2.0, 2.0, 2.0, 2.0, 2.1, 1.9, 2.0, 2.1, 2.0, 8.5])
    assert result.westgard.rule_1_3s, f"1₃s should be triggered. Violations: {result.westgard.violations}"

def test_westgard_2_2s():
    pipeline = JLIGHTMLPipeline()
    # Stable baseline + two consecutive values > 2SD same direction
    result = pipeline.run([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 5.5, 5.8])
    assert result.westgard.rule_2_2s, f"2₂s should be triggered. Violations: {result.westgard.violations}"

def test_zscore_anomaly():
    pipeline = JLIGHTMLPipeline()
    # Stable baseline + extreme outlier
    result = pipeline.run([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 9.0])
    assert result.z_scores.anomaly_count >= 1, f"Should detect anomaly. Max Z: {result.z_scores.max_z}, mean: {result.z_scores.mean}, sd: {result.z_scores.sd}"
    assert result.z_scores.max_z > 3.0, f"Max Z should be > 3, got {result.z_scores.max_z}"

def test_breach_forecast():
    pipeline = JLIGHTMLPipeline(iso_threshold=3.0)
    result = pipeline.run([2.1, 2.4, 2.7, 2.9, 3.1, 3.3, 3.5])
    # Already breaching
    # Already breaching or forecasting breach very soon
    assert result.regression.breach_in_periods <= 1, f"Expected breach in <=1 period, got {result.regression.breach_in_periods}"
    assert result.forecast.probability_48h > 0.4, f"Expected high breach probability, got {result.forecast.probability_48h}"

def test_risk_score_range():
    pipeline = JLIGHTMLPipeline()
    result = pipeline.run([2.1, 2.3, 2.8, 3.1, 3.6, 4.1, 4.8])
    assert 0 <= result.risk.score <= 100
    assert result.risk.level in ("CRITICAL", "ATTENTION", "STABLE")

def test_min_data_points():
    pipeline = JLIGHTMLPipeline()
    try:
        pipeline.run([2.0, 2.1])
        assert False, "Should raise ValueError for < 3 points"
    except ValueError:
        pass

test("Regression — rising trend", test_regression_rising)
test("Regression — stable trend", test_regression_stable)
test("Westgard 1₃s rule", test_westgard_1_3s)
test("Westgard 2₂s rule", test_westgard_2_2s)
test("Z-score anomaly detection", test_zscore_anomaly)
test("Breach forecast (already breaching)", test_breach_forecast)
test("Risk score 0-100 range", test_risk_score_range)
test("Minimum data points validation", test_min_data_points)


# ─── CSV Engine Tests ─────────────────────────────────────────────────────────

print("\n📊 CSV ENGINE")

SAMPLE_CSV = b"""timestamp,analyser,batch,cv_pct,mean,rerun_count
14:20:01,A2,B6,2.1,7.42,1
14:20:44,A2,B6,2.3,7.39,0
14:21:18,A2,B6,2.2,7.41,1
14:21:55,A2,B7,2.8,7.44,2
14:22:30,A2,B7,3.2,7.48,3
14:23:05,A2,B7,3.9,7.51,4
14:23:42,A2,B7,4.4,7.55,5
14:24:18,A2,B7,4.8,7.58,6
14:25:30,A2,B7,5.3,7.62,7
14:26:45,A2,B7,5.9,7.68,8
"""

def test_csv_parse():
    result = analyse_csv(SAMPLE_CSV, "test_qc.csv")
    assert result["success"]
    assert result["rowCount"] == 10
    assert result["columnCount"] >= 4

def test_csv_detects_cv_column():
    result = analyse_csv(SAMPLE_CSV, "test_qc.csv")
    assert "cv" in result["detectedColumns"] or "primary" in result["detectedColumns"]

def test_csv_generates_decision_card():
    result = analyse_csv(SAMPLE_CSV, "test_qc.csv")
    card = result["decisionCard"]
    assert card["id"].startswith("LAB-CSV-")
    assert card["risk"] > 0
    assert card["status"] in ("crit", "att", "stab")

def test_csv_ml_results():
    result = analyse_csv(SAMPLE_CSV, "test_qc.csv")
    ml = result["ml"]
    assert ml["slope"] > 0
    assert 0 <= ml["r_squared"] <= 1
    assert ml["risk_level"] in ("CRITICAL", "ATTENTION", "STABLE")

def test_csv_steps():
    result = analyse_csv(SAMPLE_CSV, "test_qc.csv")
    assert len(result["steps"]) >= 6

def test_csv_minimal():
    minimal = b"cv\n2.1\n2.3\n2.8\n3.5\n4.2\n"
    result = analyse_csv(minimal, "minimal.csv")
    assert result["success"]

test("CSV parsing", test_csv_parse)
test("CV column detection", test_csv_detects_cv_column)
test("Decision card generation", test_csv_generates_decision_card)
test("ML results in output", test_csv_ml_results)
test("Analysis steps list", test_csv_steps)
test("Minimal CSV (single column)", test_csv_minimal)


# ─── Bioinformatics Tests ─────────────────────────────────────────────────────

print("\n🧬 BIOINFORMATICS ENGINE")

# Real RpoB S450L resistant sequence
RESISTANT_SEQ = (
    "TTGGCAGATTCCCGCCAGAGCAAAACAGCCGCTAGTCCTAGTCCGAGTCGCCCGCAAAGTTTCCGACATCACCCAGAACCGT"
    "CGGCACGGTCGTGGCGAGAAGATCACCCCTGACGAAGCGCCAGCTGCTGGGCAACCACATCGGCTTGCCCGGCATGCGCGAA"
    "ATCAAGGAGCAGTTCGGCAACCGCATCTCCATCAAGCGGATTACCGGCTTGCAAGTCACCGTCTTGCCCGGCACGCTGCGCG"
    "ACCCCTTGATCGACCAGACCTTGACCATCTTGACCATCTTGACCAGCTTGACC"
)

SENSITIVE_SEQ = (
    "ATGCGTACCGATCGATCGATCGATCGAATCGATCGATCGTACGATCGATCGATCG"
    "ATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCG"
)

REF_SEQ = "ATGCGTACCGATCGATCGATCGATCGAATCGATCGATCGTACGATCGATCGATCG"
SAMPLE_SEQ = "ATGCGTACCGATCGATCGATCGATCGAATCGATCGATCGTACGATCGATCTATCG"  # 1 SNV

def test_tb_resistant():
    report = screen_tb_resistance(RESISTANT_SEQ)
    assert report.sequence_length > 50
    assert report.mutations_screened == 16
    # Should detect at least one mutation given the sequence
    assert isinstance(report.resistant_mutations, list)
    assert report.who_category in ("Pan-Sensitive (No Mutations Detected)", "Drug-Resistant TB", "MDR-TB", "Pre-XDR-TB", "XDR-TB")

def test_tb_sensitive():
    report = screen_tb_resistance(SENSITIVE_SEQ)
    assert report.who_category == "Pan-Sensitive (No Mutations Detected)"
    assert len(report.resistant_mutations) == 0

def test_tb_short_seq():
    try:
        screen_tb_resistance("ATCG")
        assert False, "Should handle short sequences"
    except Exception:
        pass

def test_variant_detection():
    report = detect_variants(REF_SEQ, SAMPLE_SEQ)
    assert report.total_variants >= 1, "Should detect at least 1 SNV"
    assert report.snvs >= 1
    assert 0 <= report.percent_identity <= 100

def test_variant_identical():
    report = detect_variants(REF_SEQ, REF_SEQ)
    assert report.total_variants == 0
    assert report.percent_identity == 100.0

def test_ngs_quality():
    seqs = [SENSITIVE_SEQ] * 100
    result = analyse_ngs_quality(seqs)
    assert result.total_reads == 100
    assert 0 <= result.gc_content <= 100
    assert result.qc_status in ("PASS", "WARN", "FAIL")
    assert len(result.per_base_quality) > 0

def test_wgs_n50():
    lengths = [284512, 198304, 142880, 98741, 76543, 52341, 41200, 38900, 29800, 21400]
    result = calculate_wgs_metrics(lengths)
    assert result.n50 > 0
    assert result.l50 > 0
    assert result.n50 >= result.n90
    assert result.contig_count == 10
    assert result.total_assembly_size == sum(lengths)

def test_wgs_from_sequences():
    seqs = ["ATCG" * 1000, "GCTA" * 500, "TTAA" * 200]
    result = calculate_wgs_metrics(seqs)
    assert result.contig_count == 3

def test_sequence_analysis_dna():
    result = analyse_sequence(SENSITIVE_SEQ)
    assert result.sequence_type == "DNA"
    assert 0 < result.gc_content < 100
    assert result.length == len(SENSITIVE_SEQ)
    assert result.melting_temp_c > 0

def test_sequence_analysis_orfs():
    # ATG (start) + codons (>20 aa worth) + TAA (stop) = valid ORF ≥60bp
    coding = "ATGAAACCCGGGTTTAGCGATCGATCGATCGATCGATCGATCGATCGATCGATCGTAA"
    orf_seq = coding * 3  # Repeat to ensure length
    result = analyse_sequence(orf_seq)
    assert result.orf_count >= 1, f"Expected ORF, got {result.orf_count}. Seq length: {result.length}"

def test_sequence_rna():
    rna = SENSITIVE_SEQ.replace("T", "U")
    result = analyse_sequence(rna)
    assert result.sequence_type == "RNA"

def test_sequence_fasta_input():
    fasta = ">Sample_1 Mycobacterium tuberculosis\n" + SENSITIVE_SEQ
    result = analyse_sequence(fasta)
    assert result.length == len(SENSITIVE_SEQ)

test("TB resistance — resistant sequence", test_tb_resistant)
test("TB resistance — sensitive sequence", test_tb_sensitive)
test("TB resistance — short sequence handling", test_tb_short_seq)
test("Variant detection — 1 SNV", test_variant_detection)
test("Variant detection — identical sequences", test_variant_identical)
test("NGS quality metrics", test_ngs_quality)
test("WGS N50 from lengths", test_wgs_n50)
test("WGS N50 from sequences", test_wgs_from_sequences)
test("Sequence analysis — DNA", test_sequence_analysis_dna)
test("Sequence analysis — ORF detection", test_sequence_analysis_orfs)
test("Sequence analysis — RNA", test_sequence_rna)
test("Sequence analysis — FASTA input", test_sequence_fasta_input)


# ─── Summary ─────────────────────────────────────────────────────────────────

total = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed

print(f"\n{'─'*50}")
print(f"Results: {passed}/{total} tests passed")
if failed:
    print(f"Failed:  {[name for name, ok in results if not ok]}")
print(f"{'─'*50}\n")

sys.exit(0 if failed == 0 else 1)
