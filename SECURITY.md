# Security Policy

## Supported versions

Security fixes are provided for the latest commit on `main`. Until the project publishes stable release branches, older commits and local forks are not supported security versions.

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities. Use GitHub Private Vulnerability Reporting when enabled for the repository. If it is unavailable, contact the repository owner privately and include:

- affected commit or release;
- minimal reproduction steps and impact;
- whether credentials, personal data, Runner access, Policy bypass, or cross-Environment access may be involved;
- any logs or payloads after removing tokens, cookies, connection strings and customer data.

Do not access data that is not yours, disrupt shared systems, persist access, or publish exploit details before a coordinated fix. Test against the local Fault Lab whenever possible.

The maintainers aim to acknowledge a complete report within 3 business days, provide an initial severity assessment within 7 business days, and coordinate remediation and disclosure based on impact. These are response targets, not a warranty.

## Security boundaries

Runner bootstrap tokens, Control Plane tokens, browser cookies, database credentials, webhook tokens and model API keys are secrets. Store them in secret files or a secret manager; never commit them, place them in URLs, Eval datasets, audit archives, screenshots or issue reports.

Action execution requires server-side Environment Scope, Policy authorization, one-time Approval consumption, Resource Lock fencing and Runner capability checks. Reports that bypass any of these layers are in scope. Prompt Injection that only changes prose but cannot cross deterministic Tool, Resource, Evidence, Policy or Approval checks should still be reported with its demonstrated impact.

See `docs/备份恢复与审计归档.md`, `docs/控制面认证与RBAC.md` and `docs/Agent-Prompt-Injection防护.md` for operational controls.
