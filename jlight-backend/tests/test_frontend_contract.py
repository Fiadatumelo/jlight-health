"""Static contract checks for the JLIGHT proposal-aligned frontend."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
html = (ROOT / "index.html").read_text(encoding="utf-8")

def require(condition, message):
    if not condition:
        raise AssertionError(message)

# Path-first access and the four declared compartments.
for role in ("Laboratory", "Hospital", "Bioinformatics", "Trial"):
    require(f'data-path="{role}"' in html, f"Missing path selector for {role}")
require("sessionStorage.removeItem('jl_selected_path')" in html,
        "A fresh app load must require a fresh path choice")
require("Choose a JLIGHT path before signing in" in html,
        "Sign-in must require an explicit path choice")

# Shared patient journey and patient-scoped report outputs.
require('id="page-journey"' in html, "Patient Journey page container missing")
require("case 'journey':" in html and "function renderJourney()" in html,
        "Patient Journey navigation is not wired")
require('onclick="generatePatientJourneyReports()"' in html,
        "Patient Journey UI does not invoke the two-report workflow")
require('id="patient-journey-report-status"' in html,
        "Patient Journey report status region is missing")
require("async function generatePatientJourneyReports()" in html,
        "Patient-specific report generation is missing")
require("patient-journey-summary" in html and "patient-data-quality-traceability" in html,
        "Both patient-specific report types must be generated")
require("journeyReport.correlationId = correlationId" in html and
        "qualityReport.correlationId = correlationId" in html,
        "The two patient reports must share a correlation ID")
require("Clinical Trials remain a separate workflow" in html,
        "Clinical Trial separation statement missing")
journey_start = html.index("function buildPatientJourneyEvents(patient)")
journey_end = html.index("\\nfunction selectJourneyPatient", journey_start)
journey = html[journey_start:journey_end]
for field in ("STATE.admissions", "STATE.clinicalOrders", "STATE.labOrders",
              "STATE.results", "STATE.bioRuns"):
    require(field in journey, f"Patient journey does not read {field}")
require("function buildJourneyReport()" not in html and
        "async function generateJourneyReport()" not in html,
        "Obsolete aggregate traceability export must be removed")

# Active navigation entries must have a route.
roles_start = html.index("const ROLES =")
roles_end = html.index("const REF_RANGES", roles_start)
role_block = html[roles_start:roles_end]
active_keys = set(re.findall(r"key:\s*'([^']+)'", role_block))
route_start = html.index("function goPage(page)")
route_end = html.index("document.addEventListener('keydown'", route_start)
routes = set(re.findall(r"case\s+'([^']+)'\s*:", html[route_start:route_end]))
require(not (active_keys - routes),
        "Navigation keys without routes: " + ", ".join(sorted(active_keys - routes)))

# Prevent accidental reintroduction of analyser-like dashboard metrics or simulated imports.
dash_start = html.index("function renderDashboard()")
dash_end = html.index("// DECISION CARDS", dash_start)
dashboard = html[dash_start:dash_end]
for label in ("Sample Error Rate", "Contamination Rate", "FP / FN Detected"):
    require(label not in dashboard, f"Out-of-scope dashboard metric returned: {label}")
require("STATE.entries       = STATE.samples" not in html,
        "Legacy sample cache must not overwrite role-scoped entries")
legacy_start = html.index("// The former CSV importer generated simulated specimen/result records")
legacy_end = html.index("// ── AUDIT INTEGRITY CHECK UI ──", legacy_start)
legacy_import = html[legacy_start:legacy_end]
require("STATE.samples.push" not in legacy_import and "analyseLabSample(" not in legacy_import,
        "Legacy CSV importer must not create simulated specimens or run analyser rules")
require("function renderBioinformaticsReview()" in html,
        "Bioinformatics review route is missing")

# Standalone source-data intake must validate and persist authorised records without running specimen engines.
for feature in ("SOURCE_IMPORT_SCHEMAS", "function parseSourceCSV(", "function previewSourceCsv()", "function commitSourceCsv()", "function retrySourceImportSync()", "syncDomainToBackend(schema.backendDomain, imported.slice"):
    require(feature in html, f"Validated source import feature missing: {feature}")
require("if (!MODE.isOnline && parsed.headers.some(h => sensitive.includes(h)))" in html,
        "Offline imports must reject identifiable columns for every record type")
require("Offline imports must be de-identified" in html,
        "Offline source imports must reject identifiable data")

print("JLIGHT frontend contract checks passed.")
