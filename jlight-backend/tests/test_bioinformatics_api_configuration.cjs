// Exercise configuration and failure paths without a browser or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../../index.html'), 'utf8');
const helper = html.slice(html.indexOf('function getJlightApiBaseUrl()'), html.indexOf('async function loadAuthoritativePatientJourney'));
const context = vm.createContext({window: {}, URL});
vm.runInContext(helper, context);
function configured(value) {
  context.window = {JLIGHT_CONFIG: {apiBaseUrl: value}};
  return context.getJlightApiBaseUrl();
}
for (const invalid of [undefined, '', '  ', '/api', 'javascript:alert(1)',
  'http://example.org', 'https://user:password@example.org',
  'https://example.org?token=synthetic', 'https://example.org/#fragment']) {
  assert.throws(() => configured(invalid), /JLIGHT API configuration/);
}
assert.equal(configured(' https://api.example.org/base/// '), 'https://api.example.org/base');
assert.equal(configured('http://localhost:5000/'), 'http://localhost:5000');
context.window = {JLIGHT_API_BASE_URL: 'https://legacy.example.org/'};
assert.equal(context.getJlightApiBaseUrl(), 'https://legacy.example.org');
assert(!html.includes('https://jlight-backend-staging.onrender.com'));
const runtime = fs.readFileSync(path.join(__dirname, '../../jlight-runtime-config.js'), 'utf8');
assert(html.indexOf('src="/jlight-runtime-config.js"') < html.indexOf('function getJlightApiBaseUrl()'));
for (const hostname of ['deploy-preview-97--jlight-health.netlify.app', 'localhost',
  'jlight-health.netlify.app', 'main--jlight-health.netlify.app']) {
  const browser = {location: {hostname}};
  vm.runInNewContext(runtime, {window: browser});
  assert.equal(browser.JLIGHT_CONFIG, undefined);
}
const stagingBrowser = {
  location: {hostname: 'deploy-preview-96--jlight-health.netlify.app'},
  JLIGHT_CONFIG: {otherSetting: 'retained', apiBaseUrl: 'https://unapproved.example.org'}
};
vm.runInNewContext(runtime, {window: stagingBrowser});
assert.equal(stagingBrowser.JLIGHT_CONFIG.apiBaseUrl, 'https://jlight-backend-staging.onrender.com');
assert.equal(stagingBrowser.JLIGHT_CONFIG.otherSetting, 'retained');
context.window = stagingBrowser;
assert.equal(context.getJlightApiBaseUrl(), 'https://jlight-backend-staging.onrender.com');
for (const hostname of ['jlight-health.co.za', 'www.jlight-health.co.za',
  'jlight-health.netlify.app', 'main--jlight-health.netlify.app']) {
  if (['jlight-health.co.za', 'www.jlight-health.co.za'].includes(hostname)) {
    const browser = {location: {hostname}, JLIGHT_CONFIG: {apiBaseUrl: 'https://jlight-backend-staging.onrender.com'}};
    vm.runInNewContext(runtime, {window: browser});
    assert.equal(browser.JLIGHT_CONFIG.apiBaseUrl, 'https://jlight-backend.onrender.com');
    context.window = browser;
    assert.equal(context.getJlightApiBaseUrl(), 'https://jlight-backend.onrender.com');
  }
  context.window = {location: {hostname}, JLIGHT_API_BASE_URL: 'https://jlight-backend-staging.onrender.com'};
  assert.throws(() => context.getJlightApiBaseUrl(), /cannot use the staging backend/);
  context.window.JLIGHT_API_BASE_URL = 'https://approved-api.example.org';
  assert.equal(context.getJlightApiBaseUrl(), 'https://approved-api.example.org');
}

