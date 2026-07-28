-- 0727 phase A: prepare the seller_target status consolidation without
-- removing the legacy column.
--
-- recommendation_status answered two questions at once (may this target be
-- recommended, and has it been parsed) and answered neither reliably: it only
-- flipped to 'recommendable' when a fact write happened to land while
-- information_status was still in a parse-lifecycle state. Every other path
-- left it at 'not_recommendable' forever, which silently removed the target
-- from recommendation screening. The 2026-07-27 production audit found 8 such
-- active targets carrying complete facts.
--
-- New application code uses lifecycle_status (交易状态, human-owned, the sole
-- screening gate) and information_status (AI 处理进度, system-owned).  The
-- legacy recommendation_status column stays physically present until every
-- Railway API/worker instance is running the phase-A code.  Phase B removes it
-- in a separate migration after production verification.

-- Pre-migration counts are recorded in 平台优化方案/标的管理优化方案0727.md §0
-- (61 targets, 8 active ones stuck at not_recommendable, 4 pending_review).
-- They are not re-counted with RAISE NOTICE here: run_migration_sql doubles
-- every '%' before execution to protect psycopg3 from stray placeholders, which
-- turns a RAISE format specifier into a literal '%%' and makes PL/pgSQL reject
-- the statement with "too many parameters specified for RAISE".

-- 1. Retire the 待复核 target state. The extracted_action rows behind it stay
--    untouched and queryable, and the enum value stays in the check constraint
--    for historical rows, but no writer produces it any more.
update seller_target
set information_status = 'normal',
    updated_at = now()
where deleted_at is null
  and information_status = 'pending_review';

-- 2. Defensive location normalization. The audit found production data already
--    canonical, so this is expected to touch zero rows -- it exists so a
--    cascading region filter cannot be defeated by a stray short province name
--    written before backend/app/services/region_dictionary.py existed.
update seller_target
set location_province = nullif(btrim(location_province), ''),
    location_city = nullif(btrim(location_city), ''),
    location_district = nullif(btrim(location_district), ''),
    updated_at = now()
where deleted_at is null
  and (
    location_province is distinct from nullif(btrim(location_province), '')
    or location_city is distinct from nullif(btrim(location_city), '')
    or location_district is distinct from nullif(btrim(location_district), '')
  );

with province_alias(short_name, canonical_name) as (
  values
    ('北京', '北京市'), ('天津', '天津市'), ('河北', '河北省'), ('山西', '山西省'),
    ('内蒙古', '内蒙古自治区'), ('辽宁', '辽宁省'), ('吉林', '吉林省'),
    ('黑龙江', '黑龙江省'), ('上海', '上海市'), ('江苏', '江苏省'),
    ('浙江', '浙江省'), ('安徽', '安徽省'), ('福建', '福建省'), ('江西', '江西省'),
    ('山东', '山东省'), ('河南', '河南省'), ('湖北', '湖北省'), ('湖南', '湖南省'),
    ('广东', '广东省'), ('广西', '广西壮族自治区'), ('海南', '海南省'),
    ('重庆', '重庆市'), ('四川', '四川省'), ('贵州', '贵州省'), ('云南', '云南省'),
    ('西藏', '西藏自治区'), ('陕西', '陕西省'), ('甘肃', '甘肃省'),
    ('青海', '青海省'), ('宁夏', '宁夏回族自治区'), ('新疆', '新疆维吾尔自治区'),
    ('台湾', '台湾省'), ('香港', '香港特别行政区'), ('澳门', '澳门特别行政区')
)
update seller_target st
set location_province = province_alias.canonical_name,
    updated_at = now()
from province_alias
where st.deleted_at is null
  and st.location_province = province_alias.short_name;

-- 3. Add the new lifecycle-first index alongside the legacy scope index.  The
--    latter must remain available to old containers during the rolling deploy.
create index if not exists idx_seller_target_lifecycle_scope
  on seller_target using btree (team_id, workspace_id, lifecycle_status, information_status)
  where deleted_at is null;

-- 4. Record the terminal time of parse operations independently from research.
--    Comparing this with last_research_at lets the API report the latest AI
--    operation rather than letting an older failure mask a newer success.
alter table seller_target
  add column if not exists last_parse_at timestamptz;
