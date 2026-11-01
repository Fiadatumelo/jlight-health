export type MailMessage = { to: string; subject: string; text: string };

const SESSION_URL = "https://my.mailbux.com/jmap/";
const CORE = "urn:ietf:params:jmap:core";
const MAIL = "urn:ietf:params:jmap:mail";
const SUBMISSION = "urn:ietf:params:jmap:submission";

export function buildBasicAuth(username: string, password: string): string {
  const bytes = new TextEncoder().encode(username + ":" + password);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return "Basic " + btoa(binary);
}

async function jmapRequest(apiUrl: string, auth: string, methodCalls: unknown[][]) {
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: { Authorization: auth, "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ using: [CORE, MAIL, SUBMISSION], methodCalls }),
  });
  if (!response.ok) throw new Error("Mailbux JMAP request failed (" + response.status + ")");
  const result = await response.json();
  if (!Array.isArray(result.methodResponses)) throw new Error("Mailbux returned an invalid JMAP response");
  for (const item of result.methodResponses) {
    if (item?.[0] === "error") throw new Error("Mailbux JMAP method failed: " + String(item?.[1]?.type ?? "unknown"));
  }
  return result.methodResponses;
}

export async function sendMailbuxMessage(message: MailMessage): Promise<void> {
  const email = Deno.env.get("MAILBUX_EMAIL")?.trim();
  const password = Deno.env.get("MAILBUX_APP_PASSWORD") ?? Deno.env.get("MAILBUX_PASSWORD");
  if (!email || !password) throw new Error("Mailbux mailbox credentials are not configured");
  const auth = buildBasicAuth(email, password);

  const sessionResponse = await fetch(SESSION_URL, { headers: { Authorization: auth, Accept: "application/json" } });
  if (!sessionResponse.ok) throw new Error("Mailbux session discovery failed (" + sessionResponse.status + ")");
  const session = await sessionResponse.json();
  const accountId = session?.primaryAccounts?.[MAIL];
  const apiUrl = session?.apiUrl;
  let parsedApiUrl: URL;
  try { parsedApiUrl = new URL(apiUrl); } catch { throw new Error("Mailbux advertised an invalid JMAP API URL"); }
  if (typeof accountId !== "string" || parsedApiUrl.protocol !== "https:" || parsedApiUrl.hostname !== "my.mailbux.com") {
    throw new Error("Mailbux did not advertise a valid primary mail account and HTTPS API URL");
  }

  const metadata = await jmapRequest(parsedApiUrl.toString(), auth, [
    ["Mailbox/get", { accountId }, "mailboxes"],
    ["Identity/get", { accountId }, "identities"],
  ]);
  const mailboxes = metadata.find((x: any[]) => x?.[0] === "Mailbox/get")?.[1]?.list ?? [];
  const identities = metadata.find((x: any[]) => x?.[0] === "Identity/get")?.[1]?.list ?? [];
  const drafts = mailboxes.find((x: any) => x?.role === "drafts");
  const sent = mailboxes.find((x: any) => x?.role === "sent");
  const identity = identities.find((x: any) => x?.email?.toLowerCase() === email.toLowerCase()) ?? identities[0];
  if (!drafts?.id || !identity?.id) throw new Error("Mailbux drafts mailbox or sending identity is unavailable");

  const recipient = message.to.trim().toLowerCase();
  if (recipient.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) throw new Error("Recipient email address is invalid");
  const subject = message.subject.replace(/[\r\n]+/g, " ").trim().slice(0, 200);
  if (!subject || message.text.length > 100000) throw new Error("Email content is invalid");

  const onSuccessUpdateEmail: Record<string, unknown> = {
    ["mailboxIds/" + drafts.id]: null,
    "keywords/$draft": null,
  };
  if (sent?.id) onSuccessUpdateEmail["mailboxIds/" + sent.id] = true;

  const responses = await jmapRequest(parsedApiUrl.toString(), auth, [
    ["Email/set", {
      accountId,
      create: {
        draft1: {
          mailboxIds: { [drafts.id]: true },
          keywords: { "$draft": true },
          from: [{ email }],
          to: [{ email: recipient }],
          subject,
          textBody: [{ partId: "text1", type: "text/plain" }],
          bodyValues: { text1: { value: message.text } },
        },
      },
    }, "create"],
    ["EmailSubmission/set", {
      accountId,
      create: {
        send1: {
          identityId: identity.id,
          emailId: "#draft1",
          envelope: { mailFrom: { email }, rcptTo: [{ email: recipient }] },
        },
      },
      onSuccessUpdateEmail: { "#send1": onSuccessUpdateEmail },
    }, "submit"],
  ]);
  const created = responses.find((x: any[]) => x?.[0] === "Email/set")?.[1]?.created?.draft1;
  const submitted = responses.find((x: any[]) => x?.[0] === "EmailSubmission/set")?.[1]?.created?.send1;
  if (!created?.id || !submitted?.id) throw new Error("Mailbux did not confirm email submission");
}
