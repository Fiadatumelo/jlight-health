import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const siteUrl = (Deno.env.get("JLIGHT_SITE_URL") ?? "https://jlight-health.co.za").replace(/\/$/, "");
const allowedOrigins = new Set((Deno.env.get("ALLOWED_ORIGINS") ?? (siteUrl + ";https://deploy-preview-11--jlight-health.netlify.app"))
  .split(";").map((x) => x.trim().replace(/\/$/, "")).filter(Boolean));

const corsHeaders = (origin: string) => ({
  "Access-Control-Allow-Origin": allowedOrigins.has(origin) ? origin : "null",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Max-Age": "86400",
  "Vary": "Origin",
});
const json = (body: unknown, status = 200, origin = "") =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(origin), "Content-Type": "application/json", "Cache-Control": "no-store", "Pragma": "no-cache" },
  });
const escapeHtml = (value: string) =>
  value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);

// Best-effort per-isolate throttling. Configure upstream abuse controls/CAPTCHA
// before public launch; this in-memory guard is not a distributed rate limiter.
const attempts = new Map<string, number[]>();
function rateLimited(key: string, now = Date.now()) {
  const recent = (attempts.get(key) ?? []).filter((ts) => now - ts < 15 * 60 * 1000);
  if (recent.length >= 5) {
    attempts.set(key, recent);
    return true;
  }
  recent.push(now);
  attempts.set(key, recent);
  return false;
}

Deno.serve(async (req: Request) => {
  const origin = (req.headers.get("origin") ?? "").replace(/\/$/, "");
  if (req.method === "OPTIONS") {
    if (!allowedOrigins.has(origin)) return new Response("Forbidden origin", { status: 403 });
    return new Response("ok", { headers: corsHeaders(origin) });
  }
  if (!allowedOrigins.has(origin)) return json({ error: "Origin not allowed" }, 403, origin);
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, origin);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const resendApiKey = Deno.env.get("RESEND_API_KEY");
  const fromEmail = Deno.env.get("JLIGHT_FROM_EMAIL");
  if (!supabaseUrl || !anonKey || !serviceRoleKey) return json({ error: "Password recovery is not configured" }, 503, origin);
  if (!resendApiKey || !fromEmail) {
    return json({ error: "Password-recovery email delivery is not configured. Configure RESEND_API_KEY and JLIGHT_FROM_EMAIL in Supabase Edge Function secrets." }, 503, origin);
  }

  let email = "";
  try {
    const body = await req.json();
    email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  } catch {
    return json({ error: "Request body must be valid JSON" }, 400, origin);
  }
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return json({ error: "Enter a valid email address" }, 400, origin);
  }
  const clientIp = req.headers.get("cf-connecting-ip") ?? req.headers.get("x-real-ip") ?? "unknown";
  if (rateLimited(clientIp)) {
    return json({ error: "Too many reset requests. Wait 15 minutes and try again." }, 429, origin);
  }

  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // Generic response for unknown addresses prevents account enumeration.
  const { data, error } = await admin.auth.admin.generateLink({
    type: "recovery",
    email,
    options: { redirectTo: origin + "/?type=recovery" },
  });
  if (error || !data?.properties?.action_link) {
    console.warn("[send-password-reset] Recovery link unavailable; returning generic response.");
    return json({ success: true, message: "If an account exists for that address, a reset email has been requested." }, 200, origin);
  }

  const actionLink = data.properties.action_link;
  const html = `<!doctype html><html><body style="font-family:Arial,sans-serif;color:#172033;line-height:1.6"><h2>Reset your JLIGHT password</h2><p>We received a request to reset the password for your JLIGHT account.</p><p><a href="${escapeHtml(actionLink)}" style="display:inline-block;background:#087f8c;color:#fff;text-decoration:none;padding:12px 20px;border-radius:6px">Choose a new password</a></p><p>If the button does not work, copy this link into your browser:</p><p style="word-break:break-all">${escapeHtml(actionLink)}</p><p>If you did not request this, ignore this email. Do not share this link with anyone.</p></body></html>`;
  const mail = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${resendApiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: fromEmail,
      to: [email],
      subject: "Reset your JLIGHT password",
      html,
      text: `Reset your JLIGHT password using this one-time link: ${actionLink}\n\nIf you did not request this, ignore this email.`,
    }),
  });
  if (!mail.ok) {
    const details = await mail.text();
    console.error("[send-password-reset] Email provider rejected message", mail.status, details.slice(0, 300));
    return json({ error: "The email service could not send your reset link. Please try again later." }, 502, origin);
  }
  return json({ success: true, message: "If an account exists for that address, a reset email has been requested." }, 200, origin);
});
