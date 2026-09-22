# CodeForge\n\nCodeForge is an AI-native coding workspace built with FastAPI, Monaco Editor, Supabase, and a unified LLM gateway.\n\n## Features\n\n- AI coding agent with Build, Review, Debug, and Explain modes\n- FreeLLMAPI-backed model routing with automatic provider fallback\n- OpenAI-compatible streaming and tool calling\n- Monaco code editor and project explorer\n- AI-generated file change review with accept/reject\n- Temporary per-user/per-project workspaces synchronized with Supabase Storage\n- Per-project agent locking to prevent concurrent workspace corruption\n- Bounded command execution and LLM/tool loops\n- Persistent projects and authentication through Supabase\n- Multi-project support\n\n## Architecture\n\nCodeForge deliberately does **not** store individual provider API keys. It talks to a private FreeLLMAPI gateway through one OpenAI-compatible endpoint:\n\n```text\nBrowser\n  |\n  v\nFastAPI / CodeForge Agent\n  |\n  +--> Supabase Auth / PostgreSQL / Storage\n  |\n  +--> Project workspace + tools\n  |\n  +--> FreeLLMAPI (private)\n          |\n          +--> provider/model discovery\n          +--> health + quota tracking\n          +--> routing + fallback\n          +--> streaming + tool translation\n          |\n          +--> configured LLM providers\n```\n\nFreeLLMAPI exposes an OpenAI-compatible `/v1` interface. CodeForge defaults to `/v1/chat/completions` because it provides broad streaming/tool compatibility; the Responses API remains supported through the `FREE_LLM_API_WIRE_API=responses` setting.\n\n## Prerequisites\n\n- Python 3.10+\n- A Supabase project\n- A running FreeLLMAPI instance with at least one configured provider key\n- OpenAI Python SDK (installed from `requirements.txt`)\n\n## Local Development\n\n1. Install dependencies:\n\n   ```bash\n   pip install -r requirements.txt\n   ```\n\n2. Start FreeLLMAPI separately. The upstream project provides a Docker Compose setup:\n\n   ```bash\n   git clone https://github.com/tashfeenahmed/freellmapi.git\n   cd freellmapi\n   docker compose up -d\n   ```\n\n3. Configure FreeLLMAPI's provider credentials in its own dashboard/environment. Do not copy those provider secrets into CodeForge.\n\n4. Copy CodeForge's `.env.example` to `.env`.\n\n5. Configure Supabase:\n\n   - `SUPABASE_URL`\n   - `SUPABASE_ANON_KEY`\n   - `SUPABASE_SERVICE_ROLE_KEY`\n\n6. Configure the CodeForge gateway:\n\n   ```env\n   FREE_LLM_API_URL=http://localhost:3001/v1\n   FREE_LLM_API_KEY=freellmapi-your-unified-key\n   FREE_LLM_API_WIRE_API=chat_completions\n\n   DEFAULT_MODEL=auto:balanced\n   PLANNING_MODEL=auto:smart\n   CODING_MODEL=auto:balanced\n   REVIEW_MODEL=auto:smart\n   DEBUG_MODEL=auto:reliable\n   ```\n\n7. Start CodeForge:\n\n   ```bash\n   uvicorn app.main:app --reload\n   ```\n\n8. After authenticating, check:\n\n   `GET /api/ai/status`\n\n   A healthy response includes `status: "ready"` and the number of models currently visible through the gateway.\n\n## Routing\n\nTask-level routing is intentionally provider-neutral:\n\n```text\nplanning -> auto:smart\ncoding   -> auto:balanced\nreview   -> auto:smart\ndebug    -> auto:reliable\n```\n\nThese `auto:*` model IDs are interpreted by FreeLLMAPI. CodeForge never assumes that a model name belongs to Claude, GPT, Gemini, Groq, or another provider.\n\nYou can also pin a specific gateway model by sending its model ID in the chat request.\n\n## Sprint 1\n\nSprint 1 establishes the gateway boundary without changing the frontend:\n\n- [x] Replace provider-specific AI configuration with one gateway client\n- [x] Route chat-completion streaming through FreeLLMAPI\n- [x] Preserve agent tool calling\n- [x] Preserve the Responses API path as an optional wire protocol\n- [x] Remove provider inference from CodeForge\n- [x] Add gateway readiness endpoint\n- [x] Persist gateway/wire metadata with assistant messages\n- [ ] Add live provider/quota usage dashboards\n- [ ] Add user/project AI limits\n- [ ] Add workspace-aware context management\n- [ ] Add production execution sandbox\n\n## Security note\n\nKeep FreeLLMAPI private. Do not expose its port directly to the public internet when CodeForge is deployed. Provider credentials belong in FreeLLMAPI, while CodeForge only receives its unified gateway key.\n\nThe command executor is hardened with workspace scoping, bounded execution time, bounded output, and a restricted environment. It is **not a complete OS-level sandbox for hostile multi-tenant code execution**. A production deployment accepting arbitrary untrusted code should add container/process isolation before exposing terminal execution broadly.

