"""Static contract checks for the JLIGHT proposal-aligned frontend."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
html = (ROOT / "index.html").read_text(encoding="utf-8")


def require(condition, message):
    if not condition:
        raise AssertionError(message)

bio_schema_start = html.index("bioRuns: {")
bio_schema_end = html.index("\n}", bio_schema_start)
bio_schema = html[bio_schema_start:bio_schema_end]
for field in ("analysisType", "outputType", "status", "qualityStatus",
              "summary", "createdAt", "sourceSystem", "sourceRecordId"):
    require(field in bio_schema, f"JLIGHT bioRuns import contract is missing {field}")

api_source = (ROOT / "jlight-backend/api/app.py").read_text(encoding="utf-8")
require("from engine.bio_engine import" not in api_source,
        "The legacy raw-sequence analyser must not be loaded by the JLIGHT API")
for legacy_route in ("/api/bio/tb", "/api/bio/variant", "/api/bio/ngs",
                     "/api/bio/wgs", "/api/bio/sequence", "/api/bio/fasta"):
    require(legacy_route not in api_source,
            f"Legacy raw-sequence analyser route returned: {legacy_route}")
require(not (ROOT / "jlight-backend/engine/bio_engine.py").exists(),
        "The obsolete in-product raw-sequence analyser engine must remain deleted")

# Path-first access and the four declared compartments.
for role in ("Laboratory", "Hospital", "Bioinformatics", "Trial"):
    require(f'data-path="{role}"' in html, f"Missing path selector for {role}")
require("sessionStorage.removeItem('jl_selected_path')" in html,
        "A fresh app load must require a fresh path choice")
require("Select one or more pathways for this organisation" in html and
        "Select one or more pathways for initial organisation registration" in html,
        "Initial registration must allow one or multiple pathway selections")
require('selectedPaths.map(x => ({Laboratory:"laboratory",Hospital:"hospital",Bioinformatics:"bioinformatics",Trial:"clinical_trials"})[x])' in html,
        "Initial registration must submit every selected pathway to the server")
require("await loadVerifiedOrganisationPath(user, selectedPath)" in html and
        "Your organisation or member account is not authorised for the selected workspace." in html,
        "Returning users must have the selected pathway verified against server entitlements")
require("Choose one of your approved workspaces to continue." in html,
        "Multi-workspace accounts must choose an approved workspace after sign-in")
require("Choose a JLIGHT path before signing in" not in html,
        "Obsolete single-path sign-in requirement must not return")

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
roles_start = html.index("const ROLES =")
roles_end = html.index("const REF_RANGES", roles_start)
role_block = html[roles_start:roles_end]

# Clinical Trials has its own study-scoped participant timeline, never the routine patient journey.
trial_nav_start = role_block.index("Trial:")
trial_nav_end = role_block.index("Hospital:", trial_nav_start)
trial_nav = role_block[trial_nav_start:trial_nav_end]
require("key: 'trial-timeline'" in trial_nav and "key: 'journey'" not in trial_nav,
        "Clinical Trials must use a separate participant timeline navigation")
require('id="page-trial-timeline"' in html and "async function renderTrialTimeline()" in html,
        "Dedicated Clinical Trial Participant Timeline is missing")
require("jl_trial_participant_events" in html and "selectTrialParticipant" in html,
        "Participant timeline must read canonical study-scoped event records")
require("jl_record_trial_participant_event" in html and "function recordTrialParticipantEvent()" in html,
        "Trial events must persist through the validated database event function")
require("key: 'trial-referrals'" in role_block and "function createHospitalTrialReferral()" in html,
        "Hospital-to-Clinical-Trial recruitment referral workflow is missing")
require("jl_create_trial_recruitment_referral" in html and
        "jl_create_trial_participant_from_referral" in html,
        "Recruitment hand-off and screening creation must use governed database functions")
require("jl_list_trial_recruitment_approval_queue" in html and
        "jl_list_active_trial_recruitment_authorisations" in html and
        "jl_revoke_trial_recruitment" in html,
        "Platform administration must support independent recruitment approval and revocation")
require("function submitTrialEntry()" not in html and "function analyseTrialEvent(e)" not in html,
        "Legacy local-storage Clinical Trials event entry and analysis must be removed")
require("function buildClinicalTrialsJCChecks()" not in html and
        "body: JSON.stringify({})" in html,
        "Browser must not calculate or submit Clinical Trials evidence counts; server derives them from the database")
journey_start = html.index("function buildPatientJourneyEvents(patient)")
journey_end = html.index("\nfunction selectJourneyPatient", journey_start)
journey = html[journey_start:journey_end]
require("STATE.participants" not in journey and "STATE.visits" not in journey and
        "STATE.adverseEvents" not in journey and "STATE.role==='Trial'" not in journey,
        "Routine Patient Journey must not include Clinical Trials records")
report_start = html.index("async function generatePatientJourneyReports()")
report_end = html.index("\nfunction ", report_start + 10)
journey_reports = html[report_start:report_end]
require("trialPatientIds" not in journey_reports and "STATE.role === 'Trial'" not in journey_reports,
        "Routine Patient Journey reports must not include Clinical Trials participant identities")
journey_start = html.index("function buildPatientJourneyEvents(patient)")
journey_end = html.index("\nfunction selectJourneyPatient", journey_start)
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
route_end = html.index("// ── Boot: restore an existing Supabase session", route_start)
routes = set(re.findall(r"case\s+'([^']+)'\s*:", html[route_start:route_end]))
require(not (active_keys - routes),
        "Navigation keys without routes: " + ", ".join(sorted(active_keys - routes)))

# Authentication is passwordless and workspace authorization remains server-derived.
require("sb.auth.verifyOtp({ email, token, type: \"email\" })" in html,
        "Sign-in must verify a one-time email code")
for legacy_auth in ("screen-pin", "pinPress(", "handleLogin()", "handleSetup()", "getPinHash", "setPinHash", "hashPin(", "doOfflineMode", "si-role-row"):
    require(legacy_auth not in html, f"Legacy PIN/password authentication returned: {legacy_auth}")
require('type="password"' not in html.lower(),
        "JLIGHT must not expose password-based sign-in")

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


# Dead, unreferenced handlers from superseded workflows must not return.
removed_legacy_handlers = (
    "auditHash", "chooseRole", "submitProfile", "filterJlightQuickLinks",
    "submitResult", "analyseLabSample", "generateRegistrationErrorCard",
    "getPredictiveProgress", "renderPredictiveOnboarding", "handleCSVFile",
    "parseCSV", "importCSV", "checkAuditIntegrity", "markAsFalsePositive",
    "renderRegisterBio", "generateBioReport", "runOfflineMigration", "openBioRun",
    "exportWorkspaceReport", "renderMigrationWizard", "generateOrgCode",
    "createOrganisation", "joinOrganisation", "getOrgMembers", "saveAllDomainData",
    "enrolParticipant", "submitNewRequest", "acceptLabRequest", "rejectLabRequest",
    "releaseResult", "generateResultReceivedCard", "computeAuditHash", "sha256hex",
    "validateConsentRef", "mergeByTimestamp", "detectOfflineData", "startAutoEngines",
    "updateRequestBadge",
)
for name in removed_legacy_handlers:
    require(not re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", html),
            f"Unreferenced legacy handler returned: {name}")

declarations = re.findall(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", html)
duplicates = sorted({name for name in declarations if declarations.count(name) > 1})
require(not duplicates, "Duplicate frontend function declarations: " + ", ".join(duplicates))
require("NGS_REF_RANGES" not in html, "Obsolete NGS analyser form thresholds returned")
require("JLIGHT_AI" not in html and "api.anthropic.com" not in html,
        "Direct-browser legacy AI client must remain removed")


# The old simulated NGS queue/report UI is not part of the imported-output workflow.
for legacy_bio_symbol in (
    "page-bio-pipeline", "page-bio-report", "page-bio-run-detail",
    "bio-pipeline", "bio-run-detail", "bio-report", "BIO_STAGES",
    "renderBioPipeline", "bioPipelineCard", "updateBioStage", "resubmitBio",
    "renderBioReport", "bioReportBody", "exportBioReport",
    "renderBioRunDetail", "promptBioStageUpdate",
):
    require(legacy_bio_symbol not in html,
            f"Superseded simulated Bioinformatics pipeline returned: {legacy_bio_symbol}")
require("function renderBioinformaticsReview()" in html,
        "Current imported-output Bioinformatics review page must remain")

# Tuberculosis workspace compartments use versioned TBProfiler output only.
require("id=\"page-tb\"" in html and "key: 'tb'" in role_block,
        "Dedicated Tuberculosis Intelligence page and navigation are required")
require("function renderBioinformaticsTB()" in html and "function setBioinformaticsTBTab(" in html,
        "TB intelligence compartments are not wired")
for tb_compartment in ("overview", "resistance", "lineage", "variants", "qc"):
    require("['" + tb_compartment + "'" in html or ",'" + tb_compartment + "'" in html,
            "Missing TB compartment: " + tb_compartment)
for tb_field in ("drtype", "main_lineage", "sub_lineage", "dr_variants",
                 "other_variants", "qc_fail_variants", "spoligotype"):
    require(tb_field in html, "TBProfiler output mapping is missing " + tb_field)
require("function normaliseTBProfilerResult(" in html and
        "function handleTBProfilerJsonFile(" in html and
        "function commitTBProfilerJson(" in html,
        "TBProfiler JSON validation and import workflow is incomplete")
require("syncDomainToBackend('bioRuns',imported)" in html,
        "TBProfiler records must persist through the organisation-scoped Bioinformatics domain")
require("patientLinkStatus:'not linked'" in html,
        "TBProfiler sample IDs must not be silently treated as patient IDs")
require("p_domain:'bioinformatics',p_access:'write'" in html and
        "jlight_has_domain_permission" in html,
        "Online TBProfiler imports must use server-derived Bioinformatics write permission")
require("function hydrateTBProfilerRecord(" in html and
        "JLIGHT-normalized TBProfiler CSV" in html,
        "TB compartments must support the public validation workflow's normalized CSV output")
require("summary.resistanceAssociatedVariants" in html and
        "summary.drugResistanceCall" in html and
        "summary.percentReadsMapped" in html and
        "summary.numberOfReads" in html,
        "TB importer must remain compatible with the existing public TBProfiler fixture schema")
require("function classifyTBResistanceType(" in html and
        "if(v.includes('pre-mdr'))return 'Pre-MDR-TB'" in html,
        "TB resistance classes must distinguish Pre-MDR, MDR, Pre-XDR and XDR")
require("const otherVariants = Array.isArray(summary.otherVariants)" in html and
        "r.tbProfiler?.otherVariants" in html and
        "Other detected variants" in html,
        "TB variant compartment must preserve and display non-resistance-associated variants separately")
require("summary.otherVariantCount" in html and "summary.sourceUrl" in html,
        "TB import must preserve other-variant counts and source provenance")
require(r'tbdr\\.lshtm\\.ac\\.uk\\/results' in html and
        'rel="noopener noreferrer"' in html,
        "TB QC provenance links must be restricted to the official TBProfiler result host and opened safely")

print("JLIGHT frontend contract checks passed.")
