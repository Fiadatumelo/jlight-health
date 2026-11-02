"""WHO TB surveillance aggregate-data loader and South Africa intelligence summary.

This module handles WHO country-level surveillance/burden CSVs only. It must never
be used to create patient records, infer patient identity, or mix trial participants.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

WHO_FILES = {
    "burden": ("TB_burden_countries", {"country", "iso3", "year", "e_inc_num", "e_inc_num_lo", "e_inc_num_hi", "e_inc_100k", "e_mort_num", "e_mort_100k"}),
    "mdr_rr": ("MDR_RR_TB_burden_estimates", {"country", "iso3", "year", "e_rr_pct_new", "e_rr_pct_ret", "e_inc_rr_num"}),
    "notifications": ("TB_notifications", {"country", "iso3", "year", "new_labconf", "c_newinc"}),
    "outcomes": ("TB_outcomes_2026", {"country", "iso3", "year", "newrel_coh", "newrel_succ", "newrel_died", "newrel_lost", "c_new_tsr"}),
    "drug_resistance_surveillance": ("TB_dr_surveillance", {"country", "iso3", "year", "rr_new", "rr_ret", "mdr_new", "mdr_ret"}),
    "laboratories": ("TB_laboratories", {"country", "iso3", "year", "dx_test_sites", "m_wrd_tests_performed", "m_wrd_tests_positive"}),
    "burden_age_sex": ("TB_burden_age_sex", {"country", "iso3", "year", "measure", "unit", "age_group", "sex", "best"}),
    "outcomes_age_sex": ("TB_outcomes_age_sex", {"country", "iso3", "year", "cohort_type", "age_group", "sex", "coh", "succ", "tsr"}),
}
IDENTITY = {"country", "iso2", "iso3", "iso_numeric", "g_whoregion", "year"}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_file(directory: Path, prefix: str) -> Path:
    matches = sorted(directory.glob(prefix + "*.csv"))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {prefix}*.csv file; found {len(matches)}")
    return matches[0]


def _read_csv(path: Path, required: set[str], iso3: str) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"{path.name} missing required columns: {', '.join(missing)}")
        return [row for row in reader if (row.get("iso3") or "").strip().upper() == iso3.upper()]


def load_who_tb_bundle(directory: str | Path, *, iso3: str = "ZAF") -> dict[str, Any]:
    """Load a complete WHO aggregate TB bundle and return country-scoped rows + provenance."""
    root = Path(directory)
    datasets: dict[str, list[dict[str, str]]] = {}
    provenance: list[dict[str, Any]] = []
    for key, (prefix, required) in WHO_FILES.items():
        path = _find_file(root, prefix)
        rows = _read_csv(path, required, iso3)
        datasets[key] = rows
        years = [int(row["year"]) for row in rows if (row.get("year") or "").isdigit()]
        provenance.append({
            "dataset": key, "file": path.name, "row_count_country": len(rows),
            "year_min": min(years) if years else None, "year_max": max(years) if years else None,
            "source": "WHO Global tuberculosis data CSV supplied by user",
            "grain": "country-year aggregate" if key not in {"burden_age_sex", "outcomes_age_sex"} else "country-year-age-sex aggregate",
        })

    burden = sorted(datasets["burden"], key=lambda row: int(row["year"]))
    if not burden:
        raise ValueError(f"No WHO burden rows found for ISO3={iso3}")
    latest = burden[-1]
    previous = next((row for row in reversed(burden[:-1]) if row.get("e_inc_num") not in ("", None)), None)
    inc_latest, inc_previous = _number(latest.get("e_inc_num")), _number(previous.get("e_inc_num")) if previous else None
    mortality_latest = _number(latest.get("e_mort_num"))
    mdr = sorted(datasets["mdr_rr"], key=lambda row: int(row["year"]))
    mdr_latest = mdr[-1] if mdr else {}
    result = {
        "source": "WHO Global tuberculosis data",
        "iso3": iso3.upper(),
        "country": latest.get("country"),
        "latest_year": int(latest["year"]),
        "burden": {
            "estimated_incidence_cases": inc_latest,
            "incidence_lower": _number(latest.get("e_inc_num_lo")),
            "incidence_upper": _number(latest.get("e_inc_num_hi")),
            "incidence_per_100k": _number(latest.get("e_inc_100k")),
            "estimated_deaths": mortality_latest,
            "mortality_per_100k": _number(latest.get("e_mort_100k")),
            "case_detection_rate_percent": _number(latest.get("c_cdr")),
            "case_fatality_ratio_percent": _number(latest.get("cfr_pct")),
            "incidence_change_vs_previous_year_percent": (
                round((inc_latest - inc_previous) / inc_previous * 100, 2)
                if inc_latest is not None and inc_previous not in (None, 0) else None
            ),
        },
        "drug_resistance": {
            "year": int(mdr_latest["year"]) if mdr_latest else None,
            "rr_percent_new_cases": _number(mdr_latest.get("e_rr_pct_new")),
            "rr_percent_retreatment_cases": _number(mdr_latest.get("e_rr_pct_ret")),
            "estimated_rr_mdr_cases": _number(mdr_latest.get("e_inc_rr_num")),
        },
        "datasets": datasets,
        "provenance": provenance,
        "interpretation": {
            "data_level": "aggregate surveillance and burden estimates; not patient-level",
            "patient_matching_permitted": False,
            "clinical_diagnosis_permitted": False,
            "uncertainty": "WHO lower/upper bounds are preserved and must be displayed where supplied",
            "limitations": [
                "Estimates and notifications are different measures and must not be added together.",
                "Missing values remain unknown; they are not converted to zero.",
                "Drug-resistance burden estimates are not individual drug-susceptibility results.",
                "Country aggregates cannot validate patient matching, individual treatment decisions, or clinical outcomes.",
            ],
        },
    }
    return result


def build_tb_intelligence_cards(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Create traceable review signals from aggregate trends, not clinical recommendations."""
    burden = bundle["burden"]
    cards: list[dict[str, Any]] = []
    change = burden.get("incidence_change_vs_previous_year_percent")
    if change is not None:
        cards.append({
            "type": "population_trend", "severity": "information",
            "title": "Estimated TB incidence trend",
            "signal": f"Estimated incidence changed {change:+.2f}% versus the previous year.",
            "value": burden.get("estimated_incidence_cases"),
            "source": bundle["source"], "year": bundle["latest_year"],
            "requires_human_review": True,
        })
    rr = bundle["drug_resistance"]
    if rr.get("rr_percent_new_cases") is not None or rr.get("rr_percent_retreatment_cases") is not None:
        cards.append({
            "type": "drug_resistance_surveillance", "severity": "review",
            "title": "Rifampicin-resistant TB surveillance estimate",
            "signal": "WHO population-level RR estimates; not a patient result.",
            "new_case_percent": rr.get("rr_percent_new_cases"),
            "retreatment_case_percent": rr.get("rr_percent_retreatment_cases"),
            "year": rr.get("year"), "source": bundle["source"],
            "requires_human_review": True,
        })
    return cards
