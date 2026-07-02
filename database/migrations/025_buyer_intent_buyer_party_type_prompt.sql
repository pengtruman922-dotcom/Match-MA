-- Match-MA buyer intent parser buyer_party type prompt tuning
-- Purpose: keep buyer_party.buyer_type prompt examples aligned with the
-- database enum values used by buyer_party_buyer_type_check.

begin;

update prompt_template
set user_prompt_template = replace(
      replace(
        user_prompt_template,
        '"buyer_type": "state_owned | private | listed | pe_fund | strategic | ..."',
        '"buyer_type": "industrial_buyer | listed_company | state_owned_platform | pe_fund | financial_investor | government_platform | other"'
      ),
      '11. Only populate buyer_party when the material describes the ACQUIRER (the buyer) itself',
      '11. For buyer_party.buyer_type use exactly one of: industrial_buyer, listed_company, state_owned_platform, pe_fund, financial_investor, government_platform, other. Map strategic/private/corporate buyers to industrial_buyer; listed acquirers to listed_company; state-owned acquirers to state_owned_platform.
12. Only populate buyer_party when the material describes the ACQUIRER (the buyer) itself'
    ),
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
      'buyer_party_type_prompt_tuning_source', 'migration_025_buyer_intent_buyer_party_type_prompt'
    ),
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'buyer_intent_parser'
  and is_default = true;

commit;
