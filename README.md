# JLIGHT — Health Intelligence System v4

> **Africa Developers Hackathon 2026 — Top 30 Finalist**  
> Built by **Fiada Mothapo** · Medical Scientist · 10+ years lab, clinical trials & hospital experience

🌍 **Live Demo:** [jlight-health.co.za](https://jlight-health.co.za)

---

## What is JLIGHT?

JLIGHT is a real-time health intelligence platform that monitors laboratory, clinical trial, and hospital operations simultaneously — detecting anomalies, forecasting breaches, and generating actionable Decision Cards before problems escalate into patient harm.

It bridges a critical gap in African health infrastructure: existing systems like LIMS, CTMS, and HIS generate data but provide no cross-system intelligence. JLIGHT connects them all and reasons across them.

---

## The Problem

A laboratory in Gauteng is running a batch of haematology tests. QC CV% has been drifting upward for 6 hours. Nobody notices — the analyser shows no instrument fault. Meanwhile, the same pattern is happening on 3 analysers sharing a contaminated reagent lot.

Downstream: 47 patient results have already been reported. 8 are incorrect.

**JLIGHT would have caught this in the first window — before a single result was reported.**

This is not hypothetical. It is a documented failure mode in South African laboratory practice that JLIGHT was specifically designed to prevent.

---

## Core Features

### 🔮 6-Step Intelligence Loop

| Step | What happens |
|------|-------------|
| **01 · Ingest** | Pulls from LIMS, CTMS, HIS, FASTQ pipelines |
| **02 · Baseline** | 7-day adaptive rolling baseline per analyte per analyser |
| **03 · Detect** | Z-score + Westgard multi-rules (1₂s, 2₂s, R₄s, 4₁s, 10ₓ) |
| **04 · Predict** | Linear regression trend + time-to-breach forecast |
| **05 · Reason** | Root cause + ISO standard mapping + SA regulatory check |
| **06 · Deliver** | Decision Card generated + saved to DB + alert dispatched |

### 📋 Decision Cards

Each card contains: risk score (0–100), patient impact statement, detected signals, intelligence interpretation, recommended action, standards violated, troubleshooting steps, confidence radar, and detection timeline.

### 👥 Three Role-Based Dashboards

**🧪 Lab Manager** — QC alerts, rerun rate, TAT, sigma metrics, reagent lot tracking  
Cards: batch instability, reagent contamination, SOP deviation, instrument drift, NGS QC failure

**💊 Trial Monitor** — Protocol deviations, consent compliance, SAE tracking, site risk  
Cards: consent violations, SAE expedited report, site risk elevation

**💓 Hospital Ops** — Bed occupancy, discharge lag, ward TAT, HAI cluster detection  
Cards: cross-department bottleneck, bed capacity critical, CLABSI cluster

### 🧬 Bioinformatics Engine

All runs client-side — no external APIs, fully POPIA compliant:

| Tab | Functionality |
|-----|--------------|
| **NGS QC** | FastQC-style metrics, Q30/GC%/duplication, coverage depth, auto-generates QC Decision Card |
| **TB Drug Resistance** | Screens against 8 MTBC mutations per WHO 2023 + NICD 2024 guidelines |
| **Variant Analysis** | SNP/INDEL detection, ACMG/AMP Class 1–5 classification |
| **WGS Metrics** | N50 calculator, contig distribution, POC chromosomal analysis |
| **Sequence Analyser** | GC%, reverse complement, DNA→RNA, ORF detection |

### 📁 Real CSV Analysis

Upload any lab data CSV and JLIGHT reads the actual file, detects column schema, computes Z-scores per row, runs all Westgard multi-rules, performs linear regression breach forecasting, and generates a full Decision Card from your real data. Analysis runs via Netlify backend with full client-side fallback.

### 📧 Email Backend

Real HTML emails via Resend API — compliance audit reports, intelligence summaries, and critical alert notifications when cards are escalated.

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │      jlight-health.co.za      │
                    │      Netlify CDN (Global)     │
                    └────────────┬─────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼──────┐  ┌────────▼──────┐  ┌───────▼───────┐
     │  send-email   │  │ analyse-csv   │  │ health-check  │
     │  Netlify Fn   │  │  Netlify Fn   │  │  Netlify Fn   │
     │  (Resend API) │  │ (Statistics)  │  │  (DB ping)    │
     └───────────────┘  └───────────────┘  └───────────────┘
                                 │
                    ┌────────────▼──────────────────┐
                    │      Supabase (ZA region)      │
                    │  Auth · PostgreSQL · RLS       │
                    │  profiles · decision_cards     │
                    │  alerts · csv_uploads          │
                    │  audit_log · system_health_log │
                    └───────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS — single file, zero build tools |
| Backend | Netlify Functions (Node.js serverless) |
| Database | Supabase PostgreSQL with Row Level Security |
| Auth | Supabase Auth (PKCE flow) |
| Email | Resend API |
| Deployment | Netlify CDN |
| Data residency | South Africa (Johannesburg) |

---

## South African Standards Coverage

| Standard | Area |
|----------|------|
| ISO 15189 | QC CV limits, calibration, pre-analytical, non-conformance |
| SANAS R47-01 | SA NATA accreditation, reagent lot validation |
| SANS 10212 | Specimen transport cold chain |
| NCS Domain 2, 4, 6, 7 | Staffing, bed capacity, TAT, infection control |
| ICH E6(R2) | GCP consent, SAE reporting, risk-based monitoring |
| SA GCP Regulations | SAHPRA notification timelines (7-day, 15-day) |
| NICD Guidelines | TB WGS QC, HAI cluster notification, drug resistance |
| POPIA | Data residency, access control, immutable audit log |
| WHO Catalogue 2023 | TB drug resistance mutations |

---

## Database Schema

```
profiles          — User accounts linked to Supabase Auth
decision_cards    — Intelligence cards with full status tracking
alerts            — Notifications linked to cards
csv_uploads       — Upload history with full analysis results
audit_log         — Immutable POPIA-compliant action log (INSERT-only)
system_health_log — Health check history
```

All tables enforce Row Level Security. `audit_log` has no UPDATE or DELETE policies — required by POPIA.

---

## Why JLIGHT is Different

| Competitor | Gap | JLIGHT's answer |
|-----------|-----|----------------|
| LabWare / STARLIMS | Lab-only, no cross-system intelligence | Multi-system correlation + predictive alerts |
| Medidata Rave | Trial data only | Live intelligence across lab, trials, hospital |
| Epic / MedRecord HIS | Generates data, doesn't analyse it | Reasons across HIS + LIMS + CTMS simultaneously |
| REDCap | Data collection only | Full intelligence + decision support |
| All of the above | No SA regulatory awareness | POPIA, SAHPRA, NICD, SANAS, NCS built in |
| All of the above | No bioinformatics | WGS, NGS QC, TB resistance, variant calling included |

---

## Running Locally

No build tools needed — open `index.html` directly in any browser.

For full backend functionality:
```bash
npm install -g netlify-cli
netlify dev
```

Set environment variables:
```
RESEND_API_KEY=re_your_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
```

---

## Project Structure

```
├── index.html                         Main application (263KB)
├── netlify.toml                       Netlify configuration
├── package.json                       Node.js project
├── netlify/functions/
│   ├── send-email.js                  Email sending (reports + alerts)
│   ├── analyse-csv.js                 Statistical analysis (Westgard + Z-score)
│   └── health-check.js               System health monitoring
└── supabase/migrations/
    └── RUN_THIS_IN_SUPABASE.sql      Schema + RLS + indexes + seed data
```

---

## Roadmap

| Phase | Focus |
|-------|-------|
| **v4 — Live now** | Intelligence engine · 3 roles · Bioinformatics · Full backend |
| **v5 — 3–6 months** | Next.js · Real LIMS CSV import · Mobile app |
| **v6 — 6–12 months** | HL7 v2.5 · FHIR R4 · Multi-facility · Enterprise SSO |
| **v7 — 12–24 months** | Pan-African · DHIS2 · SAHPRA auto-reporting · Predictive ML |

---

## About the Builder

**Fiada Mothapo** is a Medical Scientist with 10 years of hands-on combined experience across laboratory management, clinical trial monitoring, hospital operations, and NGS bioinformatics.

JLIGHT is not a theoretical product. Every decision card, every ISO standard, every troubleshooting step, and every bioinformatics algorithm was written by someone who has personally managed the real-world consequences of the failures JLIGHT detects.

---

*JLIGHT — Intelligence that acts before harm does.*