(async () => {
  for (const [name, next] of [
    ['requestJlightIntelligenceSummary', 'async function requestJlightClinicalTrialsSummary'],
    ['requestJlightClinicalTrialsSummary', '\nasync function ']
  ]) {
    const start = html.indexOf('async function ' + name + '(');
    const end = html.indexOf(next, start + 15);
    assert(end > start);
    const testContext = vm.createContext({
      window: {}, URL, STATE: {role: 'Hospital', labOrders: [], results: []},
      getSupabase: () => ({auth: {getSession: async () => ({data: {session: {access_token: 'synthetic'}}})}}),
      fetch: () => { throw new Error('Network must not be called without configuration'); }
    });
    vm.runInContext(helper + '\n' + html.slice(start, end), testContext);
    const result = await testContext[name]({id: 'synthetic'}, []);
    assert.equal(result.success, false);
    assert.match(result.message, /configuration is missing/);
  }
  const preview = {innerHTML: ''};
  const offline = vm.createContext({
    TB_PROFILER_IMPORT_PREVIEW: [{id: 'synthetic-result'}], TB_PROFILER_IMPORT_NAME: 'synthetic.json',
    document: {getElementById: () => preview}, MODE: {isOnline: false},
    STATE: {bioRuns: [], orgId: 'synthetic-org', role: 'Bioinformatics'},
    BIORUN_KEY: 'synthetic', jlightStorageKey: key => key,
    localStorage: {setItem: () => {}}, requirePermission: () => true,
    audit: () => { throw new Error('Offline import must not claim persistence'); },
    toast: () => {}, window: {}
  });
  const importStart = html.indexOf('async function commitTBProfilerJson()');
  vm.runInContext(html.slice(importStart, html.indexOf('async function retryTBProfilerCloudSync', importStart)), offline);
  await offline.commitTBProfilerJson();
  assert.equal(offline.STATE.bioRuns.length, 1);
  assert.match(preview.innerHTML, /Saved on this device only/);
  assert(!preview.innerHTML.includes('Workspace sync confirmed'));
  // A generic jl_entries write is not proof of canonical Bioinformatics persistence.
  const online = vm.createContext({
    TB_PROFILER_IMPORT_PREVIEW: [{id: 'synthetic-result'}],
    TB_PROFILER_IMPORT_NAME: 'synthetic.json',
    document: {getElementById: id => id === 'tb-profiler-preview' ? preview : null},
    MODE: {isOnline: true, organisationId: 'synthetic-org'},
    STATE: {bioRuns: [], orgId: 'synthetic-org', role: 'Bioinformatics'},
    getSupabase: () => ({rpc: async () => ({data: true})}),
    BIORUN_KEY: 'synthetic', jlightStorageKey: key => key,
    localStorage: {setItem: () => {}}, window: {},
    audit: () => {}, toast: () => {}, renderDashboard: () => {}, esc: String,
    persistTBProfilerCanonicalRecords: async () => ({ok: true}),
    syncDomainToBackend: async () => ({ok: true})
  });
  vm.runInContext(html.slice(importStart, html.indexOf('function hydrateTBProfilerRecord', importStart)), online);
  await online.commitTBProfilerJson();
  assert.match(preview.innerHTML, /Canonical save acknowledged/);
  assert.match(preview.innerHTML, /Independent retrieval, full evidence readback and patient linking are not verified/);
  assert(!preview.innerHTML.includes('Workspace sync confirmed'));
  online.window._tbProfilerPendingSync = [{id: 'synthetic-result'}];
  await online.retryTBProfilerCloudSync();
  assert.match(preview.innerHTML, /not an authoritative patient result/);
  assert(!preview.innerHTML.includes('Cloud sync confirmed'));
  online.syncDomainToBackend = async () => ({ok: false, reason: 'synthetic failure'});
  online.window._tbProfilerPendingSync = [{id: 'synthetic-result'}];
  await online.retryTBProfilerCloudSync();
  assert.equal(online.window._tbProfilerPendingSync.length, 1);
  online.persistTBProfilerCanonicalRecords = async () => ({ok: false, reason: 'synthetic canonical failure'});
  online.syncDomainToBackend = async () => { throw new Error('Generic copy must not substitute for a canonical failure'); };
  online.TB_PROFILER_IMPORT_PREVIEW = [{id: 'synthetic-second-result'}];
  await online.commitTBProfilerJson();
  assert.match(preview.innerHTML, /synthetic canonical failure/);
  assert.equal(online.window._tbProfilerPendingSync.length, 1);
  const report = html.slice(html.indexOf('function generateTBProfilerGenomicReport()'), html.indexOf('function setBioinformaticsTBTab'));
  assert(report.includes('not an authoritative patient analysis report'));
  assert(report.includes("['Pipeline version',r.pipelineVersion"));
  assert(report.includes("['Database version',r.databaseVersion"));
  assert(report.includes('Absence of a drug or mutation is not proof of susceptibility'));
  // Synthetic frontend contract tests: no network or live persistence is claimed.
  const canonicalSource = html.slice(html.indexOf('async function jlightCanonicalApiRequest('), importStart);
  const orgId = '00000000-0000-4000-8000-000000000088';
  const runId = '00000000-0000-4000-8000-000000000076';
  const accessionId = '00000000-0000-4000-8000-000000000077';
  const calls = [];
  const canonicalContext = vm.createContext({
    window: {JLIGHT_API_BASE_URL: 'https://synthetic-api.example.org'}, URL,
    STATE: {orgId}, MODE: {isOnline: true, organisationType: 'bioinformatics'},
    getSupabase: () => ({auth: {getSession: async () => ({data: {session: {access_token: 'synthetic-test-token'}}})}}),
    hydrateTBProfilerRecord: x => x,
    fetch: async (url, options) => {
      calls.push({url, options});
      return {ok: true, status: 200, json: async () => ({success: true,
        canonical_run_id: runId, canonical_accession_id: accessionId,
        run: {id: runId, accession_id: accessionId, run_id: 'SYNTH-RUN-001'}})};
    }
  });
  vm.runInContext(helper + '\n' + canonicalSource, canonicalContext);
  const makeRecord = () => ({orgId, sampleId: 'SYNTH-RUN-001', patientId: 'must-not-be-inferred',
    tbProfiler: {qc: {medianDepth: 44, meanDepth: 46}, resistanceEvidence: []}});
  const record = makeRecord();
  assert.equal((await canonicalContext.persistTBProfilerCanonicalRecords([record])).ok, true);
  assert.equal(record.canonicalRunId, runId);
  assert.equal(record.patientLinkStatus, undefined);
  assert.equal(calls[0].url, 'https://synthetic-api.example.org/api/bioinformatics/runs/upsert');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer synthetic-test-token');
  assert.equal(calls[0].options.headers['X-JLIGHT-Organisation'], orgId);
  assert.equal(calls[0].options.headers['X-JLIGHT-Workspace'], 'bioinformatics');
  const payload = JSON.parse(calls[0].options.body);
  assert.equal(payload.patient_id, undefined);
  assert.equal(payload.qc.coverageMean, 46);
  canonicalContext.MODE.organisationType = 'clinical_trials';
  assert.equal((await canonicalContext.persistTBProfilerCanonicalRecords([makeRecord()])).ok, false);
  assert.equal(calls.length, 1);
  canonicalContext.MODE.organisationType = 'bioinformatics';
  assert.equal((await canonicalContext.persistTBProfilerCanonicalRecords([{...makeRecord(), orgId: 'other-org'}])).ok, false);
  assert.equal(calls.length, 1);
  for (const status of [401, 403, 409, 503]) {
    canonicalContext.fetch = async () => ({ok: false, status, json: async () => ({success: false})});
    const rejected = makeRecord();
    assert.equal((await canonicalContext.persistTBProfilerCanonicalRecords([rejected])).ok, false);
    assert.equal(rejected.canonicalRunId, undefined);
  }
  canonicalContext.fetch = async () => ({ok: true, status: 200, json: async () => ({success: true})});
  assert.equal((await canonicalContext.persistTBProfilerCanonicalRecords([makeRecord()])).ok, false);
  canonicalContext.getSupabase = () => ({auth: {getSession: async () => ({data: {session: null}})}});
  canonicalContext.fetch = async () => { throw new Error('Unauthenticated requests must not reach the network'); };
  assert.equal((await canonicalContext.persistTBProfilerCanonicalRecords([makeRecord()])).ok, false);
  console.log('PASS: API URL validation, legacy configuration, fail-closed request paths, honest offline/generic-copy status, retry failure retention, and local report provenance');
})().catch(error => { console.error(error); process.exitCode = 1; });
