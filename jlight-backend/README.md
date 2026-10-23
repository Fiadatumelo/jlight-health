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


## Source-system interoperability (staging foundation)

The source-workflow API is a **read-only integration layer** over events and records exported by existing Hospital, Laboratory, and Bioinformatics systems. It does not replace those systems, operate analysers, process specimens, or write back into source systems. Clinical Trials remains a separate participant workflow.

New authenticated endpoints:
- `POST /api/source-records` — append an immutable, versioned source record.
- `POST /api/workflow-events` — append a source-observed workflow event.
- `POST /api/connectors/ingest` — ingest a read-only FHIR R4 Bundle, HL7 v2 status message, or mapped CSV export directly. This is a push/import adapter, not an automatic live-system connector.
- `POST /api/connectors/queue` — durably enqueue a FHIR/HL7 v2/CSV export using `Idempotency-Key` (or `idempotency_key` in the JSON body); repeated keys with changed content are rejected for review.
- `POST /api/connectors/queue/process` — owner/admin-only processing of queued exports with bounded retries, worker leases, duplicate-safe event persistence, and dead-letter status after repeated failures.
- `GET /api/workflow-timelines` — read the tenant's event timeline.
- `GET /api/decision-cards` — generate explainable operational delay cards with exact source-event evidence.
- `GET /api/connector-freshness` — report when each source feed last delivered an event; this does not directly probe the source system.
- `POST /api/patient-keys` and `GET /api/patient-keys` — create/list pseudonymous canonical journey keys (owner/admin creation).
- `POST /api/patient-links` — append an owner/admin-verified source identity link or unlink event. Raw source references are HMACed and not stored.
- `GET /api/patient-journeys` — combine verified Hospital, Laboratory and Bioinformatics events into one patient journey; unverified events are excluded and Clinical Trials remains separate.

All listed API endpoints require a valid Supabase Auth bearer token and an `X-JLIGHT-Organization` UUID. The API verifies active membership against `jlight_organization_memberships`. Viewer memberships are read-only. Client-supplied patient IDs are deliberately not accepted as verified links; records remain unlinked until a separate trusted patient-linking workflow is implemented.

Before staging use:
1. Configure `SUPABASE_URL`, `DATABASE_URL`, and a random `JLIGHT_LINKING_SECRET` of at least 32 characters in the backend environment. Keep the linking secret identical across API instances and rotate it only through a planned re-hash migration.
2. Apply `migrations/20261023110000_cross_section_persistence.sql`, `migrations/20261023123000_organization_memberships.sql`, `migrations/20261023160000_trusted_patient_linking.sql`, and `migrations/20261023180000_durable_ingestion_queue.sql` to a **non-production** PostgreSQL database.
3. Provision an organization and membership using a trusted administrative process; never expose membership self-assignment to clients.
4. Configure `DATABASE_URL` with a dedicated database login that is explicitly granted membership in the non-login `jlight_runtime` role. The API executes `SET ROLE jlight_runtime` on every connection. Do not use the table-owner or a `BYPASSRLS` login for the deployed API.
5. Verify row-level security with two synthetic organizations, then run the synthetic tests and exercise the endpoints with synthetic Hospital/Laboratory/Bioinformatics records before connecting real systems.
6. Configure a source-specific export/push job in the existing HIS/LIS/EMR to send a FHIR Bundle, supported HL7 v2 status message, or mapped CSV export to `/api/connectors/queue`, using a stable idempotency key for each export. When service is restored, an authenticated owner/admin can call `/api/connectors/queue/process` to process and retry queued exports. The queue protects exports already received by JLIGHT; it cannot receive data while JLIGHT is fully offline, and does not poll remote systems automatically.
7. Review each generated Decision Card with an operational subject-matter expert and configure a workflow-appropriate delay threshold before using alerts operationally.
8. A trusted owner/admin must create a pseudonymous journey key and verify source-system patient crosswalks before events can be combined across Hospital, Laboratory and Bioinformatics. Source references are stored as keyed HMAC digests, not raw identifiers. This verification process must be governed by the organisation's patient-identity and POPIA procedures.

These migrations are not automatically applied by the API. No live source-system connector or production deployment is implied by these endpoints.
