-- 003_storage_policies.sql

-- Assuming a bucket named 'projects' has been created.
-- In Supabase dashboard, you must create a bucket named 'projects' first, 
-- or do it via SQL (requires superuser, often better done via UI/API).

-- INSERT INTO storage.buckets (id, name, public) VALUES ('projects', 'projects', false);

-- Enable RLS on storage.objects
-- ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- Storage Policy: Users can only upload files to their own user directory: projects/{user_id}/...
CREATE POLICY "Users can upload to their own project folder"
ON storage.objects FOR INSERT
WITH CHECK (
    bucket_id = 'projects' AND
    (storage.foldername(name))[1] = auth.uid()::text
);

-- Storage Policy: Users can view their own project files
CREATE POLICY "Users can view their own project files"
ON storage.objects FOR SELECT
USING (
    bucket_id = 'projects' AND
    (storage.foldername(name))[1] = auth.uid()::text
);

-- Storage Policy: Users can update their own project files
CREATE POLICY "Users can update their own project files"
ON storage.objects FOR UPDATE
USING (
    bucket_id = 'projects' AND
    (storage.foldername(name))[1] = auth.uid()::text
);

-- Storage Policy: Users can delete their own project files
CREATE POLICY "Users can delete their own project files"
ON storage.objects FOR DELETE
USING (
    bucket_id = 'projects' AND
    (storage.foldername(name))[1] = auth.uid()::text
);
