# Project Map

## Project purpose

HackAlem AI Voice Router: a contact-center voice-robot simulation whose central problem is LLM-based selection of the correct business scenario from Russian, Kazakh, and mixed-language dialogue. It must handle ambiguity, context, topic changes, uncertainty, and operator handoff. Speech recognition and synthesis are required final-MVP interfaces, but routing quality is the main evaluated intelligence.

## Repository structure

- `README.md` — short repository identification.
- `AGENTS.md` — persistent project rules and planned default stack.
- `.agents/skills/` — reusable project-local Codex Skills; select only the Skills relevant to the task.
- `docs/PROJECT_MAP.md` — this navigation and architecture map.

## Application architecture and entry points

**Implemented:** no application source, backend, frontend, API routes, Router Agent, configuration module, or startup entry point exists yet.

**Planned architecture:** `User → STT → Router Agent → Scenario Handler / Tools → Response → TTS`. Start with text routing and retain text input as a development/debugging fallback. The Router Agent is the LLM-based primary scenario selector; it should produce a structured routing result when practical. A multi-agent design is not planned unless the actual starter-kit requirements justify it.

## Data flow

No implemented data flow. Planned routing must consider relevant conversation context and distinguish confident scenario selection from clarification or operator handoff.

## Domain data, database, and storage

No database client, Supabase configuration, schema, migration, row-level security policy, or file storage configuration exists. For the initial MVP, starter-kit JSON files and simple in-memory conversation state are sufficient. Persistent storage is planned only if a real requirement for it emerges.

The starter kit is expected to supply authoritative scenario and evaluation inputs conceptually including `scenarios.json`, `dialogs_sample.json`, `knowledge_base.json`, `mock_backend.json`, `dev_utterances.json`, and `evaluate.py`. Their schemas have not been inspected and must not be assumed.

## OpenAI / agent layer

No OpenAI SDK usage, OpenAI Agents SDK usage, agents, tools, prompts, or evaluation tests exist. The planned routing layer must use an LLM for meaningful scenario selection; an encoder-based intent classifier must not be the primary selector, and evaluation utterances must not be hardcoded.

Future routing outputs should support concise application-level supervisor trace data—selected scenario, confidence, alternatives, routing reason, topic-change signal, and latency measurements—without exposing hidden chain-of-thought.

## Environment variables

No environment template or environment-variable references exist. Do not create real credential files. Add a `.env.example` only when a selected implementation needs configuration, with names and placeholders only.

## Project-local Codex Skills

Seven reusable Skills are available under `.agents/skills/`. The current baseline is `agents-sdk`, `agent-evals`, `agent-debugging`, `security-review`, and `demo-readiness`. Use `supabase-data` only if persistence is later required. `agri-rag-vision` is currently irrelevant and remains only as a reusable Skill for changed requirements.

## Important commands

No dependency manifests, package manager lockfiles, scripts, Docker files, test configuration, linter, formatter, type checker, or runnable application commands exist.

Git / inspection commands used during setup:

```powershell
git status --short --branch
git remote -v
git ls-tree -r --name-only HEAD
```

## Current implementation status

- **Implemented:** empty repository scaffold (README), project operating instructions, and local reusable Skills.
- **Partially implemented:** none.
- **Planned / not implemented:** starter-kit inspection, text routing, dialogue context, scenario execution, supervisor trace, STT, TTS, latency work, backend, frontend, tests, dependency setup, deployment, and environment template.

## Known issues and blockers

- The actual starter-kit files and their schemas have not yet been inspected, so routing contracts and commands cannot be designed responsibly.
- No application/dependency configuration exists, so there are no dependencies to install or runnable checks beyond Git inspection.

## Next step

Inspect the supplied starter kit and evaluation utility, identify the smallest text-routing user journey, then implement only the components needed to measure and demonstrate routing quality. Update this map with verified paths, contracts, and commands.
