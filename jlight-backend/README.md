# JLIGHT Health Intelligence API

The Python service provides authenticated support for JLIGHT's health-intelligence workflows. It is not a wet-lab system, sequencing service, diagnostic engine, or raw-sequence analyser.

## Current API

| Method | Endpoint | Purpose | Availability |
|---|---|---|---|
| GET | `/api/health` | Service health probe | Public |
| POST | `/api/analyse-csv` | Optional, authenticated QC dataset analysis for trusted integrations | Protected |
| GET | `/api/cards` | Legacy global card listing | Disabled (503) until tenant-scoped access is implemented |
| POST | `/api/cards/acknowledge` | Legacy global card update | Disabled (503) until tenant-scoped access is implemented |
| GET | `/api/audit` | Legacy global audit listing | Disabled (503) until tenant-scoped access is implemented |

Raw sequence endpoints (`/api/bio/*`) have been retired. The current Bioinformatics experience is for reviewing imported pipeline outputs and provenance; it does not accept raw sequences or issue clinical interpretations.

The current browser application stores and reads tenant-scoped operational data through Supabase. The optional `/api/analyse-csv` endpoint is not the frontend's source-import path.

## Authentication

Protected endpoints require:

```http
Authorization: Bearer <Supabase access token>
```

Configure the backend verifier with:

- `SUPABASE_URL` — Supabase project URL.
- `SUPABASE_JWT_SECRET` — only when the project uses HS256 access tokens.
- `SUPABASE_JWT_ISSUER` and `SUPABASE_JWKS_URL` — optional overrides.
- `DATABASE_URL` — optional PostgreSQL connection for the backend's existing audit and QC persistence.
- `PORT` — supplied by the hosting service.

Keep signing secrets and database credentials in the hosting provider's secret environment. Never commit them to this repository.

## Local development

```bash
cd jlight-backend
python -m pip install -r requirements.txt
cp .env.example .env
python -m pytest tests/test_api_security.py -q
python -m unittest tests.test_interoperability
python tests/test_all.py
python api/app.py
```

The health probe is available at `http://localhost:5000/api/health`.

## Render deployment

Use the repository's configured Render service, with:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT api.app:app`

Do not use the retired manual PowerShell deployment script. Changes should flow through reviewed pull requests and the configured service branch.

## Release and integration notes

- The browser's optional JC summary request currently targets the staging API base unless an explicit `JLIGHT_CONFIG.apiBaseUrl` or `JLIGHT_API_BASE_URL` is supplied.
- The production backend branch must not be selected for that request until the authenticated `/api/intelligence/summary` contract, organisation claims, Clinical Trials exclusion, and mandatory audit persistence have been ported and validated there.
- The raw-sequence routes are intentionally absent. TBProfiler research/benchmark work must remain a separately validated worker pipeline, not a user-facing raw-sequence analyser API.
- The global card and audit endpoints remain fail-closed until organisation-scoped permissions are proven.

## Tests

The regression workflow checks frontend syntax and contracts, patient-journey privacy, source import parsing, backend authentication, interoperability, and analytical-engine behaviour. Run the commands above when changing this service.
