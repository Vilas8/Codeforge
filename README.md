# Universal CodeForge

A production-ready AI Coding Agent web application in Python, designed to be deployed on Render with Supabase as the persistent backend.

## Features
- AI coding agent (OpenAI compatible via Universal API)
- Monaco code editor and project explorer
- Sandboxed terminal execution
- Persistent projects and chat history via Supabase (PostgreSQL & Storage)
- Secure ZIP import/export
- Multi-project support and User Authentication

## Prerequisites
- Python 3.10+
- A Supabase Project
- An OpenAI-compatible API key (OpenAI, Anthropic via proxy, etc.)

## Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables:**
   Copy `.env.example` to `.env` and fill in your Supabase credentials and Universal API details.

3. **Database Setup:**
   Run the SQL scripts located in `supabase/migrations/` in your Supabase project's SQL Editor to create the necessary tables and RLS policies.

4. **Run the Application:**
   ```bash
   uvicorn app.main:app --reload
   ```

## Architecture
This application uses **FastAPI** as the backend, rendering a lightweight frontend. 
Persistent state (Users, Projects, Chat, Files) is stored securely in **Supabase**.
The **Render** container provides a temporary workspace for the AI to execute and validate code.

## Deployment on Render
Connect your repository to Render and use the provided `render.yaml` blueprint. Make sure to populate the required Environment Variables in the Render dashboard.
