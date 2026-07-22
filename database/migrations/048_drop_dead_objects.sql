-- 048: drop the tables and columns the 2026-07-22 audit sentenced (docs/系统总纲.md §6.1/§6.2)
-- Production row survey confirmed every dropped object is empty or seed-only
-- (tag_dictionary 83 rows and region_alias_config 5 rows all came from migrations 002/003)

-- 1. Dead tables. seller_target.seller_party_id must go before seller_party
--    so the foreign key does not block the table drop
drop table if exists seller_target_financial;
drop table if exists seller_target_risk;
drop table if exists seller_target_tag;
drop table if exists buyer_intent_constraint;
drop table if exists tag_dictionary;
drop table if exists region_alias_config;

alter table seller_target drop column if exists seller_party_id;
drop table if exists seller_party;

-- 2. seller_target dead columns (never written by any code, or write-only telemetry)
alter table seller_target drop column if exists acceptable_relocation_regions_json;
alter table seller_target drop column if exists accepted_payment_methods_json;
alter table seller_target drop column if exists asset_regions_json;
alter table seller_target drop column if exists control_path_options_json;
alter table seller_target drop column if exists deal_paths_json;
alter table seller_target drop column if exists operating_regions_json;
alter table seller_target drop column if exists production_regions_json;
alter table seller_target drop column if exists pe_calculation_basis_json;
alter table seller_target drop column if exists completeness_score;
alter table seller_target drop column if exists last_business_update_at;
alter table seller_target drop column if exists listing_board;
alter table seller_target drop column if exists registered_country;
alter table seller_target drop column if exists last_attachment_parse_at;

-- 3. buyer_intent dead columns
alter table buyer_intent drop column if exists is_temporary;
alter table buyer_intent drop column if exists last_business_update_at;
alter table buyer_intent drop column if exists last_recommendation_at;

-- 4. visibility columns stored a three-state access level no code ever filtered
--    by (real visibility is the owner scope) so they only misled readers.
--    attachment keeps its visibility column because the upload API stores it
alter table seller_target drop column if exists visibility;
alter table buyer_party drop column if exists visibility;
alter table buyer_intent drop column if exists visibility;
alter table buyer_seller_relation drop column if exists visibility;
alter table recommendation_session drop column if exists visibility;
alter table business_update drop column if exists visibility;
