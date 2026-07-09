-- Match-MA app_user auth fields and system assistant user
-- Purpose: add username/password_hash so real accounts can log in, and seed a
-- non-login system assistant account used by background workers when writing
-- created_by / updated_by on auto-applied changes.

begin;

alter table app_user add column if not exists username text;
alter table app_user add column if not exists password_hash text;

update app_user
set username = 'admin'
where id = '00000000-0000-0000-0000-000000000201' and username is null;

create unique index if not exists uq_app_user_username
  on app_user (lower(username))
  where username is not null;

insert into app_user (id, team_id, default_workspace_id, name, email, role, status)
values (
  '00000000-0000-0000-0000-000000000202',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  '系统助手',
  null,
  'developer',
  'active'
)
on conflict (id) do update set
  name = excluded.name,
  role = excluded.role,
  status = excluded.status,
  updated_at = now();

commit;
