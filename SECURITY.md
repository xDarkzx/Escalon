# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through
[GitHub security advisories](https://github.com/xDarkzx/Escalon/security/advisories/new), not
in a public issue. You'll get an acknowledgement within five working days.

## Design measures

- **Identity from the token, never from the prompt.** Every request carries an Entra ID bearer
  token, validated for signature, issuer, audience, expiry and the `Helpdesk.Use` scope. The
  ticket owner is taken from the validated token; no tool accepts a user identity as an
  argument, so a prompt can't file or read tickets as someone else.
- **No stored credentials in Azure.** Services run with key authentication disabled; the app
  uses a managed identity and role assignments. The one third-party secret (the Zammad token)
  lives in Key Vault.
- **The model can't fake actions.** A deterministic guard checks every reply: a claimed ticket
  that wasn't created is filed for real and the reply corrected; links must come from search
  results.
- **Supply chain.** Dependencies are locked (`uv.lock`), audited for known vulnerabilities in
  CI, and updated by Dependabot. Secret scanning runs on every commit.

## Supported versions

Only `main` is supported.
