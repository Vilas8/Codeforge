# CodeForge

CodeForge is an AI coding workspace built with FastAPI, Monaco Editor, Supabase, and provider-specific LLM APIs.

## Features

- AI coding agent with Build, Review, Debug, and Explain modes
- Claude models through LLMsRelay OpenAI-compatible Chat Completions
- Codex/GPT models through LLMsRelay Responses API
- Monaco code editor and project explorer
- AI-generated file change review with accept/reject
- Temporary per-user/per-project workspaces synchronized with Supabase Storage
- Per-project agent locking to prevent concurrent workspace corruption
- Bounded command execution and LLM/tool loops
- Persistent projects and authentication through Supabase
- Multi-project support

## Prerequisites

- Python 3.10+
- A Supabase project
- LLMsRelay API access (or another compatible endpoint configured through the provider variables)

## Local Development

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env`.

3. Configure Supabase:

   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`

4. Configure the AI providers:

   ```env
   CLAUDE_API_KEY=your-llmsrelay-key
   CLAUDE_API_BASE_URL=https://api.llmsrelay.com/v1
   CLAUDE_MODEL=claude-sonnet-4.6

   CODEX_API_KEY=your-llmsrelay-key
   CODEX_API_BASE_URL=https://api.llmsrelay.com/v1
   CODEX_MODEL=gpt-5.5

   DEFAULT_MODEL=claude-sonnet-4.6
   ```

   Use separate keys if desired; the same provider key can also be used for both providers.

5. Start the application:

   ```bash
   uvicorn app.main:app --reload
   ```

## AI Provider Routing

The selected model determines the wire protocol:

```
claude-*  -> Claude provider -> /chat/completions
gpt-*     -> Codex provider  -> /responses
codex*    -> Codex provider  -> /responses
```

This allows CodeForge to use Claude and Codex/GPT models in the same installation without forcing both through one API protocol.

Task-specific models can be configured with:

- `PLANNING_MODEL`
- `CODING_MODEL`
- `REVIEW_MODEL`
- `DEBUG_MODEL`

## Architecture

```
Browser
  |
  v
FastAPI
  |
  +--> Supabase Auth / PostgreSQL / Storage
  |
  +--> Per-user project workspace
  |
  +--> CodeForge Agent
         |
         +--> Claude -> Chat Completions
         |
         +--> Codex/GPT -> Responses
         |
         +--> Project tools
                |- list_files
                |- read_file
                |- write_file
                |- run_command
```

The Render container provides temporary execution workspaces. Project files are synchronized with Supabase Storage so a restarted container can hydrate the project again.

## Deployment on Render

Connect the repository to Render and use the provided `render.yaml` blueprint. Configure all required Supabase and provider environment variables in the Render dashboard.

### Security note

The command executor is hardened with workspace scoping, bounded execution time, bounded output, and a restricted environment. It is **not a complete OS-level sandbox for hostile multi-tenant code execution**. A production deployment accepting arbitrary untrusted code should add container/process isolation before exposing terminal execution broadly.
