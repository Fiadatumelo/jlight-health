import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const siteUrl = (Deno.env.get("JLIGHT_SITE_URL") ?? "https://jlight-health.co.za").replace(/\/$/, "");
const allowedOrigins = new Set((Deno.env.get("ALLOWED_ORIGINS") ?? (siteUrl + ";https://www.jlight-health.co.za;https://deploy-preview-33--jlight-health.netlify.app"))
  .split(";").map((x) => x.trim().replace(/\/$/, "")).filter(Boolean));

const isAllowedOrigin = (origin: string) => allowedOrigins.has(origin) || /^https:\/\/deploy-preview-\\d+--jlight-health\\.netlify\\.app$/.test(origin);
const corsHeaders = (origin: string) => ({
  "Access-Control-Allow-Origin": isAllowedOrigin(origin) ? origin : "null",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Max-Age": "86400",
  "Vary": "Origin",
});

const json = (body: unknown, status = 200, origin = "") =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders(origin),
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "Pragma": "no-cache",
    },
  });

const escapeHtml = (value: string) =>
  value.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c] ?? c);

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin") ?? "";
  if (req.method === "OPTIONS") {
    if (!isAllowedOrigin(origin)) return new Response("Forbidden origin", { status: 403 });
    return new Response("ok", { headers: corsHeaders(origin) });
  }
  if (!isAllowedOrigin(origin)) return json({ error: "Origin not allowed" }, 403, origin);
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, origin);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const resendApiKey = Deno.env.get("RESEND_API_KEY");
  const fromEmail = Deno.env.get("JLIGHT_FROM_EMAIL");

  if (!supabaseUrl || !anonKey || !serviceRoleKey) {
    return json({ error: "Organisation-code service is not configured" }, 503, origin);
  }
  if (!resendApiKey || !fromEmail) {
    return json({
      error: "Organisation-code email is not configured. Configure RESEND_API_KEY and JLIGHT_FROM_EMAIL in Supabase Edge Function secrets.",
      code_available_in_app: true,
    }, 503, origin);
  }

  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return json({ error: "Sign in is required" }, 401, origin);

  const userClient = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const adminClient = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: authData, error: authError } = await userClient.auth.getUser();
  const user = authData?.user;
  if (authError || !user?.id || !user.email) return json({ error: "Session is invalid or expired" }, 401, origin);

  let body: { organisation_id?: unknown };
  try {
    body = await req.json();
  } catch {
    return json({ error: "Request body must be valid JSON" }, 400, origin);
  }
  const organisationId = typeof body.organisation_id === "string" ? body.organisation_id : "";
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuidPattern.test(organisationId)) return json({ error: "Organisation is invalid" }, 400, origin);

  // Only the verified organisation owner can request delivery of its code.
  const { data: org, error: orgError } = await adminClient
    .from("jl_organisations")
    .select("id,name,org_code,owner_user_id")
    .eq("id", organisationId)
    .eq("owner_user_id", user.id)
    .maybeSingle();

  if (orgError) return json({ error: "Could not verify organisation ownership" }, 500, origin);
  if (!org?.org_code) return json({ error: "Only the organisation owner can request this code" }, 403, origin);

  const name = String(org.name ?? "JLIGHT workspace");
  const code = String(org.org_code);
  const safeName = escapeHtml(name);
  const safeCode = escapeHtml(code);

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${resendApiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: fromEmail,
      to: [user.email],
      subject: `Your JLIGHT organisation code — ${name}`,
      text: `Your JLIGHT organisation code for ${name} is: ${code}\n\nShare this code only with authorised colleagues. The code is an identifier, not a substitute for an invitation or account permissions.\n\nIf you did not request this message, you can ignore it.`,
      html: `<!doctype html><html><body style="font-family:Arial,sans-serif;color:#172033"><h2>JLIGHT organisation code</h2><p>Your organisation code for <strong>${safeName}</strong> is:</p><p style="font-size:24px;font-weight:700;letter-spacing:2px">${safeCode}</p><p>Share this code only with authorised colleagues. The code is an identifier, not a substitute for an invitation or account permissions.</p><p>If you did not request this message, you can ignore it.</p></body></html>`,
    }),
  });

  if (!response.ok) {
    const details = await response.text();
    console.error("[send-organisation-code] provider rejected message", response.status, details.slice(0, 300));
    return json({ error: "Email provider could not send the organisation code. The code remains available in JLIGHT." }, 502, origin);
  }

  return json({ success: true, sent_to: user.email }, 200, origin);
});
