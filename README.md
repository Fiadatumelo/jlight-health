# JLIGHT — Health Intelligence Platform

> **Detecting errors in South African laboratories, hospitals, and clinical trial sites that current systems are not designed to detect.**

**Live Demo:** [jlight-health.co.za](https://jlight-health.co.za)
**Built by:** Fiada Mothapo — Founder & Director, Hunadi Medica
**Contact:** info@hunadimedica.co.za · 083 946 1431

---

## What is JLIGHT?

JLIGHT is a unified health intelligence platform operating in two modes:

- **Standalone mode** — complete LIS, CTMS, HIS, and Bioinformatics LIMS for facilities with no existing system
- **Overlay mode** — connects to existing systems via HL7 v2.5 and runs automatic error detection without changing any existing workflow

The core innovation is detecting **errors of absence** — the missing specimen, the unacknowledged critical result, the QC run trending toward failure before it fails, the admitted patient with no laboratory work ordered.

---

## The Problem JLIGHT Solves

| Documented Failure | Current System | JLIGHT |
|---|---|---|
| 31.4% of critical results not acknowledged within 24h (Tygerberg 2024) | No alert | Patient Journey Engine fires immediately |
| Pre-analytical specimen losses undetectable (Wits/NHLS 2025) | Invisible | Completeness Engine flags missing orders |
| QC run trending toward failure | Flags after failure | Predictive Drift forecasts before failure |
| SAE reporting deadline missed at trial sites | No automated clock | SAE Clock Engine monitors from onset |

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla JavaScript · Single HTML file · No framework |
| Database | Supabase (PostgreSQL + Auth + Realtime + RLS) |
| AI Engine | Anthropic API (claude-sonnet-4-20250514) |
| Integration | HL7 v2.5 parser (ORU^R01, ADT^A01/A03) |
| Auth | Supabase JWT · Row-Level Security |
| Audit | SHA-256 cryptographic hash chain (ISO 15189 / GCP) |
| Hosting | Netlify CDN |
| Offline | localStorage sync · auto-merge on reconnect |

---

## AI Integration

JLIGHT integrates a large language model via the Anthropic API for intelligent Decision Card enrichment. When an intelligence engine detects an error, the AI analyses clinical context, generates natural language explanations, and provides evidence-based recommendations specific to South African health settings.

---

## Intelligence Engines

| Engine | Domain | Standard | Detects |
|---|---|---|---|
| Westgard QC | Lab | Westgard JO 2008 | QC outside 2SD/3SD |
| Delta-Check | Lab | Strathmann et al. AJCP 2011 | Implausible result change |
| Predictive Drift | Lab | Shewhart SPC / CUSUM | QC failure before it occurs |
| Completeness | Hospital | Original | Admitted patients with no lab orders |
| Patient Journey | Hospital | Original | Results with no clinical action within 4h |
| TAT Monitor | Hospital | CAP Q-Probes | STAT >1h · Urgent >4h · Routine >24h |
| HAI Cluster | Hospital | CDC/WHO | ≥2 pathogen · same ward · 14 days |
| Visit Windows | Trial | ICH E6(R3) | Visit window compliance |
| SAE Clock | Trial | ICH E2A | 24h expedited reporting deadline |
| LTFU Risk | Trial | UNAIDS | Retention risk score ≥60 |
| NGS Quality | Bio | ACMG/AMP · GATK | Coverage · mapping · Q-score |

---

## Setup

**Step 1 — Database:** Run `schema/01_fix_columns.sql` then `schema/02_schema.sql` in Supabase SQL Editor

**Step 2 — Deploy:** Copy `index.html` to any static host. No build step required.

**Step 3 — First use:** Open URL → Create workspace → Choose role → Start working

---

## The Problem in Numbers

| Metric | Source |
|---|---|
| 6.3M blood tests unprocessed — NHLS ransomware 2024 | SAMJ Nov 2024 |
| 31.4% critical results unacknowledged within 24h | Davids et al. AJLM 2024 |
| R4.12B medicolegal payouts in 3 years | SA NDOH Auditor-General 2024 |
| 80% of SA population served by NHLS | NHLS Annual Report |

---

## Founder

**Fiada Mothapo** — Medical Scientist · Founder & Director, Hunadi Medica

NICD (Respiratory & TB) · Cytespace Africa · Next Bioscience · Ampath · Lancet

BSc Microbiology (Wits) · BSc(Hons) Medical Microbiology (UP) · ICH GCP · GCLP

---

*JLIGHT — Built in South Africa. For South Africa.*
