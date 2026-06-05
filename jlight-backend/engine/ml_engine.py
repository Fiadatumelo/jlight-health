"""
JLIGHT v4 — ML Intelligence Engine
====================================
Real Python/scikit-learn implementation of:
  - Linear regression (least squares) with R², slope, intercept
  - Z-score anomaly detection (per-window, rolling baseline)
  - Westgard multi-rule evaluation (1₃s, 2₂s, R₄s, 4₁s, 10ₓ)
  - Breach probability (logistic-style composite model)
  - Risk stratification (Critical / Attention / Stable)
  - 3-period breach forecast with ISO threshold

Author: JLIGHT · Team Fiada Mothapo · Hackathon 2026
"""

import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import warnings
warnings.filterwarnings("ignore")


# ─── Data Structures ────────────────────────────────────────────────────────

@dataclass
class RegressionResult:
    slope: float
    intercept: float
    r_squared: float
    p_value: float
    std_error: float
    trend_label: str          # RISING / GRADUAL / STABLE / DECLINING
    forecast: List[float]     # Next 3 periods
    breach_in_periods: int    # -1 = not forecast, else periods until ISO breach
    iso_threshold: float = 3.0

@dataclass
class ZScoreResult:
    z_scores: List[float]
    anomalies: List[Dict]     # [{index, value, z_score, timestamp}]
    anomaly_count: int
    max_z: float
    mean: float
    sd: float

@dataclass
class WestgardResult:
    rule_1_3s: bool           # 1 value > 3SD
    rule_2_2s: bool           # 2 consecutive > 2SD same side
    rule_r_4s: bool           # Range > 4SD within run
    rule_4_1s: bool           # 4 consecutive > 1SD same side
    rule_10x: bool            # 10 consecutive same side of mean
    violations: List[str]     # Human-readable list of violated rules
    sigma_metric: float       # (TEa - |bias|) / CV

@dataclass
class RiskScore:
    score: int                # 0-100
    level: str                # CRITICAL / ATTENTION / STABLE
    components: Dict[str, float]   # Breakdown of score components

@dataclass
class BreachForecast:
    probability_48h: float    # 0.0 – 1.0
    probability_label: str    # LOW / MODERATE / HIGH / CRITICAL
    contributing_factors: List[str]
    time_to_breach_hours: Optional[float]  # None if not forecast

@dataclass
class MLResult:
    regression: RegressionResult
    z_scores: ZScoreResult
    westgard: WestgardResult
    risk: RiskScore
    forecast: BreachForecast
    summary: str
    action_required: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Linear Regression ───────────────────────────────────────────────────────

class RegressionEngine:
    """
    Least-squares linear regression on time-series QC data.
    Uses sklearn LinearRegression with scipy for p-value computation.
    """

    def __init__(self, iso_threshold: float = 3.0):
        self.iso_threshold = iso_threshold
        self.model = LinearRegression()

    def fit(self, values: List[float], periods_ahead: int = 3) -> RegressionResult:
        if len(values) < 3:
            raise ValueError("Need at least 3 data points for regression")

        y = np.array(values, dtype=float)
        x = np.arange(len(y)).reshape(-1, 1)
        x_flat = x.flatten()

        # Fit model
        self.model.fit(x, y)
        slope = float(self.model.coef_[0])
        intercept = float(self.model.intercept_)

        # R² 
        y_pred = self.model.predict(x)
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        # p-value via scipy
        slope_scipy, intercept_scipy, r_value, p_value, std_err = stats.linregress(x_flat, y)
        
        # Trend label
        if slope > 0.3:
            trend_label = "RISING"
        elif slope > 0.05:
            trend_label = "GRADUAL"
        elif slope < -0.05:
            trend_label = "DECLINING"
        else:
            trend_label = "STABLE"

        # Forecast next N periods
        n = len(y)
        forecast = [
            round(slope * (n + i) + intercept, 3)
            for i in range(periods_ahead)
        ]

        # When does forecast breach ISO threshold?
        breach_in = -1
        for i, val in enumerate(forecast):
            if val >= self.iso_threshold:
                breach_in = i + 1
                break

        # If current data already breaching, look backwards
        if breach_in == -1 and y[-1] >= self.iso_threshold:
            breach_in = 0

        return RegressionResult(
            slope=round(slope, 4),
            intercept=round(intercept, 4),
            r_squared=round(r_squared, 4),
            p_value=round(float(p_value), 6),
            std_error=round(float(std_err), 4),
            trend_label=trend_label,
            forecast=forecast,
            breach_in_periods=breach_in,
            iso_threshold=self.iso_threshold,
        )


