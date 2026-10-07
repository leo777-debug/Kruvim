-- Dedicated landing records in ANE; application user tables are unchanged.
create table public.landing_signups (
  id uuid primary key default gen_random_uuid(),
  full_name text not null check (char_length(trim(full_name)) between 2 and 120),
  email text not null check (char_length(email) <= 254),
  entity_name text check (char_length(entity_name) <= 160),
  phone text not null check (char_length(phone) between 7 and 30),
  source text not null default 'kruvim_landing' check (source = 'kruvim_landing'),
  created_at timestamptz not null default now()
);
create unique index landing_signups_email_idx on public.landing_signups (lower(email));
create table public.feedback_messages (
  id uuid primary key default gen_random_uuid(),
  full_name text check (char_length(full_name) <= 120),
  email text check (char_length(email) <= 254),
  message text not null check (char_length(trim(message)) between 10 and 4000),
  source text not null default 'kruvim_landing' check (source = 'kruvim_landing'),
  created_at timestamptz not null default now()
);
create table public.kruvim_form_limits (
  bucket text primary key,
  requests integer not null default 1,
  expires_at timestamptz not null
);
alter table public.landing_signups enable row level security;
alter table public.feedback_messages enable row level security;
alter table public.kruvim_form_limits enable row level security;
revoke all on public.landing_signups, public.feedback_messages, public.kruvim_form_limits from anon, authenticated;
grant all on public.landing_signups, public.feedback_messages, public.kruvim_form_limits to service_role;
create function public.kruvim_check_form_limit(p_bucket text) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare n integer;
begin
  delete from public.kruvim_form_limits where expires_at < now();
  insert into public.kruvim_form_limits (bucket, requests, expires_at)
    values (p_bucket, 1, now() + interval '10 minutes')
    on conflict (bucket) do update set requests = public.kruvim_form_limits.requests + 1
    returning requests into n;
  return n <= 5;
end;
$$;
revoke all on function public.kruvim_check_form_limit(text) from public, anon, authenticated;
grant execute on function public.kruvim_check_form_limit(text) to service_role;
