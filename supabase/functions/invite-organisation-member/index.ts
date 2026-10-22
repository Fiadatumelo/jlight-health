import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = (origin: string, allowed: Set<string>) => ({
  "Access-Control-Allow-Origin": allowed.has(origin) ? origin : "null",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Vary": "Origin",
});

const json = (body: unknown, status: number, headers: Record<string, string>) =>
  new Response(JSON.stringify(body), { status, headers: { ...headers, "Content-Type": "application/json", "Cache-Control": "no-store" } });

Deno.serve(async (req) => {
  const allowedOrigins = new Set((Deno.env.get("ALLOWED_ORIGINS") ?? "")
    .split(";").map((x) => x.trim()).filter(Boolean));
  const origin = req.headers.get("origin") ?? "";
  const headers = corsHeaders(origin, allowedOrigins);

  if (req.method === "OPTIONS") {
    if (!allowedOrigins.has(origin)) return new Response("Forbidden origin", { status: 403 });
    return new Response("ok", { headers });
  }
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, headers);
  if (!allowedOrigins.has(origin)) return json({ error: "Origin not allowed" }, 403, headers);

  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return json({ error: "Sign in is required" }, 401, headers);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const redirectTo = Deno.env.get("INVITE_REDIRECT_URL");
  if (!supabaseUrl || !anonKey || !serviceRoleKey || !redirectTo) {
    return json({ error: "Invitation service is not configured" }, 503, headers);
  }

  const userClient = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const adminClient = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: authData, error: authError } = await userClient.auth.getUser();
  if (authError || !authData.user) return json({ error: "Session is invalid or expired" }, 401, headers);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "Request body must be valid JSON" }, 400, headers);
  }
  const organisationId = typeof body.organisation_id === "string" ? body.organisation_id : "";
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const role = typeof body.access_role === "string" ? body.access_role : "";
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const allowedRoles = new Set(["hospital", "laboratory", "bioinformatics", "clinical_trial", "reviewer", "read_only", "org_admin"]);
  if (!uuidPattern.test(organisationId) || email.length > 254 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
      !allowedRoles.has(role)) {
    return json({ error: "Organisation, email or role is invalid" }, 400, headers);
  }

  const { data: callerMembership, error: membershipError } = await adminClient
    .from("jl_org_memberships")
    .select("access_role,status")
    .eq("organisation_id", organisationId)
    .eq("user_id", authData.user.id)
    .maybeSingle();

  if (membershipError) return json({ error: "Could not verify organisation permissions" }, 500, headers);
  if (!callerMembership || callerMembership.status !== "active" ||
      !["owner", "org_admin"].includes(callerMembership.access_role)) {
    return json({ error: "You are not authorised to invite members to this organisation" }, 403, headers);
  }
  if (role === "org_admin" && callerMembership.access_role !== "owner") {
    return json({ error: "Only an organisation owner can appoint an organisation administrator" }, 403, headers);
  }

  const { data: inviteData, error: inviteError } = await adminClient.auth.admin.inviteUserByEmail(email, { redirectTo });
  if (inviteError || !inviteData.user) {
    // Do not return provider details that could disclose whether an account exists.
    return json({ error: "Invitation could not be sent. Check the address and try again." }, 400, headers);
  }

  const { error: insertError } = await adminClient.from("jl_org_memberships").insert({
    organisation_id: organisationId,
    user_id: inviteData.user.id,
    access_role: role,
    status: "active",
    created_by: authData.user.id,
  });

  if (insertError) {
    // The invite may have been sent, but membership is not granted on failure.
    console.error("Membership provisioning failed after invite; inspect server logs.", insertError.code);
    return json({ error: "Invitation was sent, but access provisioning needs administrator attention. Do not resend repeatedly." }, 502, headers);
  }

  return json({ ok: true, message: "Invitation sent. Access is limited to the selected organisation role." }, 200, headers);
});
