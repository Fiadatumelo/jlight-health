export type MailMessage = {
  to: string;
  subject: string;
  text: string;
};

const SESSION_URL = "https://my.mailbux.com/jmap/";

function basicAuth(username: string, password: string): string {
  return "Basic " + btoa(unescape(encodeURIComponent(username + ":" + password)));
}

async function jmapRequest(url: string, auth: string, calls: unknown[][], using: string[]) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": auth,
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    body: JSON.stringify({ using, methodCalls: calls }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error("Mailbux JMAP request failed (" + response.status + "): " + detail.slice(0, 200));
  }
  const result = await response.json();
  if (!Array.isArray(result.methodResponses)) throw new Error("Mailbux returned an invalid JMAP response");
  for (const item of result.methodResponses) {
    if (item?.[0] === "error") throw new Error("Mailbux JMAP method failed: " + String(item?.[1]?.type ?? "unknown"));
  }
  return result.methodResponses;
}

export async function sendMailbuxMessage(message: MailMessage): Promise<void> {
  const email = Deno.env.get("MAILBUX_EMAIL")?.trim();
  const password = Deno.env.get("MAILBUX_APP_PASSWORD");
  if (!email || !password) throw new Error("Mailbux mailbox credentials are not configured");

  const auth = basicAuth(email, password);
  const sessionResponse = await fetch(SESSION_URL, {
    headers: { "Authorization": auth, "Accept": "application/json" },
  });
  if (!sessionResponse.ok) throw new Error("Mailbux session discovery failed (" + sessionResponse.status + ")");
  const session = await sessionResponse.json();
  const accountId = session?.primaryAccounts?.["urn:ietf:params:jmap:mail"];
  const apiUrl = session?.apiUrl;
  if (typeof accountId !== "string" || typeof apiUrl !== "string") {
    throw new Error("Mailbux did not advertise a primary mail account and API URL");
  }

  const core = "urn:ietf:params:jmap:core";
  const mail = "urn:ietf:params:jmap:mail";
  const submission = "urn:ietf:params:jmap:submission";
  const metadata = await jmapRequest(apiUrl, auth, [
    ["Mailbox/get", { accountId }, "mailboxes"],
    ["Identity/get", { accountId }, "identities"],
  ], [core, mail, submission]);

  const mailboxResult = metadata.find((x: any[]) => x?.[0] === "Mailbox/get")?.[1];
  const identityResult = metadata.find((x: any[]) => x?.[0] === "Identity/get")?.[1];
  const drafts = (mailboxResult?.list ?? []).find((x: any) => x?.role === "drafts");
  const identity = (identityResult?.list ?? []).find((x: any) => x?.email?.toLowerCase() === email.toLowerCase())
    ?? (identityResult?.list ?? [])[0];
  if (!drafts?.id || !identity?.id) throw new Error("Mailbux mailbox is missing a drafts folder or sending identity");

  const cleanTo = message.to.trim().toLowerCase();
  if (cleanTo.length > 254 || !/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(cleanTo)) {
    throw new Error("Recipient email address is invalid");
  }
  const subject = message.subject.replace(/[\\r\\n]+/g, " ").trim().slice(0, 200);
  if (!subject || message.text.length > 100000) throw new Error("Email content is invalid");

  const sendCalls = await jmapRequest(apiUrl, auth, [
    ["Email/set", {
      accountId,
      create: {
        draft1: {
          mailboxIds: { [drafts.id]: true },
          from: [{ email }],
          to: [{ email: cleanTo }],
          subject,
          textBody: [{ type: "text/plain", value: message.text }],
        },
      },
    }, "create"],
    ["EmailSubmission/set", {
      accountId,
      create: {
        send1: {
          identityId: identity.id,
          emailId: "#draft1",
          envelope: {
            mailFrom: { email },
            rcptTo: [{ email: cleanTo }],
          },
        },
      },
    }, "submit"],
  ], [core, mail, submission]);

  const created = sendCalls.find((x: any[]) => x?.[0] === "Email/set")?.[1]?.created?.draft1;
  const submissionResult = sendCalls.find((x: any[]) => x?.[0] === "EmailSubmission/set")?.[1];
  if (!created?.id || !submissionResult?.created?.send1) {
    const notCreated = submissionResult?.notCreated?.send1;
    throw new Error("Mailbux did not confirm email submission" + (notCreated?.type ? ": " + notCreated.type : ""));
  }
}
