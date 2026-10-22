# Security policy

MisteR Dashboard holds GitLab and SonarQube tokens on behalf of its user, so security reports are
taken seriously.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately through GitHub's
private vulnerability reporting: open the repository's **Security** tab and click **Report a
vulnerability**.

Include what you can of:

- the affected version or commit;
- a description of the issue and its impact (for example, a token or GitLab data reachable by
  another page or another local user);
- steps to reproduce, or a proof of concept.

The maintainers will acknowledge the report, keep you informed of its progress, and credit you in the
fix unless you prefer otherwise. Please give them reasonable time to release a fix before disclosing
the issue publicly.

## Supported versions

Only the latest version on the default branch receives security fixes.

## Scope

The security model is described in the [README](../README.md#security-model). Of particular interest:
anything that lets a page other than the dashboard read through the relay or trigger a local action,
exposes a token to the browser, writes to GitLab beyond the documented actions, or executes content
coming from GitLab in the page.
