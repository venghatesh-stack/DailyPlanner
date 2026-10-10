# CHANGES — before / after

The agent was running in a headless Linux/WSL environment without a browser
(no Chrome, no Playwright, no display), so pixel-perfect screenshots of the
live app weren't possible. Instead, this folder captures the _shape_ of
each change — what the HTML / CSS looked like before and after, plus the
verification receipts from the Phase 5 run.

## `login_register_before_after.md`
Side-by-side HTML structure comparison for the redesigned login and
register pages. Shows how per-page inline `<style>` was replaced with
design-system tokens + shared components.

## `verification.md`
Test-suite output, boot-smoke results, and the PII-redaction /
open-redirect unit-check transcripts.

## How to eyeball the changes yourself
Run locally and navigate:
```bash
source .venv/bin/activate
export SUPABASE_URL=... SUPABASE_KEY=... FLASK_SECRET_KEY=$(python -c 'import secrets;print(secrets.token_urlsafe(48))')
export ENCRYPTION_KEY=...  # your Fernet passphrase
python -m flask --app app:create_app run --debug
```
Then open:
- `/login`, `/register` — redesigned, token-driven.
- Any page — skip-link appears on Tab; dark-mode muted text now passes WCAG AA; focus rings visible on keyboard.
- `/health` heatmap — now actually respects both date bounds.
- Top-right clock — shows your local timezone abbreviation, not `IST` hard-coded.

## `redesign_2026-10-11.md`
The Ink & Lime redesign pass: what changed, the two SQL migrations to run
(in order), the security fix, and what is still open.
