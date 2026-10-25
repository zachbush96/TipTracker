-- Review-only additive schema for issue #16. No credentials or tip-out migration.
-- Apply through the deployment process after review of the database role and grants.
begin;

create table public.integration_grants (
    id varchar(36) primary key,
    token_hash varchar(64) unique not null,
    user_id uuid not null references public.users(id),
    client_id varchar(100) not null,
    audience varchar(100) not null,
    scopes text not null,
    expires_at bigint not null,
    revoked boolean not null default false
);

create table public.integration_tip_previews (
    id varchar(36) primary key,
    grant_id varchar(36) not null references public.integration_grants(id),
    payload text not null,
    expires_at bigint not null,
    consumed boolean not null default false
);
create index integration_preview_expiry on public.integration_tip_previews(expires_at);

create table public.integration_tip_receipts (
    id varchar(36) primary key,
    user_id uuid not null references public.users(id),
    client_id varchar(100) not null,
    key varchar(128) not null,
    payload text not null,
    tip_id bigint references public.tip_entries(id) on delete set null,
    unique(user_id, client_id, key)
);

-- These tables are server-only. Browser/Data API roles have no access.
alter table public.integration_grants enable row level security;
alter table public.integration_tip_previews enable row level security;
alter table public.integration_tip_receipts enable row level security;
revoke all on public.integration_grants from public, anon, authenticated;
revoke all on public.integration_tip_previews from public, anon, authenticated;
revoke all on public.integration_tip_receipts from public, anon, authenticated;
-- No permissive RLS policies. Review the backend role separately.
commit;
