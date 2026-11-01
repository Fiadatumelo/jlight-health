# Mailbux integration for JLIGHT

JLIGHT uses the existing Mailbux mailbox `support@jlight-health.co.za`. Clients can continue sending enquiries to this address; Mailbux receives those messages in its existing webmail inbox. No new mailbox, account, password, DNS record, or Mailbux setting is required for ordinary inbound client email.

JLIGHT's transactional email functions use the Mailbux JMAP service over HTTPS for organisation-code, password-recovery, and organisation-invitation messages. This does not require the paid Mailbux management API or IMAP/POP3.

## Runtime configuration

The Supabase Edge Functions read these server-side secrets:

- `MAILBUX_EMAIL=support@jlight-health.co.za`
- `MAILBUX_APP_PASSWORD=<existing authorised Mailbux mailbox credential>`

Use only an existing credential already authorised for this mailbox and already available to the project owner. Prefer an already-issued app password if one exists. **Do not create, reset, or change a Mailbux password or alter Mailbux account settings as part of this integration.** Never commit credentials, return them to a browser, or include them in logs.

The helper discovers the JMAP session from `https://my.mailbux.com/jmap/`, validates the advertised HTTPS API endpoint, reads the primary mail account, drafts/sent mailboxes and sending identity, then creates and submits messages using RFC 8621-compliant `Email/set` and `EmailSubmission/set` calls with a MIME body part and body value.

## JLIGHT email functions

- `send-organisation-code` — sends the organisation code only to the authenticated organisation owner.
- `send-password-reset` — generates a Supabase recovery link and sends it without exposing whether an account exists.
- `invite-organisation-member` — checks organisation owner/admin permissions, emails the invitation link, and creates the invited membership only after Mailbux accepts the message. Existing active, suspended, or revoked memberships are not silently duplicated or reactivated.

## Inbound client enquiries

Clients can email `support@jlight-health.co.za` from their own personal or organisation email addresses. The existing Mailbux forwarder is already enabled and routes incoming messages to the mailbox owner's existing inbox; the Mailbux webmail inbox also retains the messages. No forwarding rule, DNS record, mailbox, password, or Mailbux account setting was changed during this PR. This PR does not create a second inbox inside JLIGHT or copy private client messages into the JLIGHT database. Mailbux documents JMAP access for mailbox operations; its separate tenant-management REST API is not required for this sender. A future in-JLIGHT shared inbox would need its own authenticated JMAP sync, message storage, access controls, and UI.

## Staging-first verification

1. Confirm the existing Mailbux credential is already available in the staging Supabase secret store. Do not create or change a Mailbux credential.
2. Deploy the three functions to staging, preserving the currently deployed JWT verification settings.
3. Verify organisation-code, password-recovery and invitation delivery with controlled test accounts.
4. Confirm message receipt in the existing Mailbux mailbox, sender identity, one-time links, duplicate invitation handling, and negative authorisation tests.
5. Only after staging tests pass, separately authorise and perform production secret configuration and deployment.

Do not deploy the Mailbux sender functions to production until staging delivery and authorisation tests pass.