## Sprint 3 — IDE intelligence

Sprint 3 adds the context and editing primitives that make CodeForge IDE-first:

- `@workspace`, `@file:path`, `@folder:path` and `@selection` context directives.
- Server-side workspace context assembly with size limits and path traversal protection.
- Ctrl+K Inline AI for selected Monaco code with preview and Apply/Cancel flow.
- Automatic workspace checkpoints before Build and Debug agent runs.
- Durable checkpoint snapshots in Supabase Storage with restore support.
- Provider-neutral routing profiles remain the only model choices exposed by the IDE.

Context is intentionally bounded so large repositories do not get blindly injected into every prompt. Production deployments should still add semantic indexing/retrieval for very large codebases in the next iteration.


## Sprint 4 — Agent Modes

CodeForge now supports explicit agent execution modes with server-side policies and bounded budgets:

- **Plan** — inspect and produce an implementation plan; read-only.
- **Build** — implement features and validate them.
- **Debug** — diagnose, fix and re-run validation.
- **Review** — inspect correctness, security and maintainability; read-only.
- **Test** — discover and run relevant checks; read-only.
- **Refactor** — improve structure while preserving behavior.
- **Security** — security-focused inspection; read-only.
- **Optimize** — targeted performance/reliability improvements.
- **Explain** — understand a codebase without changing files.

Each mode has hard server-side limits for steps, tool calls, file changes and runtime. Read-only modes cannot call file-write tools, and their command runner blocks common mutation/install/reset patterns. The agent emits mode and budget events to the IDE so execution policy is visible during a run.

Debug/build-style modes are instructed to validate changes and iterate through tool results. Full process/container isolation for untrusted command execution remains a Sprint 5 concern.


## Sprint 5 — Production Execution & Audit

Sprint 5 hardens the execution boundary and adds operational traceability:

- Docker sandbox is the default for terminal and agent commands.
- Sandbox networking is disabled.
- CPU, memory, PID and timeout limits are enforced.
- The container receives only the project workspace as a read/write volume.
- The sandbox filesystem is read-only except for the mounted workspace and temporary filesystem.
- Application secrets are not inherited into executed processes.
- Trusted local development can explicitly use `EXECUTION_MODE=process`; this should not be used for untrusted multi-user workloads.
- Authenticated Git status, diff, log and commit APIs are available under `/api/git`.
- Git commits create a workspace checkpoint first.
- Audit events are persisted for agent execution, terminal execution and Git operations.
- Users can view their own audit events through `/api/audit`.

### Sprint 5 environment

```env
EXECUTION_MODE=docker
EXECUTION_DOCKER_IMAGE=mcr.microsoft.com/devcontainers/python:3.12
EXECUTION_CPU_LIMIT=1.0
EXECUTION_MEMORY_LIMIT=512m
EXECUTION_PIDS_LIMIT=128
EXECUTION_TIMEOUT=30
```

Apply `supabase/migrations/20260922_sprint5_audit.sql` before enabling audit reporting.

This sandbox is a meaningful isolation boundary, but production operators should still use a dedicated execution host/node, resource quotas at the infrastructure layer, image pinning/scanning, and outbound egress controls appropriate to their threat model.
