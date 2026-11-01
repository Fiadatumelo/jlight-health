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
const attempts = new Map<string, number[]>();
function rateLimited(key: string, now = Date.now()) {
  const recent = (attempts.get(key) ?? []).filter((ts) => now - ts < 15 * 60 * 1000);
  if (recent.length >= 5) { attempts.set(key, recent); return true; }
  recent.push(now); attempts.set(key, recent); return false;
}

Deno.serve(async (req: Request) => {
  const origin = (req.headers.get("origin") ?? "").replace(/\/$/, "");
  if (req.method === "OPTIONS") {
    if (!allowed(origin)) return new Response("Forbidden origin", { status: 403 });
    return new Response("ok", { headers: corsHeaders(origin) });
  }
  if (!allowed(origin)) return json({ error: "Origin not allowed" }, 403, origin);
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, origin);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("JLIGHT_SERVICE_ROLE_KEY") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !anonKey || !serviceRoleKey) return json({ error: "Password recovery is not configured" }, 503, origin);

  let email = "";
  try {
    const body = await req.json();
    email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  } catch { return json({ error: "Request body must be valid JSON" }, 400, origin); }
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "Enter a valid email address" }, 400, origin);
  const clientIp = req.headers.get("cf-connecting-ip") ?? req.headers.get("x-real-ip") ?? "unknown";
  if (rateLimited(clientIp)) return json({ error: "Too many reset requests. Wait 15 minutes and try again." }, 429, origin);

  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data, error } = await admin.auth.admin.generateLink({
    type: "recovery", email, options: { redirectTo: origin + "/?type=recovery" },
  });
  if (error) {
    const code = (error as { code?: string }).code ?? "";
    if (code === "user_not_found") return json({ success: true, message: "If an account exists for that address, a reset email has been requested." }, 200, origin);
    console.error("[send-password-reset] Recovery link generation failed", code || "unclassified");
    return json({ error: "Password recovery is temporarily unavailable. Please try again later." }, 503, origin);
  }
  const actionLink = data?.properties?.action_link;
  if (!actionLink) return json({ error: "Password recovery is temporarily unavailable. Please try again later." }, 503, origin);

  try {
    await sendMailbuxMessage({
      to: email,
      subject: "Reset your JLIGHT password",
      text: [
        "We received a request to reset the password for your JLIGHT account.",
        "",
        "Use this secure, one-time link to choose a new password:",
        actionLink,
        "",
        "If you did not request this, ignore this email. Never share your recovery link.",
      ].join("\n"),
    });
  } catch (err) {
    console.error("[send-password-reset] Mailbux delivery failed", err instanceof Error ? err.message : "unknown");
    // Keep the public response generic to prevent account enumeration.
    return json({ success: true, message: "If an account exists for that address, a reset email has been requested." }, 200, origin);
  }
  return json({ success: true, message: "If an account exists for that address, a reset email has been requested." }, 200, origin);
});
