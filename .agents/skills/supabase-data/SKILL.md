---
name: supabase-data
description: Design or change Supabase PostgreSQL, Storage, client access, migrations, and RLS for this project. Use only when the requested case actually needs Supabase data or files.
---

# Supabase Data

## Purpose

Add the minimum secure, reproducible Supabase persistence required by the actual hackathon workflow.

## When to use

Use for Supabase clients, PostgreSQL schemas, migrations, tables, relationships, indexes, Storage, RLS, or authentication that the case requires.

## When not to use

Do not use to prebuild a generic agriculture database, or to enable Auth, Realtime, Edge Functions, pgvector, or Storage without a demonstrated need.

## Workflow

1. Read the relevant project map sections and inspect existing Supabase config, migrations, client code, and environment templates.
2. Establish the data contract and access boundary before creating a table, bucket, or client path.
3. Prefer a reviewed migration over undocumented dashboard-only changes whenever practical.
4. For each new table, record its purpose, primary key, important fields, relationships, necessary indexes, and access policy.
5. Keep browser use to the anon/client key; keep server credentials and the service-role key on the server only.
6. Enable and test RLS deliberately for exposed tables and Storage paths. Add authentication only when the real use case needs identity.
7. Run the relevant migration, query, policy, or integration check when infrastructure is available; otherwise state what could not be verified.

## Project-specific rules

- Follow root `AGENTS.md`; inspect existing implementation first, make minimal changes, reuse project patterns, and avoid speculative architecture.
- Use a small schema and resource-conscious free-tier usage. Do not create hypothetical tables or indexes.
- Add vector storage only for an actual retrieval requirement; document its retrieval contract and cost implications.
- Distinguish source observations from AI inferences and retain only permitted, necessary agricultural data with provenance.
- Never expose service-role keys or server-only secrets, and never put secret values in source, migrations, documentation, or frontend bundles.
- Report unavailable Supabase projects, credentials, or migration access rather than using unlabeled mock persistence. Never claim a test passed unless it ran.

## Completion criteria

Schema and access behavior are documented, migration-backed where practical, minimally scoped, and verified to the available extent. Update the project map for real tables, policies, Storage, environment-variable names, and commands.
