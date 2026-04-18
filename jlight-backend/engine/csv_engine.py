"""
JLIGHT v4 — CSV Analysis Engine
==================================
Parses uploaded CSV/XLSX files, detects QC columns,
runs the full ML pipeline, and returns a structured
Decision Card result.

Handles: QC logs, LIMS exports, instrument CSV, Excel files
"""

import io
import json
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

import numpy as np
import pandas as pd

from engine.ml_engine import JLIGHTMLPipeline, MLResult


# ─── Column Detection ────────────────────────────────────────────────────────

CV_KEYWORDS = ["cv", "cv%", "coeff", "coefficient", "variability", "cv_pct"]
MEAN_KEYWORDS = ["mean", "average", "avg", "result", "value", "conc", "concentration"]
BATCH_KEYWORDS = ["batch", "lot", "run", "plate", "assay"]
TIME_KEYWORDS = ["time", "timestamp", "date", "datetime", "collected", "received"]
RERUN_KEYWORDS = ["rerun", "re-run", "repeat", "repeat_count", "reruns"]
INSTRUMENT_KEYWORDS = ["instrument", "analyser", "analyzer", "machine", "unit", "device"]


def detect_column(df: pd.DataFrame, keywords: List[str]) -> Optional[str]:
    """Find the first column whose name contains any keyword."""
    for col in df.columns:
        col_lower = col.lower().replace(" ", "_").replace("-", "_")
        for kw in keywords:
            if kw in col_lower:
                return col
    return None


def extract_numeric_series(df: pd.DataFrame, col: str) -> List[float]:
    """Extract a clean numeric series from a DataFrame column."""
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    return [float(v) for v in series.tolist()]


# ─── CSV Parser ─────────────────────────────────────────────────────────────

class CSVParser:
    """
    Parses CSV or XLSX files into a structured DataFrame.
    Handles encoding issues, BOM markers, and common LIMS export quirks.
    """

    def parse(self, file_content: bytes, filename: str) -> Tuple[pd.DataFrame, Dict]:
        meta = {"filename": filename, "parse_warnings": []}

        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "csv"

        try:
            if ext in ("xlsx", "xls"):
                df = pd.read_excel(io.BytesIO(file_content), engine="openpyxl" if ext == "xlsx" else None)
            else:
                # Try common encodings
                for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
                    try:
                        text = file_content.decode(enc)
                        df = pd.read_csv(io.StringIO(text))
                        meta["encoding"] = enc
                        break
                    except (UnicodeDecodeError, Exception):
                        continue
                else:
                    raise ValueError("Could not decode file with any supported encoding")

        except Exception as e:
            meta["parse_warnings"].append(f"Parse warning: {str(e)}")
            raise

        # Clean column names
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        meta["row_count"] = len(df)
        meta["column_count"] = len(df.columns)
        meta["columns"] = list(df.columns)

        return df, meta


# ─── Decision Card Builder ───────────────────────────────────────────────────

