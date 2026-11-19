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
require("await loadVerifiedOrganisationPath(user, effectivePath)" in html and
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
require("STATE.authoritativeJourneyEvents" in journey and "source_record_id" in journey,
        "Patient Journey must render server-authoritative source events with provenance")
require("async function loadAuthoritativePatientJourney(patient)" in html and
        "/api/patient-journey/" in html,
        "Patient Journey must load from the authenticated source API, not browser cache arrays")
require("STATE.patientJourneyApiStatus !== 'loaded'" in html,
        "Patient Journey reports must fail closed until authorised source events load")
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
require(r'tbdr\.lshtm\.ac\.uk\/results' in html and
        'rel="noopener noreferrer"' in html,
        "TB QC provenance links must be restricted to the official TBProfiler result host and opened safely")
require("QC warnings and review notes" in html and
        "Median target coverage is below the 30x review threshold" in html and
        "review_required_low_coverage" in html,
        "TB low-coverage warnings must be generated for raw imports and visible in the QC compartment")
for field in ("pipeline.software_version", "qc.genome_median_depth", "qc.target_median_depth",
              "qc.target_qc", "qc.num_reads_mapped"):
    require(field in html, f"TBProfiler 6.7 JSON import is missing {field}")

# Cloud restore must separate device-only records from operational workspace state.
restore_start = html.index("async function loadDomainDataFromBackend()")
restore_end = html.index("// ═", restore_start)
restore_source = html[restore_start:restore_end]
require("cloudByDomain" in restore_source and "cloudIdsByDomain" in restore_source,
        "Restore must build operational state from server-confirmed records")
require("STATE.localRecovery = recovery" in restore_source and
        "jl_local_recovery_v1::org::" in restore_source,
        "Unconfirmed local records must be retained in an organisation-scoped recovery quarantine")
require("!cloudIdsByDomain[domain].has(String(x.id))" in restore_source,
        "Quarantine must include only records absent from the cloud result")
require("const records = Array.from(cloudByDomain[domain].values())" in restore_source,
        "Operational state must contain cloud-confirmed records only")
require("function exportLocalRecovery()" in html and
        "x.path === MODE.organisationType" in html and
        "String(x.orgId || '') === String(STATE.orgId)" in html,
        "Recovery export must be scoped to the active organisation and workspace")
require("Local records need review" in html and "Export recovery records" in html,
        "Settings must expose quarantined records for review and export")

# ── Environment-bound Supabase client contract ──
require("const SB_URL" not in html and "const SB_KEY" not in html and "let _sb" not in html,
        "The legacy hardcoded production Supabase client must not return; every module uses the environment-bound client")
client_source = html[html.index("function getSupabase()"):]
client_source = client_source[:client_source.index("// ── BACKEND SYNC")]
require("_supa = window.supabase.createClient(BACKEND.url, BACKEND.key" in client_source,
        "getSupabase must initialise the single client from the host-resolved BACKEND project")
require(client_source.count("createClient") == 1,
        "Supabase must be initialised exactly once; duplicate clients cross-contaminate sessions")
require("storageKey: 'jl-auth-v10'" in client_source,
        "The auth storage key must be versioned so a session stored for another project can never be reused")
require("resolveJlightEnvironment" in html and "PRODUCTION_HOSTS" in html,
        "Environment resolution must be explicit and host-based")
require("'jlight-health.co.za', 'www.jlight-health.co.za'" in html,
        "Production hostnames must resolve only to the production Supabase project")
require("wrdwzpmpsbtkrwonejhp" in html and "ampkysrzliwjtvbigsvu" in html,
        "Both Supabase project references must be declared per environment")
require("if (host.endsWith('.netlify.app')) return 'staging'" in html,
        "Netlify deploy previews must resolve to the staging project, never production")
require("if (['localhost', '127.0.0.1', '[::1]'].includes(host)) return 'staging'" in html,
        "Local development must resolve to the staging project")
env_block = html[html.index("function resolveJlightEnvironment()"):]
env_block = env_block[:env_block.index("const BACKEND =")]
require("return null" in env_block,
        "Unknown hosts must fail closed instead of silently choosing a Supabase project")
require("if (!BACKEND?.url || !BACKEND?.key)" in client_source and "return null" in client_source,
        "getSupabase must fail closed when the host has no approved project")
require("console.info('[JLIGHT] Supabase bound to '" in client_source and
        "BACKEND.url.replace('https://', '').split('.')[0]" in client_source,
        "Diagnostics may expose the environment and project reference only, never keys")
for secret_marker in ("sb_secret_", "service_role"):
    require(secret_marker not in html, f"Browser JavaScript must never contain a {secret_marker} key")

# ── Controlled OTP lifecycle contract ──
require("let otpRequestInFlight = false" in html and "let otpRequestSeq = 0" in html and
        "let otpVerifyInFlight = false" in html,
        "The OTP lifecycle must track in-flight state and a request sequence")
require("if (otpRequestInFlight) return;" in html,
        "Duplicate login-code submissions (double click, Enter, automation) must be blocked while a request is in flight")
require("const requestSeq = ++otpRequestSeq;" in html,
        "Every login-code request must advance the request sequence")
require("if (requestSeq !== otpRequestSeq) return;" in html,
        "A stale asynchronous login-code response must not overwrite newer authentication state")
require("pending.requestedAt = Date.now();" in html,
        "A resend must supersede the previously issued code in the pending request context")
otp_request_block = html[html.index("async function doSignIn("):]
otp_request_block = otp_request_block[:otp_request_block.index("const requestSeq")]
require("otpRequestInFlight = true" in otp_request_block and "resendBtn" in otp_request_block,
        "The resend control must be disabled while a login-code request is in flight")
require("codeInput.value = \"\";" in html or "codeInput.value = '';" in html,
        "Requesting a new code must clear the previous token from the verification input")
require('await sb.auth.verifyOtp({ email, token, type: "email" })' in html,
        "Email-code verification must use the Supabase email OTP type against the same project")
require("if (verifySeq !== otpRequestSeq) throw new Error(" in html,
        "Verification of a superseded code must fail instead of opening a workspace")
verify_block = html[html.index("async function verifyLoginCode("):]
verify_block = verify_block[verify_block.index("otpVerifyInFlight = true;"):]
verify_block = verify_block[:verify_block.index("const user = data.user;")]
require("await sb.auth.getSession()" in verify_block and "await sb.auth.getUser()" in verify_block,
        "A successful verifyOtp response must be proven with a persisted session and getUser() identity")
require("if (otpVerifyInFlight) return;" in html,
        "Duplicate verification submissions must be blocked while verification is in flight")
require("let effectivePath = selectedPath;" in html and
        "sessionStorage.setItem(\"jl_selected_path\", effectivePath);" in html,
        "The selected workspace must survive a page refresh between requesting and entering the code")

# ── Workspace discovery and distinct failure contract ──
discovery_block = html[html.index("async function loadVerifiedOrganisationPath("):]
discovery_block = discovery_block[:discovery_block.index("async function verifyLoginCode(")]
require('await sb.auth.getUser()' in discovery_block and
        "String(authenticatedUser.id) !== String(user.id)" in discovery_block,
        "Workspace discovery must re-validate the signed-in identity, not cached metadata")
require('sb.rpc("jl_list_my_workspaces", { p_org_id: MODE.organisationId })' in discovery_block,
        "Workspace discovery must use the secure membership RPC, not browser-supplied entitlements")
require("Array.isArray(organisations.organisations)" in discovery_block and
        'Array.isArray(organisations.workspaces) && organisations.organisation_id' in discovery_block,
        "Discovery must parse the actual deployed JSONB response shapes without inventing permissions")
require("Approved workspace lookup failed" in discovery_block and
        "returned an unexpected response" in discovery_block,
        "RPC failures and unexpected response shapes must be reported distinctly, not as one generic message")
require("No active membership for this organisation was found" in discovery_block,
        "Empty membership must be explained as a membership problem")
require("no approved workspaces yet. JLIGHT Platform Administration must approve" in discovery_block,
        "An organisation without approved workspaces must be explained as a Platform Administration approval gap")
require("your member account does not yet have" in discovery_block and
        "Ask your organisation administrator to grant it" in discovery_block,
        "An entitled organisation with an unauthorised member must be explained as a member-permission gap")
require('sb.rpc("jlight_has_domain_permission"' in discovery_block and
        "if (canRead !== true) throw" in discovery_block,
        "Workspace entry requires a successful organisation entitlement AND individual member permission check")
require("Could not securely discover your approved workspaces" not in html,
        "The generic discovery failure message that hid the real cause must not return")
require('sb.rpc("jl_register_organisation_multi"' in html and
        'sb.rpc("jl_accept_organisation_invitation"' in html and
        'sb.rpc("jl_link_user_to_organisation"' in html,
        "Registration, joining and membership must keep using the secure server RPCs")
require('.eq("owner_user_id", user.id);' in html,
        "Organisation ownership lookup must tolerate multiple owned organisations instead of failing or picking arbitrarily")
require("This account is linked to several organisations" in html,
        "Multiple organisation memberships must be surfaced explicitly instead of silently choosing one")

# ── Environment-bound application API base contract ──
require("function resolveJlightApiBase()" in html and "const JLIGHT_API_DEFAULTS" in html,
        "The application API base must be resolved per environment, not hardcoded to one backend")
require("production: 'https://jlight-backend.onrender.com'" in html,
        "Production must resolve to the production application backend")
require("staging: 'https://jlight-backend-staging.onrender.com'" in html,
        "Staging previews and local development must resolve to the staging application backend")
require(html.count("jlight-backend-staging.onrender.com") == 1,
        "The staging backend URL must appear exactly once, inside the environment defaults")
require(html.count("jlight-backend.onrender.com") == 1,
        "The production backend URL must appear exactly once, inside the environment defaults")
require(html.count("resolveJlightApiBase();") >= 3,
        "Every application API call site must use the environment-resolved base URL")
require("No approved application API is bound to this host." in html,
        "An unresolvable API environment must fail closed instead of silently calling one backend")

print("JLIGHT frontend contract checks passed.")
