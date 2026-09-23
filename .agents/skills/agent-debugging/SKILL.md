---
name: agent-debugging
description: Diagnose agent execution, tool calls, model output, and dependent services through reproducible traces and logs. Use for failures, incorrect behavior, latency, or integration errors in an existing agent flow.
---

# Agent Debugging

## Purpose

Locate the failing layer quickly and make a focused, evidence-backed repair to an existing agent workflow.

## When to use

Use when an agent request fails, a tool call is wrong, output violates a contract, latency is problematic, retries behave unexpectedly, or an external integration is unreliable.

## When not to use

Do not use to design a new agent or replace ordinary code review. Do not rewrite prompts before checking whether the API, tool, schema, database, or external service is the actual failure.

## Workflow

1. Read relevant project map sections and inspect the current flow, recent changes, configuration names, logs, and reproducible inputs.
2. Classify the failure layer: `UI → API → Agent → Tool → Database → External API → Model output`.
3. Reproduce the smallest failing request and collect safe evidence: request IDs/traces where available, tool arguments/results, status codes, validation errors, latency, retries, and token/cost signals.
4. Check contracts and data before changing instructions: input validation, tool schemas, serialized results, database responses, and external API behavior.
5. Apply the smallest fix at the confirmed layer, adding a deterministic test or focused evaluation when practical.
6. Re-run the reproduction and relevant checks. Use structured, actionable errors; redact secrets and avoid logging full sensitive payloads.

## Project-specific rules

- Follow root `AGENTS.md`; inspect existing implementation first, make minimal changes, reuse project patterns, and avoid speculative observability architecture.
- Do not blame the model when tool arguments, schemas, permissions, database data, or infrastructure are wrong.
- Keep tracing and logs useful for rapid hackathon fixes without exposing credentials or hidden prompts.
- Report unavailable tracing, models, credentials, databases, or external APIs rather than silently simulating them.
- Never claim a test passed unless it was executed.

## Completion criteria

The failing layer and evidence are documented, the minimal repair is verified to the available extent, and any remaining infrastructure blocker is explicit. Update the project map after material flow, API, or observability changes.
