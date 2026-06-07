begin;

create or replace function public.capture_outreach_unsubscribe(
  input_email text,
  input_reason text default 'unsubscribe',
  input_source text default 'public_page',
  input_note text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  normalized_email text := lower(trim(coalesce(input_email, '')));
  normalized_reason text := left(trim(coalesce(input_reason, 'unsubscribe')), 80);
  normalized_source text := left(trim(coalesce(input_source, 'public_page')), 80);
  normalized_note text := left(trim(coalesce(input_note, '')), 500);
begin
  if normalized_email = '' or normalized_email !~* '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'A valid email address is required.'
      using errcode = '22023';
  end if;

  if normalized_reason = '' then
    normalized_reason := 'unsubscribe';
  end if;

  if normalized_source = '' then
    normalized_source := 'public_page';
  end if;

  insert into public.outreach_unsubscribes (
    email,
    reason,
    source,
    note,
    updated_at
  )
  values (
    normalized_email,
    normalized_reason,
    normalized_source,
    normalized_note,
    now()
  )
  on conflict (email) do update
    set reason = excluded.reason,
        source = excluded.source,
        note = excluded.note,
        updated_at = now();

  return jsonb_build_object(
    'status', 'ok',
    'email', normalized_email,
    'reason', normalized_reason,
    'message', 'You have been unsubscribed from outreach emails.'
  );
end;
$$;

grant execute on function public.capture_outreach_unsubscribe(text, text, text, text)
to anon, authenticated, service_role;

commit;