def build_decision_card(
    ml_result: MLResult,
    filename: str,
    row_count: int,
    detected_cols: Dict,
    role: str = "Laboratory & Research",
) -> Dict[str, Any]:
    """
    Convert MLResult into a JLIGHT Decision Card structure
    matching the frontend CARDS object schema.
    """

    risk = ml_result.risk
    reg = ml_result.regression
    z = ml_result.z_scores
    w = ml_result.westgard
    fc = ml_result.forecast

    # Severity mapping
    severity_map = {"CRITICAL": "crit", "ATTENTION": "att", "STABLE": "stab"}
    severity = severity_map.get(risk.level, "att")

    # Signals list
    signals = []
    if reg.trend_label in ("RISING", "GRADUAL"):
        signals.append([f"CV Trend: {reg.trend_label} (+{reg.slope:.3f}/period)", "r" if reg.trend_label == "RISING" else "a"])
    if z.anomaly_count > 0:
        signals.append([f"{z.anomaly_count} Anomalies Detected (>{z.sd*3:.2f}%)", "r"])
    if w.rule_1_3s:
        signals.append(["Westgard 1₃s Violated", "r"])
    if w.rule_2_2s:
        signals.append(["Westgard 2₂s Violated", "r"])
    if w.rule_r_4s:
        signals.append(["Westgard R₄s Violated", "r"])
    if fc.probability_label in ("CRITICAL", "HIGH"):
        signals.append([f"Breach Prob: {fc.probability_48h:.0%} (48h)", "r"])
    if reg.breach_in_periods >= 0:
        label = "Already Breached" if reg.breach_in_periods == 0 else f"Breach in {reg.breach_in_periods} period(s)"
        signals.append([label, "r"])
    signals.append([f"R²={reg.r_squared:.3f}", "teal"])

    # ISO references
    iso = []
    if w.violations:
        iso.append(["ISO 15189 §5.6.2", f"QC CV% outside allowable limit — {len(w.violations)} Westgard rule(s) violated"])
    if risk.level == "CRITICAL":
        iso.append(["ISO 15189 §4.9", "Non-conformance — document root cause and complete CAPA form"])
        iso.append(["SANAS R47-01 §6.4", "Mandatory corrective action — notify QA Manager"])

    # Build card
    card_id = f"LAB-CSV-{hashlib.md5(filename.encode()).hexdigest()[:6].upper()}"
    now = datetime.now().strftime("%H:%M:%S SAST · %Y-%m-%d")

    card = {
        "id": card_id,
        "source": "csv_upload",
        "file": filename,
        "role": "lab",
        "status": severity,
        "risk": risk.score,
        "riskLevel": risk.level.lower(),
        "score_icon": "📊",
        "setting": f"LABORATORY · CSV Upload · {filename}",
        "title": _card_title(risk.level, z.anomaly_count, w.violations),
        "sub": f"{filename} · {row_count} rows · {now}",
        "why": _card_why(risk.level, reg, z, w),
        "signals": signals,
        "interp": _build_interpretation(ml_result, row_count, detected_cols),
        "action": _build_action(risk.level, reg, z, w),
        "iso": iso if iso else None,
        "confidence": _build_confidence(ml_result),
        "trace": f"CSV_Upload→{filename}→ML_Pipeline→Z={z.max_z:.1f}σ→{card_id}",
        "ts": now,
        "meta": [
            ["Card ID", card_id, "teal"],
            ["Severity", risk.level, "red" if risk.level == "CRITICAL" else "amber" if risk.level == "ATTENTION" else "green"],
            ["Risk Score", f"{risk.score}/100", "red" if risk.score >= 70 else "amber"],
            ["Rows Analysed", str(row_count), "teal"],
            ["Max Z-Score", f"{z.max_z:.2f}σ", "red" if z.max_z >= 3 else "amber"],
            ["Westgard", f"{len(w.violations)} violation(s)" if w.violations else "All rules passed", "red" if w.violations else "green"],
            ["Breach Prob (48h)", f"{fc.probability_48h:.0%}", "red" if fc.probability_48h >= 0.5 else "amber"],
        ],
        "ml": {
            "slope": reg.slope,
            "intercept": reg.intercept,
            "r_squared": reg.r_squared,
            "p_value": reg.p_value,
            "forecast": reg.forecast,
            "breach_in_periods": reg.breach_in_periods,
            "anomaly_count": z.anomaly_count,
            "max_z": z.max_z,
            "mean": z.mean,
            "sd": z.sd,
            "westgard_violations": w.violations,
            "sigma_metric": w.sigma_metric,
            "breach_probability_48h": fc.probability_48h,
            "breach_probability_label": fc.probability_label,
            "risk_score": risk.score,
            "risk_level": risk.level,
            "risk_components": risk.components,
            "summary": ml_result.summary,
        },
    }

    return card


def _card_title(level: str, anomalies: int, westgard: List) -> str:
    if level == "CRITICAL":
        return "Critical QC Anomaly Detected in Uploaded Data"
    elif level == "ATTENTION":
        if westgard:
            return "Westgard Rule Violation Detected in Uploaded Data"
        return "QC Irregularities Detected — Review Required"
    return "Uploaded Data Within Acceptable QC Parameters"


