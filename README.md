# JLIGHT — Health Intelligence Platform

> **Detecting errors in South African laboratories, hospitals, and clinical trial sites that current systems are not designed to detect.**

**Live Demo:** [jlight-health.co.za](https://jlight-health.co.za)
**Built by:** Fiada Mothapo — Founder & Director, Hunadi Medica
**Contact:** info@hunadimedica.co.za · 083 946 1431

---

## What is JLIGHT?

JLIGHT is a unified health intelligence platform operating in two modes:

- **Standalone mode** — complete LIS, CTMS, HIS, and Bioinformatics LIMS for facilities with no existing system
- **Overlay mode** — connects to existing systems via HL7 v2.5 and runs automatic error detection on every result, admission, and clinical event without changing any existing workflow

The core innovation is detecting **errors of absence** — the missing specimen, the unacknowledged critical result, the QC run trending toward failure before it fails, the admitted patient with no laboratory work ordered, the trial participant approaching loss to follow-up.

---

## The Problem JLIGHT Solves

| Documented Failure | Current System | JLIGHT |
|---|---|---|
| 31.4% of critical results not acknowledged within 24h (Tygerberg 2024) | No alert | Patient Journey Engine fires immediately |
| Pre-analytical specimen losses undetectable (Wits/NHLS 2025) | Invisible | Completeness Engine flags missing orders |
| QC run trending toward failure | Flags after failure | Predictive Drift forecasts before failure |
| SAE reporting deadline missed at trial sites | No automated clock | SAE Clock Engine monitors from onset |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  DATA SOURCES: Existing LIS · HIS · HL7 v2.5 · Manual Entry │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              JLIGHT INTELLIGENCE LAYER                      │
│  Westgard QC · Delta-Check · Predictive Drift               │
│  Completeness · HAI Cluster · TAT Monitor                   │
│  Patient Journey · SAE Clock · Visit Windows                │
│  LTFU Risk · NGS Quality                                    │
│  ──────────────────────────────────────────────             │
│  AI ENRICHMENT — Large language model via Anthropic API     │
│  Clinical context · Cross-domain reasoning · Natural lang.  │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌───────────┬──────────────┬──────────┬────────────────────── ┐
│Laboratory │Clinical Trial│ Hospital │   Bioinformatics      │
└───────────┴──────────────┴──────────┴───────────────────────┘
                           ▼
                    DECISION CARDS
        AI-enriched · Named · Timestamped · Audit chain
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla JavaScript · Single HTML file · No framework |
| Database | Supabase (PostgreSQL + Auth + Realtime + RLS) |
| AI Engine | Anthropic API (claude-sonnet-4-20250514) |
| Integration | HL7 v2.5 parser (ORU^R01, ADT^A01/A03) |
| Auth | Supabase JWT · Row-Level Security at Postgres level |
| Audit | SHA-256 cryptographic hash chain (ISO 15189 / GCP compliant) |
| Hosting | Netlify CDN |
| Offline | localStorage sync · auto-merge on reconnect |

---

## AI Integration

JLIGHT integrates a large language model via the Anthropic API for intelligent Decision Card enrichment. When an intelligence engine detects an error, the AI:

1. **Analyses clinical context** — patient history, result patterns, facility environment
2. **Generates natural language explanation** — what was detected and why it matters
3. **Provides evidence-based recommendations** — specific next steps for this patient
4. **Scores urgency** — based on combination of signals, not just individual thresholds

Rule-based engines fire when a number crosses a threshold. The AI adds what thresholds cannot provide: contextual reasoning, cross-domain pattern recognition, and plain language a ward nurse or trial coordinator can act on immediately.

```javascript
const response = await fetch('https://api.anthropic.com/v1/messages', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1000,
    system: 'JLIGHT clinical intelligence engine for South African health facilities...',
    messages: [{ role: 'user', content: `Analyse: ${JSON.stringify(eventData)}` }]
  })
})
```

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

## Database Schema

25 normalised tables. Full Row-Level Security at Postgres level.

```
Core:           jl_organisations · jl_user_profiles · jl_patients
Laboratory:     jl_instruments · jl_reagent_lots · jl_lab_orders
                jl_lab_samples · jl_lab_results · jl_lab_qc
Clinical Trial: jl_protocols · jl_participants · jl_visits
                jl_adverse_events · jl_deviations · jl_consents
Hospital:       jl_wards · jl_admissions · jl_clinical_orders · jl_infections
Bioinformatics: jl_bio_accessions · jl_bio_runs · jl_bio_qc · jl_bio_amr
Intelligence:   jl_cards · jl_audit · jl_requests
```

---

## Setup

**Step 1 — Database (Supabase SQL Editor)**
Run `schema/01_fix_columns.sql` then `schema/02_schema.sql`

**Step 2 — Deploy**
Copy `index.html` to any static host or Netlify. No build step required.

**Step 3 — First use**
Open the URL → Create workspace → Choose role → Register patients → Start working

---

## Project Structure

```
jlight-health/
├── index.html          # Complete application — single file
├── schema/
│   ├── 01_fix_columns.sql
│   └── 02_schema.sql
└── README.md
```

---

## The Problem in Numbers

| Metric | Source |
|---|---|
| 6.3M blood tests unprocessed — NHLS ransomware 2024 | SAMJ Nov 2024 |
| 31.4% critical results unacknowledged within 24h | Davids et al. AJLM 2024 |
| R4.12B medicolegal payouts in 3 years | SA NDOH Auditor-General 2024 |
| R2B corruption — one hospital (Tembisa 2025) | SIU Interim Report 2025 |
| 80% of SA population served by NHLS | NHLS Annual Report |

---

## Founder

**Fiada Mothapo** — Medical Scientist · Founder & Director, Hunadi Medica

- NICD Centre for Respiratory Diseases & Meningitis — high-throughput diagnostics, COVID-19 peak
- NICD Centre for Tuberculosis — national TB drug-resistance surveillance programme
- Next Bioscience — whole-genome sequencing, products of conception
- Cytespace Africa Laboratories — GCP/GCLP clinical trial sample management
- Ampath Laboratories · Lancet Laboratories — routine and molecular diagnostics

**Qualifications:** BSc Microbiology, Biotechnology & Genetics (Wits) · BSc(Hons) Medical Microbiology (UP) · ICH GCP Certified · GCLP Certified

---

*JLIGHT — Built in South Africa. For South Africa.*
