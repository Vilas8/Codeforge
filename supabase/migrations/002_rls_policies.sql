-- 002_rls_policies.sql

-- Enable RLS on all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;

-- Profiles: Users can view and update their own profile
CREATE POLICY "Users can view own profile" 
ON public.profiles FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" 
ON public.profiles FOR UPDATE USING (auth.uid() = id);

-- Projects: Users can CRUD their own projects
CREATE POLICY "Users can view own projects" 
ON public.projects FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own projects" 
ON public.projects FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own projects" 
ON public.projects FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own projects" 
ON public.projects FOR DELETE USING (auth.uid() = user_id);

-- Conversations
CREATE POLICY "Users can view own conversations" 
ON public.conversations FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own conversations" 
ON public.conversations FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own conversations" 
ON public.conversations FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own conversations" 
ON public.conversations FOR DELETE USING (auth.uid() = user_id);

-- Messages (Inherits access implicitly via conversation ownership, but we enforce user_id directly or through join if needed. For simplicity, we can rely on the backend enforcing ownership, or join with conversations)
CREATE POLICY "Users can view messages of own conversations" 
ON public.messages FOR SELECT 
USING (EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = messages.conversation_id AND c.user_id = auth.uid()));

CREATE POLICY "Users can insert messages to own conversations" 
ON public.messages FOR INSERT 
WITH CHECK (EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = messages.conversation_id AND c.user_id = auth.uid()));

-- Project Files
CREATE POLICY "Users can view files of own projects" 
ON public.project_files FOR SELECT 
USING (EXISTS (SELECT 1 FROM public.projects p WHERE p.id = project_files.project_id AND p.user_id = auth.uid()));

CREATE POLICY "Users can manage files of own projects" 
ON public.project_files FOR ALL 
USING (EXISTS (SELECT 1 FROM public.projects p WHERE p.id = project_files.project_id AND p.user_id = auth.uid()));

-- Agent Runs
CREATE POLICY "Users can view own agent runs" 
ON public.agent_runs FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own agent runs" 
ON public.agent_runs FOR INSERT WITH CHECK (auth.uid() = user_id);
