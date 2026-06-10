-- Add the signup acquisition source to public.profiles.
-- Run this in Supabase SQL Editor after the bootstrap schema.

begin;

alter table public.profiles
  add column if not exists referral_source text not null default '';

comment on column public.profiles.referral_source is
  'How the user first discovered ProspektLab (e.g. social media, newsletter, search engine).';

commit;