def _card_why(level: str, reg, z, w) -> str:
    if level == "CRITICAL":
        return (
            f"The uploaded QC data shows a {reg.trend_label.lower()} trend with "
            f"{z.anomaly_count} values exceeding 3SD from baseline. "
            f"Westgard violations detected: {len(w.violations)}. "
            "Continued deterioration will compromise result validity and trigger mandatory reruns."
        )
    elif level == "ATTENTION":
        return (
            f"QC data shows early signs of instability (slope: {reg.slope:+.3f}/period). "
            f"{z.anomaly_count} anomalous window(s) detected. "
            "Proactive intervention now prevents escalation to critical status."
        )
    return (
        "All detected QC parameters are within acceptable limits. "
        "Continue routine monitoring and maintain current QC schedule."
    )


def _build_interpretation(ml: MLResult, row_count: int, cols: Dict) -> str:
    reg = ml.regression
    z = ml.z_scores
    w = ml.westgard
    fc = ml.forecast

    parts = [
        f"Analysed {row_count} data rows across {len(cols)} detected QC columns.",
        f"Linear regression: slope {reg.slope:+.4f}/period, R²={reg.r_squared:.3f}, p={reg.p_value:.4f}.",
        f"Baseline: mean={z.mean:.3f}, SD={z.sd:.4f}.",
        f"Z-score analysis: {z.anomaly_count} anomalies detected above 3SD (max Z={z.max_z:.2f}σ).",
    ]

    if w.violations:
        parts.append(f"Westgard multi-rule evaluation: {'; '.join(w.violations)}.")
    else:
        parts.append("Westgard multi-rule evaluation: all rules passed.")

    if w.sigma_metric > 0:
        parts.append(f"Sigma metric: {w.sigma_metric:.2f} ({'acceptable' if w.sigma_metric >= 3 else 'below minimum 3.0 — action required'}).")

    parts.append(
        f"3-period forecast: {' → '.join(f'{v:.2f}%' for v in reg.forecast)}. "
        f"48h breach probability: {fc.probability_label} ({fc.probability_48h:.0%})."
    )

    if fc.time_to_breach_hours is not None and fc.time_to_breach_hours > 0:
        parts.append(f"Estimated time to ISO breach: {fc.time_to_breach_hours:.1f} hour(s).")
    elif fc.time_to_breach_hours == 0:
        parts.append("ISO 15189 QC CV% threshold already exceeded — immediate action required.")

    return " ".join(parts)


def _build_action(level: str, reg, z, w) -> str:
    if level == "CRITICAL":
        return (
            "<strong>Immediately suspend patient reporting</strong> for affected parameters. "
            "Investigate root cause: reagent lot change, instrument drift, or operator variation. "
            "Run parallel QC on backup analyser. Complete CAPA form per ISO 15189 §4.10. "
            "Notify Laboratory Manager and QA Officer."
        )
    elif level == "ATTENTION":
        return (
            "<strong>Review flagged QC windows</strong> before the next analytical run. "
            "Investigate the upward CV% trend. Consider recalibration and reagent inspection. "
            "Run expanded QC (n=5) on the next shift to confirm or exclude drift."
        )
    return (
        "<strong>No action required.</strong> "
        "All detected parameters are within acceptable QC limits. "
        "Continue routine monitoring schedule."
    )


def _build_confidence(ml: MLResult) -> List[float]:
    reg = ml.regression
    z = ml.z_scores
    # Confidence scores for radar chart [Detection, Accuracy, Causation, Urgency, DataQuality, Confidence]
    detection = min(0.99, 0.6 + (z.anomaly_count * 0.1))
    accuracy = min(0.99, reg.r_squared + 0.1)
    causation = min(0.99, 0.5 + (len(ml.westgard.violations) * 0.15))
    urgency = ml.forecast.probability_48h
    data_quality = min(0.99, 0.7 + (reg.r_squared * 0.2))
    confidence = min(0.99, (detection + accuracy + data_quality) / 3)
    return [round(v, 2) for v in [detection, accuracy, causation, urgency, data_quality, confidence]]


# ─── Main Analysis Function ──────────────────────────────────────────────────

