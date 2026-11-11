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
  console.log('PASS: API URL validation, legacy configuration, fail-closed request paths, and honest offline import status');
})().catch(error => { console.error(error); process.exitCode = 1; });
