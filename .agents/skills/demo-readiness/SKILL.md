---
name: demo-readiness
description: Validate the documented end-to-end hackathon demo shortly before presenting, including startup, the primary flow, errors, secrets, performance, and honest fallback behavior. Do not use for routine small changes.
---

# Demo Readiness

## Purpose

Establish that a teammate can reproduce the real primary demo flow and explain any remaining dependency risks honestly.

## When to use

Use near demo time, after a meaningful end-to-end change, or when explicitly preparing a presenter script.

## When not to use

Do not run the full checklist for every small edit or before an actual primary journey and startup commands exist.

## Workflow

1. Read the relevant project map sections and inspect the actual startup commands, primary journey, environment-variable names, API/agent flow, and recent changes.
2. Start the project using documented commands from a clean-enough local state; note missing credentials, services, or setup instructions.
3. Exercise the main user journey end to end, including required agent tools, database reads/writes, and RAG/vision inputs only if they are truly part of the demo.
4. Exercise a representative error path and confirm users receive an understandable message rather than a blank or misleading result.
5. Check that secrets are absent from tracked files and frontend bundles, and that no fake model/database result is presented as live.
6. Measure practical responsiveness for the main flow and identify safe, plainly labeled fallback demonstrations if an external dependency is unavailable.
7. When explicitly requested, write a short reproducible presenter sequence based on the verified flow.

## Project-specific rules

- Follow root `AGENTS.md`; inspect existing implementation first, make minimal changes, reuse project patterns, and avoid speculative demo features.
- Report unavailable infrastructure, credentials, models, databases, retrieval, or vision clearly; do not silently substitute mock results.
- Keep the validation focused on the actual case and highest-value journey, not every hypothetical feature.
- Never claim a startup check, test, or end-to-end flow passed unless it was executed.

## Completion criteria

Documented startup and the primary journey have been exercised to the available extent, failures are understandable, secrets are not exposed, performance risks and honest fallbacks are known, and blockers are clear. Update the project map if commands or architecture materially changed.
