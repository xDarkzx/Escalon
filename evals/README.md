# Evaluation set

`questions.jsonl` holds 50 support requests written the way staff phrase them, not copied
from article titles. 41 are grounded in a specific Microsoft troubleshooting article; 9 are
deliberately outside the knowledge base (hardware damage, requests, other products, a
phishing click).

## Labelling rules

`expected_action` is what a good first-line technician would do:

- **answer** — the article's fix is something a staff member can do on their own device
  without admin rights: Settings, Control Panel, Credential Manager, installing a Windows
  update, trying another port, waiting out a lockout, or "this is blocked by design".
- **escalate** — any of:
  - the fix needs an administrator: tenant, Intune or Group Policy changes, server-side
    changes, `HKLM` registry edits, resetting someone's MFA or password;
  - no article matches the problem;
  - physical damage, a hardware fault, a request (new account or equipment), or a possible
    security incident.

`expected_articles` lists the article(s) that contain the answer. For escalations they are
the articles a technician should be pointed to in the ticket.

## Label changes

Labels are only changed to match these rules, never to match agent output, and every change
is listed here.

| Question | Change | Reason |
|---|---|---|
| q11 | answer → escalate | Fix changes the time-out on the file server. |
| q12 | answer → escalate | Fix is an `HKLM` registry edit. |
| q36 | answer → escalate | Fix is in the Intune admin center. |
