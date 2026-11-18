// Public routing configuration only. No credentials belong in this file.
// Production hosts bind the approved production API. Every other Netlify host
// (PR previews, branch deploys) is a staging context and binds the staging API.
// Unlisted hosts (localhost, other domains) stay unbound: the app fails closed
// unless explicit configuration (JLIGHT_CONFIG.apiBaseUrl) is supplied.
(() => {
  const hostname = window.location.hostname.toLowerCase();
  const production = ['jlight-health.co.za', 'www.jlight-health.co.za',
    'jlight-health.netlify.app', 'main--jlight-health.netlify.app'];
  if (production.includes(hostname)) {
    window.JLIGHT_CONFIG = {
      ...(window.JLIGHT_CONFIG || {}),
      apiBaseUrl: 'https://jlight-backend.onrender.com'
    };
  } else if (hostname.endsWith('.netlify.app')) {
    window.JLIGHT_CONFIG = {
      ...(window.JLIGHT_CONFIG || {}),
      apiBaseUrl: 'https://jlight-backend-staging.onrender.com'
    };
  }
})();
