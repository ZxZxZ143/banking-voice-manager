---
name: agent-evals
description: Create or update small, useful regression evaluations for agent behavior, tools, routing, retrieval, or structured outputs. Use after meaningful behavior changes or recurring failures, not for ordinary code-only changes.
---

# Agent Evaluations

## Purpose

Protect the primary hackathon user journey from AI-behavior regressions with a compact, representative evaluation set.

## When to use

Use when agent instructions, tools, routing, retrieval, structured outputs, or a previously working scenario changes or breaks.

## When not to use

Do not build a large benchmark before a working slice exists, or use AI evaluations as a substitute for deterministic unit/integration tests.

## Workflow

1. Read the relevant project map sections and inspect the actual agent contract, tests, fixtures, and observed failure before changing them.
2. Separate deterministic software checks from AI behavior evaluations, and define the behavior each case measures.
3. Start with about 5–15 representative cases when evaluation is warranted: expected tool selection/arguments, structured output, grounding/source use, unsupported claims, missing information, and failure behavior.
4. Use assertions proportional to output variability; prefer verifiable structure, tool calls, citations, and safety conditions over brittle prose matching.
5. Add a focused regression case for an important reproducible bug where practical, without optimizing the prompt for a single example.
6. Run the evaluation or deterministic checks available and record inputs, conditions, and results without exposing secrets or sensitive data.

## Project-specific rules

- Follow root `AGENTS.md`; inspect existing implementation first, make minimal changes, reuse project patterns, and avoid speculative test architecture.
- Keep fixtures authorized, representative, and clearly labeled; do not silently replace unavailable live dependencies with mock successes.
- Report missing models, credentials, services, or tracing as unavailable and distinguish unrun from failed checks.
- Never claim a test passed unless it was executed.

## Completion criteria

The changed behavior has a small, maintainable evaluation or deterministic regression check appropriate to the risk, with a documented result and any infrastructure limits. Update the project map only if the testing architecture or commands materially change.
