# JLIGHT v4 — Python Backend

Health Intelligence System · Team Fiada Mothapo · Hackathon 2026

## What This Is

A production Python backend for JLIGHT — replacing the browser-based JavaScript
implementation with a proper server-side stack:

- **Flask** REST API (all endpoints)
- **scikit-learn + SciPy** ML engine (regression, Z-score, Westgard, risk stratification)
- **BioPython** bioinformatics (TB resistance, variant analysis, NGS QC, WGS metrics)
- **pandas + NumPy** data ingestion and CSV analysis
- **PostgreSQL** persistent storage (audit trail, cards, uploads)
- **Docker** containerised deployment

## Structure

```
jlight-backend/
├── api/
│   └── app.py              Flask REST API (all endpoints)
├── engine/
│   ├── ml_engine.py        ML pipeline (regression, Z-score, Westgard, risk)
│   ├── csv_engine.py       CSV/XLSX analysis → Decision Card
│   └── bio_engine.py       TB resistance, variant, NGS, WGS, sequence
├── tests/
│   └── test_all.py         26 tests — all passing
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Quick Start (Local)

```bash
# 1. Clone and enter directory
cd jlight-backend

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL (optional — runs without DB in stateless mode)

# 4. Run tests
python3 tests/test_all.py

# 5. Start server
python3 api/app.py

# Server runs at http://localhost:5000
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/health | System health check |
| POST | /api/analyse-csv | CSV/XLSX QC analysis |
| POST | /api/bio/tb | TB drug resistance screening |
| POST | /api/bio/variant | SNV/INDEL variant detection |
| POST | /api/bio/ngs | NGS QC metrics |
| POST | /api/bio/wgs | WGS assembly metrics (N50) |
| POST | /api/bio/sequence | Full sequence analysis |
| POST | /api/bio/fasta | Parse FASTA/FASTQ file |
| GET | /api/cards | Decision cards from DB |
| POST | /api/cards/acknowledge | Acknowledge a card |
| GET | /api/audit | Audit log entries |

## Example: CSV Analysis

```bash
curl -X POST http://localhost:5000/api/analyse-csv \
  -H "Content-Type: application/json" \
  -d '{"csvText": "cv\n2.1\n2.3\n2.8\n3.5\n4.2\n5.1", "fileName": "qc_data.csv"}'
```

## Example: TB Resistance

```bash
curl -X POST http://localhost:5000/api/bio/tb \
  -H "Content-Type: application/json" \
  -d '{"sequence": "TTGGCAGATTCCCGCCAGAGCAAAACAGCCGCTAGTCCTAGTCCGAGTCGCCCGCAAAGTTTCCGACATCACCCAGAACCGTCGGCACGGTCGTGGCGAGAAGATCACCCCTGACGAAGCGCCAGCTGCTG"}'
```

## Deploy with Docker

```bash
# Build
docker build -t jlight-backend .

# Run (without DB — stateless mode)
docker run -p 5000:5000 jlight-backend

# Run (with PostgreSQL)
docker run -p 5000:5000 \
  -e DATABASE_URL=postgresql://user:password@host:5432/jlight \
  -e SECRET_KEY=your-secret-key \
  jlight-backend
```

## Deploy to Render.com (Free Tier)

1. Push this folder to a GitHub repo
2. Go to render.com → New Web Service
3. Connect your GitHub repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn --bind 0.0.0.0:$PORT api.app:app`
6. Add environment variables in Render dashboard
7. Done — free tier gives you 512MB RAM, 0.1 CPU

## Connecting to the JLIGHT Frontend

The frontend (`index.html`) already calls these exact endpoints:
- `/api/analyse-csv` — when a CSV is uploaded
- `/api/bio/*` — when bioinformatics functions run
- `/api/health` — system monitor page

Change the base URL in the frontend from relative paths to your backend URL:

```javascript
const API_BASE = 'https://your-backend.render.com'
// Then: fetch(`${API_BASE}/api/analyse-csv`, ...)
```

## ML Algorithms

| Algorithm | Library | Purpose |
|-----------|---------|---------|
| Linear Regression | scikit-learn | QC trend analysis, R², p-value |
| Z-Score (rolling baseline) | SciPy + NumPy | Anomaly detection per window |
| Westgard Multi-Rules | Pure Python | 1₃s, 2₂s, R₄s, 4₁s, 10ₓ |
| Logistic Breach Model | NumPy | 48h breach probability |
| Risk Stratification | Composite | CRITICAL / ATTENTION / STABLE |
| N50/L50 Calculation | NumPy | WGS assembly quality |

## Bioinformatics

| Tool | Library | Purpose |
|------|---------|---------|
| TB Resistance | BioPython + custom | 16 WHO-endorsed mutations |
| Variant Detection | Pure Python | SNV, INDEL, MNV calling |
| NGS QC | Pure Python + BioPython | GC%, Q30, duplication |
| WGS Metrics | NumPy | N50, L50, N90, assembly quality |
| Sequence Analysis | Pure Python | ORFs, Tm, MW, rev-comp |
| FASTA/FASTQ Parser | BioPython | File parsing |

## Tests

```bash
python3 tests/test_all.py
# Results: 26/26 tests passed
```

## Standards Compliance

- ISO 15189 — QC CV% threshold (3.0%), Westgard implementation
- NICD NGS Guidelines 2024 — GC content thresholds for MTBC WGS
- WHO TB Drug Resistance 2022 — mutation catalogue (16 targets)
- ACMG/AMP 2015 — variant classification framework
- POPIA — no patient-identifiable data stored; read-only integration model

---
Team JLIGHT · Fiada Mothapo · Gauteng, South Africa · 2026
