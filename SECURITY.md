# Security policy

## Supported versions

Forge is a personal portfolio project, not enterprise software. Only the
latest commit on `main` is supported. Older tags and branches do not
receive security updates.

## Reporting a vulnerability

Email `rohanramekar17@gmail.com` with `[FORGE SECURITY]` in the subject.
Please include:

- A short description of the vulnerability.
- Steps to reproduce, or a minimal proof of concept.
- Affected file paths, commits, or commands.
- Your preferred name and contact for credit (or `anonymous` if you
  prefer no public credit).

Please do **not** open a public GitHub issue for security reports.

## What to expect

- Acknowledgement within 5 working days.
- A disclosure window of up to 90 days from acknowledgement, extended only
  if a fix is in active development and you agree.
- Credit in the `NOTICE` file on fix, unless you decline credit.

## Out of scope

- Vulnerabilities in upstream models (FLUX.1-dev, FLUX.2-klein-4b,
  Z-Image-Turbo) — report those to Black Forest Labs or the relevant
  upstream project.
- Vulnerabilities in upstream Python dependencies — report to the
  package maintainers.
- Findings that require physical access to the user's machine or
  privileged execution outside the Forge sandbox.
- Issues in user-supplied prompts, glossaries, or reference images.
