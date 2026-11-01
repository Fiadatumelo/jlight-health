import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { sendMailbuxMessage } from "../_shared/mailbux.ts";

const siteUrl = (Deno.env.get("JLIGHT_SITE_URL") ?? "https://jlight-health.co.za").replace(/\/$/, "");
const allowedOrigins = new Set((Deno.env.get("ALLOWED_ORIGINS") ?? siteUrl + ";https://www.jlight-health.co.za")
  .split(";").map((x) => x.trim().replace(/\/$/, "")).filter(Boolean));
const allowed = (origin: string) => allowedOrigins.has(origin) || /^https:\/\/deploy-preview-\d+--jlight-health\.netlify\.app$/.test(origin);
const corsHeaders = (origin: string) => ({
  "Access-Control-Allow-Origin": allowed(origin) ? origin : "null",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Max-Age": "86400",
  "Vary": "Origin",
});
const json = (body: unknown, status = 200, origin = "") =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders(origin), "Content-Type": "application/json", "Cache-Control": "no-store", "Pragma": "no-cache" } });

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin") ?? "";
  if (req.method === "OPTIONS") {
    if (!allowed(origin)) return new Response("Forbidden origin", { status: 403 });
    return new Response("ok", { headers: corsHeaders(origin) });
  }
  if (!allowed(origin)) return json({ error: "Origin not allowed" }, 403, origin);
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, origin);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !anonKey || !serviceRoleKey) return json({ error: "Organisation-code service is not configured" }, 503, origin);
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return json({ error: "Sign in is required" }, 401, origin);

  const userClient = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data: authData, error: authError } = await userClient.auth.getUser();
  const user = authData?.user;
  if (authError || !user?.id || !user.email) return json({ error: "Session is invalid or expired" }, 401, origin);

  let body: { organisation_id?: unknown };
  try { body = await req.json(); } catch { return json({ error: "Request body must be valid JSON" }, 400, origin); }
  const organisationId = typeof body.organisation_id === "string" ? body.organisation_id : "";
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuidPattern.test(organisationId)) return json({ error: "Organisation is invalid" }, 400, origin);

  const { data: org, error: orgError } = await admin.from("jl_organisations")
    .select("id,name,org_code,owner_user_id")
    .eq("id", organisationId).eq("owner_user_id", user.id).maybeSingle();
  if (orgError) return json({ error: "Could not verify organisation ownership" }, 500, origin);
  if (!org?.org_code) return json({ error: "Only the organisation owner can request this code" }, 403, origin);

  try {
    await sendMailbuxMessage({
      to: user.email,
      subject: "Your JLIGHT organisation code — " + String(org.name ?? "JLIGHT workspace"),
      text: [
        "Your JLIGHT organisation code for " + String(org.name ?? "JLIGHT workspace") + " is:",
        "",
        String(org.org_code),
        "",
        "Share this code only with authorised colleagues. The code is an identifier, not a substitute for an invitation or account permissions.",
        "",
        "If you did not request this message, ignore it.",
      ].join("\n"),
    });
  } catch (err) {
    console.error("[send-organisation-code] Mailbux delivery failed", err instanceof Error ? err.message : "unknown");
    return json({ error: "Mailbux could not send the organisation code. Please try again later." }, 502, origin);
  }
  return json({ success: true, email_sent: true, sent_to: user.email }, 200, origin);
});