# ─── Z-Score Anomaly Detection ───────────────────────────────────────────────

class ZScoreEngine:
    """
    Modified Z-score anomaly detection.
    Uses rolling baseline (mean ± SD) with configurable threshold.
    """

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold

    def detect(
        self,
        values: List[float],
        timestamps: Optional[List[str]] = None,
        window: Optional[int] = None,
    ) -> ZScoreResult:
        arr = np.array(values, dtype=float)

        if window and window < len(arr):
            # Rolling baseline from first `window` points
            baseline = arr[:window]
            mean = float(np.mean(baseline))
            sd = float(np.std(baseline, ddof=1)) or 0.001
        else:
            mean = float(np.mean(arr))
            sd = float(np.std(arr, ddof=1)) or 0.001

        z_scores = [(float(v) - mean) / sd for v in arr]

        anomalies = []
        for i, (v, z) in enumerate(zip(arr, z_scores)):
            if abs(z) >= self.threshold:
                anomaly = {
                    "index": i,
                    "value": round(float(v), 4),
                    "z_score": round(z, 3),
                    "direction": "HIGH" if z > 0 else "LOW",
                }
                if timestamps and i < len(timestamps):
                    anomaly["timestamp"] = timestamps[i]
                anomalies.append(anomaly)

        return ZScoreResult(
            z_scores=[round(z, 3) for z in z_scores],
            anomalies=anomalies,
            anomaly_count=len(anomalies),
            max_z=round(float(np.max(np.abs(z_scores))), 3),
            mean=round(mean, 4),
            sd=round(sd, 4),
        )


# ─── Westgard Multi-Rule Engine ──────────────────────────────────────────────

class WestgardEngine:
    """
    Full Westgard multi-rule implementation:
      1₃s  — warning: 1 value > ±3SD
      2₂s  — reject:  2 consecutive > ±2SD same side
      R₄s  — reject:  range > 4SD within one run
      4₁s  — reject:  4 consecutive > ±1SD same side
      10ₓ  — reject:  10 consecutive same side of mean
    """

    def evaluate(
        self,
        values: List[float],
        mean: float,
        sd: float,
        tea: float = 10.0,    # Total allowable error %
        bias: float = 0.0,    # % bias
        cv: Optional[float] = None,
    ) -> WestgardResult:

        arr = np.array(values, dtype=float)
        violations = []

        # 1₃s — any single value > 3SD
        rule_1_3s = bool(np.any(np.abs(arr - mean) > 3 * sd))
        if rule_1_3s:
            violations.append("1₃s — single value exceeded ±3SD (warning)")

        # 2₂s — two consecutive > 2SD same direction
        rule_2_2s = False
        for i in range(1, len(arr)):
            d_curr = arr[i] - mean
            d_prev = arr[i - 1] - mean
            if d_curr > 2 * sd and d_prev > 2 * sd:
                rule_2_2s = True
                break
            if d_curr < -2 * sd and d_prev < -2 * sd:
                rule_2_2s = True
                break
        if rule_2_2s:
            violations.append("2₂s — two consecutive values > ±2SD same side")

        # R₄s — range within run > 4SD
        rule_r_4s = False
        for i in range(1, len(arr)):
            if (arr[i] - mean) > 2 * sd and (arr[i - 1] - mean) < -2 * sd:
                rule_r_4s = True
                break
            if (arr[i] - mean) < -2 * sd and (arr[i - 1] - mean) > 2 * sd:
                rule_r_4s = True
                break
        if rule_r_4s:
            violations.append("R₄s — range within run exceeded 4SD")

        # 4₁s — four consecutive > 1SD same side
        rule_4_1s = False
        count_high = count_low = 0
        for v in arr:
            if v - mean > sd:
                count_high += 1
                count_low = 0
            elif v - mean < -sd:
                count_low += 1
                count_high = 0
            else:
                count_high = count_low = 0
            if count_high >= 4 or count_low >= 4:
                rule_4_1s = True
                break
        if rule_4_1s:
            violations.append("4₁s — four consecutive values > ±1SD same side")

        # 10ₓ — ten consecutive same side of mean
        rule_10x = False
        count_high = count_low = 0
        for v in arr:
            if v > mean:
                count_high += 1
                count_low = 0
            else:
                count_low += 1
                count_high = 0
            if count_high >= 10 or count_low >= 10:
                rule_10x = True
                break
        if rule_10x:
            violations.append("10ₓ — ten consecutive values on same side of mean")

        # Sigma metric: σ = (TEa − |bias|) / CV
        if cv and cv > 0:
            sigma = round((tea - abs(bias)) / cv, 2)
        else:
            sigma = 0.0

        return WestgardResult(
            rule_1_3s=rule_1_3s,
            rule_2_2s=rule_2_2s,
            rule_r_4s=rule_r_4s,
            rule_4_1s=rule_4_1s,
            rule_10x=rule_10x,
            violations=violations,
            sigma_metric=sigma,
        )


