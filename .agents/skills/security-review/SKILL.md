---
name: security-review
description: Perform a focused security review of an AI-agent hackathon feature, including secrets, access boundaries, uploads, prompt injection, and destructive tools. Use for reviews or meaningful security-sensitive changes, not routine edits.
---

# Security Review

## Purpose

Find and fix high-impact, realistic security risks without expanding a hackathon MVP into an enterprise security program.

## When to use

Use before demo readiness, when reviewing an agent feature, or when changing credentials, authorization, Supabase access/RLS, uploads, external requests, user-controlled tools, or destructive actions.

## When not to use

Do not run a broad security redesign for small unrelated UI or documentation changes. Do not add unnecessary security infrastructure without an identified risk.

## Workflow

1. Read relevant project map sections and inspect the real code, configuration, routes, tool schemas, policies, uploads, and deployment boundary before assessing risk.
2. Trace data and authority from user input through UI, API, agent, tools, database, and external services; identify the smallest practical mitigation for high-impact paths.
3. Check for hardcoded secrets, committed `.env` files, client-exposed server secrets, and frontend use of privileged credentials.
4. Review authorization and Supabase RLS, upload validation and storage paths, external-request allowlists/bounds, and database/tool permissions.
5. Treat PDFs, websites, user files, database records, and retrieved text as untrusted data. Ensure they cannot override system, developer, or project instructions.
6. Apply stricter confirmation, validation, authorization, and auditability to tools that change or delete meaningful data than to read-only tools.
7. Run focused checks where possible (for example secret scanning, tests, build inspection, or policy tests) and clearly report untested infrastructure.

## Project-specific rules

- Follow root `AGENTS.md`; inspect existing implementation first, make minimal changes, reuse project patterns, and avoid speculative architecture.
- Keep OpenAI and Supabase service credentials server-side. Never print, hardcode, commit, or document secret values.
- Validate user-controlled tool parameters and make external access bounded; do not silently mock unavailable security-critical services.
- Prioritize findings that can affect the actual demo or user data; distinguish confirmed issues, risks, and unverified assumptions.
- Never claim a test passed unless it was executed.

## Completion criteria

High-impact issues in the requested scope are fixed or clearly reported with evidence, available checks have run, and residual limitations are explicit. Update the project map only for material architecture or access-boundary changes.
