import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const siteUrl = (Deno.env.get("JLIGHT_SITE_URL") ?? "https://jlight-health.co.za").replace(/\/$/, "");
const allowedOrigins = new Set((Deno.env.get("ALLOWED_ORIGINS") ?? siteUrl + ";https://www.jlight-health.co.za")
  .split(";").map((x) => x.trim().replace(/\/$/, "")).filter(Boolean));
const allowed = (origin: string) => allowedOrigins.has(origin) || /^https:\/\/deploy-preview-\d+--jlight-health\.netlify\.app$/.test(origin);
const headers = (origin: string) => ({ "Access-Control-Allow-Origin": allowed(origin) ? origin : "null", "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info", "Access-Control-Allow-Methods": "POST, OPTIONS", "Vary": "Origin" });
const json = (body: unknown, status = 200, origin = "") => new Response(JSON.stringify(body), { status, headers: { ...headers(origin), "Content-Type": "application/json", "Cache-Control": "no-store" } });

async function sendMail(to: string, subject: string, text: string) {
  const mailbox = Deno.env.get("MAILBUX_EMAIL")?.trim();
  const password = Deno.env.get("MAILBUX_APP_PASSWORD");
  if (!mailbox || !password) throw new Error("Mailbux credentials are not configured");
  const auth = "Basic " + btoa(unescape(encodeURIComponent(mailbox + ":" + password)));
  const sessionResponse = await fetch("https://my.mailbux.com/jmap/", { headers: { Authorization: auth, Accept: "application/json" } });
  if (!sessionResponse.ok) throw new Error("Mailbux session discovery failed: " + sessionResponse.status);
  const session = await sessionResponse.json();
  const accountId = session?.primaryAccounts?.["urn:ietf:params:jmap:mail"];
  const apiUrl = session?.apiUrl;
  if (typeof accountId !== "string" || typeof apiUrl !== "string") throw new Error("Mailbux JMAP session is incomplete");
  const core = "urn:ietf:params:jmap:core", mail = "urn:ietf:params:jmap:mail", submission = "urn:ietf:params:jmap:submission";
  const post = async (methodCalls: unknown[][]) => {
    const response = await fetch(apiUrl, { method: "POST", headers: { Authorization: auth, "Content-Type": "application/json" }, body: JSON.stringify({ using: [core, mail, submission], methodCalls }) });
    if (!response.ok) throw new Error("Mailbux JMAP API failed: " + response.status);
    const data = await response.json();
    if (!Array.isArray(data.methodResponses)) throw new Error("Invalid Mailbux JMAP response");
    for (const item of data.methodResponses) if (item?.[0] === "error") throw new Error("Mailbux JMAP method rejected: " + String(item?.[1]?.type ?? "unknown"));
    return data.methodResponses;
  };
  const meta = await post([["Mailbox/get", { accountId }, "m"], ["Identity/get", { accountId }, "i"]]);
  const mailboxes = meta.find((x: any[]) => x?.[0] === "Mailbox/get")?.[1]?.list ?? [];
  const identities = meta.find((x: any[]) => x?.[0] === "Identity/get")?.[1]?.list ?? [];
  const drafts = mailboxes.find((x: any) => x.role === "drafts");
  const identity = identities.find((x: any) => x.email?.toLowerCase() === mailbox.toLowerCase()) ?? identities[0];
  if (!drafts?.id || !identity?.id) throw new Error("Mailbux drafts mailbox or sending identity is unavailable");
  const recipient = to.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient) || recipient.length > 254) throw new Error("Invalid recipient");
  const cleanSubject = subject.replace(/[\r\n]+/g, " ").trim().slice(0, 200);
  if (!cleanSubject || text.length > 100000) throw new Error("Invalid message content");
  const sent = await post([
    ["Email/set", { accountId, create: { draft: { mailboxIds: { [drafts.id]: true }, from: [{ email: mailbox }], to: [{ email: recipient }], subject: cleanSubject, textBody: [{ type: "text/plain", value: text }] } } }, "email"],
    ["EmailSubmission/set", { accountId, create: { submission: { identityId: identity.id, emailId: "#draft", envelope: { mailFrom: { email: mailbox }, rcptTo: [{ email: recipient }] } } } }, "submission"],
  ]);
  const created = sent.find((x: any[]) => x?.[0] === "Email/set")?.[1]?.created?.draft;
  const submitted = sent.find((x: any[]) => x?.[0] === "EmailSubmission/set")?.[1]?.created?.submission;
  if (!created?.id || !submitted) throw new Error("Mailbux did not confirm delivery submission");
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin") ?? "";
  if (req.method === "OPTIONS") return allowed(origin) ? new Response("ok", { headers: headers(origin) }) : new Response("Forbidden origin", { status: 403 });
  if (!allowed(origin)) return json({ error: "Origin not allowed" }, 403, origin);
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405, origin);
  const supabaseUrl = Deno.env.get("SUPABASE_URL"), anonKey = Deno.env.get("SUPABASE_ANON_KEY"), serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !anonKey || !serviceRoleKey) return json({ error: "Organisation-code service is not configured" }, 503, origin);
  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) return json({ error: "Sign in is required" }, 401, origin);
  const userClient = createClient(supabaseUrl, anonKey, { global: { headers: { Authorization: authHeader } }, auth: { persistSession: false, autoRefreshToken: false } });
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data, error } = await userClient.auth.getUser();
  const user = data?.user;
  if (error || !user?.id || !user.email) return json({ error: "Session is invalid or expired" }, 401, origin);
  let body: { organisation_id?: unknown };
  try { body = await req.json(); } catch { return json({ error: "Invalid JSON" }, 400, origin); }
  const orgId = typeof body.organisation_id === "string" ? body.organisation_id : "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(orgId)) return json({ error: "Organisation is invalid" }, 400, origin);
  const { data: org, error: orgError } = await admin.from("jl_organisations").select("id,name,org_code,owner_user_id").eq("id", orgId).eq("owner_user_id", user.id).maybeSingle();
  if (orgError) return json({ error: "Could not verify organisation ownership" }, 500, origin);
  if (!org?.org_code) return json({ error: "Only the organisation owner can request this code" }, 403, origin);
  try {
    await sendMail(user.email, "Your JLIGHT organisation code — " + String(org.name ?? "JLIGHT workspace"),
      "Your JLIGHT organisation code for " + String(org.name ?? "JLIGHT workspace") + " is:\n\n" + String(org.org_code) + "\n\nShare this code only with authorised colleagues. This code does not replace an invitation or account permissions.\n\nIf you did not request this message, ignore it.");
  } catch (err) {
    console.error("[send-organisation-code] Mailbux delivery failed", err instanceof Error ? err.message : "unknown");
    return json({ error: "Mailbux could not send the organisation code. Please try again later." }, 502, origin);
  }
  return json({ success: true, email_sent: true, sent_to: user.email }, 200, origin);
});
