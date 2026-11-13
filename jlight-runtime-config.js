// Public routing configuration only. No credentials belong in this file.
(() => {
  const hostname = window.location.hostname.toLowerCase();
  // Explicitly bind the existing PR #96 preview to the approved staging API.
  // Use the separately approved production API on known production hosts.
  if (hostname === 'deploy-preview-96--jlight-health.netlify.app') {
    window.JLIGHT_CONFIG = {
      ...(window.JLIGHT_CONFIG || {}),
      apiBaseUrl: 'https://jlight-backend-staging.onrender.com'
    };
  } else if (['jlight-health.co.za', 'www.jlight-health.co.za'].includes(hostname)) {
    window.JLIGHT_CONFIG = {
      ...(window.JLIGHT_CONFIG || {}),
      apiBaseUrl: 'https://jlight-backend.onrender.com'
    };
  }
})();
