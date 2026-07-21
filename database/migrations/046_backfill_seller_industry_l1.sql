-- Backfill targets created or updated through the specialized business-update
-- parser before industry_l1 was included in the extracted-action write path.

begin;

update seller_target st
set industry_l1 = tax.l1_name,
    updated_at = now()
from industry_taxonomy tax
where st.team_id = tax.team_id
  and st.workspace_id = tax.workspace_id
  and st.deleted_at is null
  and st.industry_l1 is null
  and st.industry_primary is not null
  and tax.active = true
  and lower(tax.term) = lower(st.industry_primary);

commit;
