# Mailbux JMAP transactional email

JLIGHT sends organisation-code, password-recovery and organisation-invitation messages through the dedicated Mailbux mailbox. The implementation uses Mailbux JMAP over HTTPS; it does not require the paid Mailbux management API or IMAP/POP3.

## Supabase Edge Function secrets

Configure these secrets in the target Supabase project before deploying the functions:

- `MAILBUX_EMAIL=support@jlight-health.co.za`
- `MAILBUX_APP_PASSWORD=<dedicated mailbox app password>`

Create the app password in the Mailbux dashboard under the mailbox's App Passwords section. Do not use the dashboard login password or the Mailbux management API key. Never commit the app password, include it in logs, or place it in browser configuration.

The helper discovers the JMAP session from `https://my.mailbux.com/jmap/`, then uses the advertised HTTPS API URL, primary mail account, drafts mailbox and sending identity. Messages are created and submitted using JMAP `Email/set` and `EmailSubmission/set`.

## Functions using Mailbux

- `send-organisation-code`
- `send-password-reset`
- `invite-organisation-member`

The functions retain server-side Supabase authentication and organisation/role checks. Password-reset responses remain generic to avoid account enumeration. Invitation membership is provisioned only after Mailbux accepts the invitation message for submission.

## Release procedure

1. Configure the two secrets in a non-production Supabase staging project.
2. Deploy the three functions to staging with JWT verification settings preserved from the existing project.
3. Test one organisation-code email to the verified owner, one password-recovery email to a controlled test account, and one invitation to a controlled test address.
4. Verify message receipt, sender identity, one-time recovery/invitation links, and that an unauthorised user cannot request an organisation code or invite members.
5. Only after all tests pass, configure the same secrets in production and deploy the reviewed function versions.

Do not deploy these changes to the production Supabase project until the staging mail tests pass.
