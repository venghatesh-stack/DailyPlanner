-- Prescriptions: upload photos or PDFs of prescriptions, with who they are
-- for, the doctor, the date and notes. Run once in the Supabase SQL editor.
-- Safe to run again.
--
-- Files go to a PRIVATE storage bucket. Nobody can open them by URL: the
-- app streams each file only to the signed-in owner. Row-level security is
-- on with no policies, so only the server's secret key can read the table.

create table if not exists prescriptions (
  id            uuid primary key default gen_random_uuid(),
  user_id       text not null,
  title         text not null default '',
  patient       text not null default '',      -- who it is for: Self, Amma, ...
  doctor        text not null default '',
  clinic        text not null default '',
  prescribed_on date,
  notes         text not null default '',      -- medicines, dosage, next visit
  files         jsonb not null default '[]'::jsonb,  -- [{key, mime, size, name}]
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  is_deleted    boolean not null default false,
  deleted_at    timestamptz
);

create index if not exists prescriptions_user_idx
  on prescriptions (user_id, prescribed_on desc nulls last, created_at desc)
  where is_deleted = false;

alter table prescriptions enable row level security;

-- The private bucket: 10 MB per file, images and PDFs only.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('prescriptions', 'prescriptions', false, 10485760,
        array['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'application/pdf'])
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