# ─── Risk Stratification ─────────────────────────────────────────────────────

class RiskStratifier:
    """
    Composite risk scoring model.
    Inputs: regression slope, R², Z-score anomalies, Westgard violations.
    Output: 0-100 score + CRITICAL / ATTENTION / STABLE classification.
    """

    def score(
        self,
        regression: RegressionResult,
        z_scores: ZScoreResult,
        westgard: WestgardResult,
        current_value: float,
        iso_threshold: float = 3.0,
    ) -> RiskScore:

        components = {}

        # Trend contribution (0-30 pts)
        slope_contribution = min(30, max(0, regression.slope * 40))
        components["slope_trend"] = round(slope_contribution, 1)

        # R² confidence multiplier (stronger trend = more credible)
        r2_multiplier = 0.7 + (regression.r_squared * 0.3)

        # Anomaly contribution (0-25 pts)
        anomaly_contribution = min(25, z_scores.anomaly_count * 8)
        components["anomalies"] = round(anomaly_contribution, 1)

        # Westgard contribution (0-25 pts)
        westgard_pts = 0
        if westgard.rule_1_3s: westgard_pts += 8
        if westgard.rule_2_2s: westgard_pts += 10
        if westgard.rule_r_4s: westgard_pts += 12
        if westgard.rule_4_1s: westgard_pts += 10
        if westgard.rule_10x: westgard_pts += 15
        westgard_contribution = min(25, westgard_pts)
        components["westgard"] = round(westgard_contribution, 1)

        # Proximity to ISO threshold (0-20 pts)
        if iso_threshold > 0:
            proximity = min(20, max(0, (current_value / iso_threshold) * 20))
        else:
            proximity = 0
        components["iso_proximity"] = round(proximity, 1)

        # Forecast breach bonus (0-10 pts)
        if regression.breach_in_periods == 0:
            breach_bonus = 10
        elif regression.breach_in_periods == 1:
            breach_bonus = 8
        elif regression.breach_in_periods == 2:
            breach_bonus = 5
        elif regression.breach_in_periods == 3:
            breach_bonus = 3
        else:
            breach_bonus = 0
        components["breach_forecast"] = round(breach_bonus, 1)

        # Composite score
        raw = (slope_contribution + anomaly_contribution +
               westgard_contribution + proximity + breach_bonus)
        score = int(min(97, max(5, round(raw * r2_multiplier))))

        # Classification
        if score >= 70 or westgard.rule_r_4s or westgard.rule_10x:
            level = "CRITICAL"
        elif score >= 40 or westgard.rule_1_3s or westgard.rule_2_2s:
            level = "ATTENTION"
        else:
            level = "STABLE"

        return RiskScore(score=score, level=level, components=components)


# ─── Breach Probability Forecaster ───────────────────────────────────────────

