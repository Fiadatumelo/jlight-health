import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { sendMailbuxMessage } from "../_shared/mailbux.ts";

const allowedOrigins = new Set((Deno.env.get("ALLOWED_ORIGINS") ?? "https://jlight-health.co.za;https://www.jlight-health.co.za")
  .split(";").map((x) => x.trim().replace(/\/$/, "")).filter(Boolean));
const isAllowedOrigin = (origin: string) => allowedOrigins.has(origin) || /^https:\/\/deploy-preview-\d+--jlight-health\.netlify\.app$/.test(origin);
const headers = (origin: string) => ({
  "Access-Control-Allow-Origin": isAllowedOrigin(origin) ? origin : "null",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Vary": "Origin",
});
const json = (body: unknown, status: number, origin: string) =>
  new Response(JSON.stringify(body), { status, headers: { ...headers(origin), "Content-Type": "application/json", "Cache-Control": "no-store" } });

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin") ?? "";
  const cors = headers(origin);
  if (req.method === "OPTIONS") {
    if (!isAllowedOrigin(origin)) return new Response("Forbidden origin", { status: 403 });
    return new Response("ok", { headers: cors });
  }
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, origin);
  if (!isAllowedOrigin(origin)) return json({ error: "Origin not allowed" }, 403, origin);
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return json({ error: "Sign in is required" }, 401, origin);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const redirectTo = Deno.env.get("INVITE_REDIRECT_URL") ?? "https://jlight-health.co.za/";
  if (!supabaseUrl || !anonKey || !serviceRoleKey) return json({ error: "Invitation service is not configured" }, 503, origin);

  const userClient = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data: authData, error: authError } = await userClient.auth.getUser();
  if (authError || !authData.user) return json({ error: "Session is invalid or expired" }, 401, origin);

  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return json({ error: "Request body must be valid JSON" }, 400, origin); }
  const organisationId = typeof body.organisation_id === "string" ? body.organisation_id : "";
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const role = typeof body.access_role === "string" ? body.access_role : "";
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const roles = new Set(["hospital", "laboratory", "bioinformatics", "reviewer", "read_only", "org_admin"]);
  if (!uuidPattern.test(organisationId) || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !roles.has(role)) {
    return json({ error: "Organisation, email or role is invalid" }, 400, origin);
  }

  const { data: memberships, error: membershipError } = await admin.from("jl_org_memberships")
    .select("access_role,status").eq("organisation_id", organisationId)
    .eq("user_id", authData.user.id).eq("status", "active");
  if (membershipError) return json({ error: "Could not verify organisation permissions" }, 500, origin);
  const callerRoles = (memberships ?? []).map((m: { access_role: string }) => m.access_role);
  if (!callerRoles.some((r: string) => ["owner", "org_admin"].includes(r))) {
    return json({ error: "You are not authorised to invite members to this organisation" }, 403, origin);
  }
  if (role === "org_admin" && !callerRoles.includes("owner")) {
    return json({ error: "Only an organisation owner can appoint an organisation administrator" }, 403, origin);
  }

  const { data: inviteData, error: inviteError } = await admin.auth.admin.generateLink({
    type: "invite", email, options: { redirectTo },
  });
  if (inviteError || !inviteData?.properties?.action_link || !inviteData.user?.id) {
    return json({ error: "Invitation could not be prepared. Check the address and try again." }, 400, origin);
  }
  try {
    await sendMailbuxMessage({
      to: email,
      subject: "You have been invited to JLIGHT",
      text: [
        "You have been invited to join a JLIGHT organisation workspace.",
        "",
        "Accept your invitation using this secure link:",
        inviteData.properties.action_link,
        "",
        "Your access is limited to the organisation and role assigned by its administrator.",
        "If you were not expecting this invitation, you can ignore this email.",
      ].join("\n"),
    });
  } catch (err) {
    console.error("[invite-organisation-member] Mailbux delivery failed", err instanceof Error ? err.message : "unknown");
    return json({ error: "The invitation link was created but could not be emailed. Ask an administrator to retry; no workspace membership was granted." }, 502, origin);
  }

  const { error: insertError } = await admin.from("jl_org_memberships").insert({
    organisation_id: organisationId,
    user_id: inviteData.user.id,
    access_role: role,
    status: "invited",
    created_by: authData.user.id,
  });
  if (insertError) {
    console.error("[invite-organisation-member] Membership provisioning failed", insertError.code);
    return json({ error: "The invitation email was sent, but access provisioning needs administrator attention. Do not resend repeatedly." }, 502, origin);
  }
  return json({ ok: true, message: "Invitation sent. Access is limited to the selected organisation role." }, 200, origin);
});