def analyse_csv(
    file_content: bytes,
    filename: str,
    role: str = "Laboratory & Research",
    iso_threshold: float = 3.0,
    tea: float = 10.0,
) -> Dict[str, Any]:
    """
    Full CSV analysis pipeline.
    Returns structured result matching the frontend Decision Card schema.
    """

    parser = CSVParser()
    df, meta = parser.parse(file_content, filename)

    # Detect QC columns
    cv_col = detect_column(df, CV_KEYWORDS)
    mean_col = detect_column(df, MEAN_KEYWORDS)
    time_col = detect_column(df, TIME_KEYWORDS)
    batch_col = detect_column(df, BATCH_KEYWORDS)
    rerun_col = detect_column(df, RERUN_KEYWORDS)

    detected_cols = {k: v for k, v in {
        "cv": cv_col, "mean": mean_col, "timestamp": time_col,
        "batch": batch_col, "rerun": rerun_col
    }.items() if v}

    # Extract primary series for analysis
    primary_col = cv_col or mean_col
    if not primary_col:
        # Fall back to first numeric column with >3 values
        for col in df.columns:
            series = extract_numeric_series(df, col)
            if len(series) >= 3:
                primary_col = col
                detected_cols["primary"] = col
                break

    if not primary_col:
        return {
            "error": "No numeric QC columns detected",
            "meta": meta,
            "detected_cols": detected_cols,
            "row_count": meta["row_count"],
            "column_count": meta["column_count"],
        }

    values = extract_numeric_series(df, primary_col)
    timestamps = None
    if time_col:
        timestamps = df[time_col].astype(str).tolist()

    # CV% for Westgard sigma
    cv_pct = None
    if cv_col and values:
        cv_pct = float(np.mean(values))

    # Run ML pipeline
    pipeline = JLIGHTMLPipeline(iso_threshold=iso_threshold, tea=tea)
    ml_result = pipeline.run(values, timestamps, cv=cv_pct)

    # Build Decision Card
    card = build_decision_card(ml_result, filename, meta["row_count"], detected_cols, role)

    # Build steps for frontend animation
    steps = [
        {"step": "📥 File received", "detail": f"{meta['row_count']} rows · {meta['column_count']} columns · {filename}", "colour": "teal"},
        {"step": "🔍 Schema detected", "detail": f"Columns: {', '.join(list(detected_cols.keys())[:5])}", "colour": "teal"},
        {"step": "📐 Baseline computed", "detail": f"Mean: {ml_result.z_scores.mean:.3f} · SD: {ml_result.z_scores.sd:.4f} · n={len(values)}", "colour": "teal"},
        {"step": "📈 Linear regression", "detail": f"Slope: {ml_result.regression.slope:+.4f}/period · R²={ml_result.regression.r_squared:.3f} · {ml_result.regression.trend_label}", "colour": "teal" if ml_result.regression.slope <= 0 else "amber"},
        {"step": "🔍 Anomaly detection", "detail": f"Max Z: {ml_result.z_scores.max_z:.2f}σ · {ml_result.z_scores.anomaly_count} above 3SD · Westgard: {len(ml_result.westgard.violations)} violation(s)", "colour": "red" if ml_result.z_scores.anomaly_count > 0 else "teal"},
        {"step": "🔮 Breach forecast", "detail": f"Probability: {ml_result.forecast.probability_label} ({ml_result.forecast.probability_48h:.0%}) · 3-period: {' → '.join(str(v) for v in ml_result.regression.forecast)}", "colour": "red" if ml_result.forecast.probability_48h >= 0.5 else "amber"},
        {"step": "🧠 Risk stratification", "detail": f"{ml_result.risk.level} · Score {ml_result.risk.score}/100 · Sigma: {ml_result.westgard.sigma_metric:.2f}", "colour": "red" if ml_result.risk.level == "CRITICAL" else "amber" if ml_result.risk.level == "ATTENTION" else "teal"},
        {"step": "📋 Decision Card generated", "detail": f"{ml_result.risk.level} severity · {card['id']}", "colour": "green"},
    ]

    return {
        "success": True,
        "rowCount": meta["row_count"],
        "columnCount": meta["column_count"],
        "detectedColumns": detected_cols,
        "primaryColumn": primary_col,
        "severity": card["status"],
        "riskScore": card["risk"],
        "steps": steps,
        "decisionCard": card,
        "ml": card["ml"],
        "summary": ml_result.summary,
    }
