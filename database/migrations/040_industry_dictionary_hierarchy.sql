-- Add explicit L1/L2 parentage and alias ownership without changing recall fields.

begin;

alter table industry_taxonomy
  add column if not exists parent_id uuid references industry_taxonomy(id),
  add column if not exists canonical_term_id uuid references industry_taxonomy(id);

update industry_taxonomy child
set parent_id = parent.id
from industry_taxonomy parent
where child.level = 'l2'
  and child.parent_id is null
  and parent.team_id = child.team_id
  and parent.workspace_id = child.workspace_id
  and parent.level = 'l1'
  and parent.term = child.l1_name;

update industry_taxonomy alias
set canonical_term_id = parent.id
from industry_taxonomy parent
where alias.level = 'alias'
  and alias.canonical_term_id is null
  and parent.team_id = alias.team_id
  and parent.workspace_id = alias.workspace_id
  and parent.level = 'l1'
  and parent.term = alias.l1_name;

create index if not exists idx_industry_taxonomy_parent
  on industry_taxonomy(team_id, workspace_id, parent_id)
  where level = 'l2';

create index if not exists idx_industry_taxonomy_canonical
  on industry_taxonomy(team_id, workspace_id, canonical_term_id)
  where level = 'alias';

commit;