class BreachForecaster:
    """
    Logistic-style breach probability model.
    Combines slope, R², anomaly density, and Westgard flags.
    """

    def forecast(
        self,
        regression: RegressionResult,
        z_scores: ZScoreResult,
        westgard: WestgardResult,
        current_value: float,
        iso_threshold: float = 3.0,
        measurement_interval_hours: float = 1.0,
    ) -> BreachForecast:

        # Sigmoid-like probability from weighted inputs
        logit = 0.0
        factors = []

        # Slope contribution
        if regression.slope > 0.3:
            logit += 2.5
            factors.append(f"Strong upward trend (slope +{regression.slope}/period)")
        elif regression.slope > 0.1:
            logit += 1.5
            factors.append(f"Gradual upward trend (slope +{regression.slope}/period)")
        elif regression.slope > 0:
            logit += 0.5

        # R² confidence
        if regression.r_squared > 0.8:
            logit += 1.0
            factors.append(f"High regression confidence (R²={regression.r_squared})")
        elif regression.r_squared > 0.5:
            logit += 0.5

        # Anomalies
        if z_scores.anomaly_count >= 3:
            logit += 2.0
            factors.append(f"{z_scores.anomaly_count} anomalous windows detected (>3SD)")
        elif z_scores.anomaly_count > 0:
            logit += 1.0
            factors.append(f"{z_scores.anomaly_count} anomalous window(s) detected")

        # Westgard violations
        if westgard.rule_r_4s or westgard.rule_10x:
            logit += 2.5
            factors.append("Westgard rejection rules triggered")
        elif westgard.rule_2_2s:
            logit += 1.5
            factors.append("Westgard 2₂s warning rule triggered")
        elif westgard.rule_1_3s:
            logit += 1.0
            factors.append("Westgard 1₃s warning rule triggered")

        # Proximity to threshold
        if current_value >= iso_threshold:
            logit += 3.0
            factors.append(f"Already at/above ISO threshold ({current_value:.2f}%)")
        elif current_value >= iso_threshold * 0.8:
            logit += 1.5
            factors.append(f"Within 20% of ISO threshold ({current_value:.2f}% / {iso_threshold}%)")

        # Convert logit to probability via sigmoid
        probability = 1 / (1 + np.exp(-logit + 2))  # offset so midpoint is ~logit=2
        probability = float(np.clip(probability, 0.03, 0.97))

        # Label
        if probability >= 0.70:
            label = "CRITICAL"
        elif probability >= 0.45:
            label = "HIGH"
        elif probability >= 0.25:
            label = "MODERATE"
        else:
            label = "LOW"

        # Time to breach estimate
        time_to_breach = None
        if regression.breach_in_periods > 0:
            time_to_breach = regression.breach_in_periods * measurement_interval_hours
        elif regression.breach_in_periods == 0:
            time_to_breach = 0.0

        return BreachForecast(
            probability_48h=round(probability, 3),
            probability_label=label,
            contributing_factors=factors,
            time_to_breach_hours=time_to_breach,
        )


# ─── Master ML Pipeline ──────────────────────────────────────────────────────

class JLIGHTMLPipeline:
    """
    Orchestrates the full ML pipeline for a given QC data series.
    Single entry point: pipeline.run(values, timestamps) → MLResult
    """

    def __init__(
        self,
        iso_threshold: float = 3.0,
        anomaly_threshold: float = 3.0,
        tea: float = 10.0,
        bias: float = 0.0,
    ):
        self.regression_engine = RegressionEngine(iso_threshold)
        self.zscore_engine = ZScoreEngine(anomaly_threshold)
        self.westgard_engine = WestgardEngine()
        self.risk_stratifier = RiskStratifier()
        self.breach_forecaster = BreachForecaster()
        self.iso_threshold = iso_threshold
        self.tea = tea
        self.bias = bias

    def run(
        self,
        values: List[float],
        timestamps: Optional[List[str]] = None,
        cv: Optional[float] = None,
        measurement_interval_hours: float = 1.0,
    ) -> MLResult:

        if len(values) < 3:
            raise ValueError("Minimum 3 data points required for full ML analysis")

        arr = np.array(values, dtype=float)

        # Use first 60% of data as BASELINE for Westgard (clinically correct practice)
        # Westgard limits should be established from a stable calibration period
        baseline_n = max(3, int(len(arr) * 0.6))
        baseline = arr[:baseline_n]
        mean = float(np.mean(baseline))
        sd = float(np.std(baseline, ddof=1)) or 0.001

        # Run all engines
        regression = self.regression_engine.fit(values)
        z_scores = self.zscore_engine.detect(values, timestamps, window=baseline_n)
        westgard = self.westgard_engine.evaluate(
            values, mean, sd, self.tea, self.bias, cv
        )
        risk = self.risk_stratifier.score(
            regression, z_scores, westgard, arr[-1], self.iso_threshold
        )
        forecast = self.breach_forecaster.forecast(
            regression, z_scores, westgard, arr[-1],
            self.iso_threshold, measurement_interval_hours
        )

        # Build human-readable summary
        summary_parts = [
            f"Analysed {len(values)} QC windows.",
            f"Trend: {regression.trend_label} (slope={regression.slope:+.3f}/period, R²={regression.r_squared:.3f}).",
            f"Anomalies: {z_scores.anomaly_count} windows above {self.iso_threshold}SD.",
        ]
        if westgard.violations:
            summary_parts.append(f"Westgard: {', '.join(westgard.violations[:2])}.")
        summary_parts.append(
            f"Risk: {risk.level} ({risk.score}/100). "
            f"48h breach probability: {forecast.probability_label} ({forecast.probability_48h:.0%})."
        )

        action_required = risk.level in ("CRITICAL", "ATTENTION") or bool(westgard.violations)

        return MLResult(
            regression=regression,
            z_scores=z_scores,
            westgard=westgard,
            risk=risk,
            forecast=forecast,
            summary=" ".join(summary_parts),
            action_required=action_required,
        )
