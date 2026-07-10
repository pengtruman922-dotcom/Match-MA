-- Match-MA industry taxonomy and multi-industry intent fields
-- Purpose: closed L1 industry dictionary (15 categories) with semi-open L2
-- terms and alias mappings, normalized industry_l1 on seller targets, and
-- multi-value industries / excluded industries on buyer intents.

begin;

create table if not exists industry_taxonomy (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  term text not null,
  level text not null check (level in ('l1', 'l2', 'alias')),
  l1_name text not null,
  active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists uq_industry_taxonomy_term
  on industry_taxonomy (team_id, workspace_id, lower(term));
create index if not exists idx_industry_taxonomy_l1
  on industry_taxonomy (team_id, l1_name) where active = true;

alter table seller_target
  add column if not exists industry_l1 text;

alter table buyer_intent
  add column if not exists industries_json jsonb not null default '[]'::jsonb;

alter table buyer_intent
  add column if not exists excluded_industries_json jsonb not null default '[]'::jsonb;

create index if not exists idx_seller_target_industry_l1
  on seller_target (team_id, industry_l1) where deleted_at is null;

insert into industry_taxonomy (team_id, workspace_id, term, level, l1_name, sort_order)
select
  '00000000-0000-0000-0000-000000000001'::uuid,
  '00000000-0000-0000-0000-000000000101'::uuid,
  v.term, v.level, v.l1_name, v.sort_order
from (
  values
    ('能源', 'l1', '能源', 1),
    ('金融', 'l1', '金融', 2),
    ('信息技术与通信', 'l1', '信息技术与通信', 3),
    ('房地产与建筑', 'l1', '房地产与建筑', 4),
    ('交通与物流', 'l1', '交通与物流', 5),
    ('文化与传媒', 'l1', '文化与传媒', 6),
    ('制造与工业', 'l1', '制造与工业', 7),
    ('商贸与消费', 'l1', '商贸与消费', 8),
    ('医药与健康', 'l1', '医药与健康', 9),
    ('教育与科研', 'l1', '教育与科研', 10),
    ('环保与公用事业', 'l1', '环保与公用事业', 11),
    ('农林牧渔', 'l1', '农林牧渔', 12),
    ('军工', 'l1', '军工', 13),
    ('商务与专业服务', 'l1', '商务与专业服务', 14),
    ('其他', 'l1', '其他', 15),

    ('电网', 'l2', '能源', 0),
    ('发电', 'l2', '能源', 0),
    ('石油石化', 'l2', '能源', 0),
    ('煤炭', 'l2', '能源', 0),
    ('核电', 'l2', '能源', 0),
    ('综合能源服务', 'l2', '能源', 0),
    ('电力工程', 'l2', '能源', 0),
    ('售电', 'l2', '能源', 0),
    ('光伏', 'l2', '能源', 0),
    ('风电', 'l2', '能源', 0),
    ('储能', 'l2', '能源', 0),
    ('新能源制造', 'l2', '能源', 0),
    ('银行', 'l2', '金融', 0),
    ('保险', 'l2', '金融', 0),
    ('证券', 'l2', '金融', 0),
    ('期货', 'l2', '金融', 0),
    ('金融科技', 'l2', '金融', 0),
    ('控股平台', 'l2', '金融', 0),
    ('交易所', 'l2', '金融', 0),
    ('运营商', 'l2', '信息技术与通信', 0),
    ('通信设备', 'l2', '信息技术与通信', 0),
    ('软件与信息化服务', 'l2', '信息技术与通信', 0),
    ('互联网服务', 'l2', '信息技术与通信', 0),
    ('半导体与集成电路', 'l2', '信息技术与通信', 0),
    ('智慧城市', 'l2', '信息技术与通信', 0),
    ('人工智能', 'l2', '信息技术与通信', 0),
    ('网络安全', 'l2', '信息技术与通信', 0),
    ('北斗与卫星应用', 'l2', '信息技术与通信', 0),
    ('算力与数据中心', 'l2', '信息技术与通信', 0),
    ('电子元件', 'l2', '信息技术与通信', 0),
    ('房地产', 'l2', '房地产与建筑', 0),
    ('建筑施工', 'l2', '房地产与建筑', 0),
    ('设计监理与工程咨询', 'l2', '房地产与建筑', 0),
    ('装饰装修', 'l2', '房地产与建筑', 0),
    ('物业管理', 'l2', '房地产与建筑', 0),
    ('家居建材', 'l2', '房地产与建筑', 0),
    ('产业园区', 'l2', '房地产与建筑', 0),
    ('航空运输', 'l2', '交通与物流', 0),
    ('水运', 'l2', '交通与物流', 0),
    ('公路', 'l2', '交通与物流', 0),
    ('铁路', 'l2', '交通与物流', 0),
    ('轨道交通', 'l2', '交通与物流', 0),
    ('机场', 'l2', '交通与物流', 0),
    ('港口', 'l2', '交通与物流', 0),
    ('物流运输', 'l2', '交通与物流', 0),
    ('仓储', 'l2', '交通与物流', 0),
    ('出行服务', 'l2', '交通与物流', 0),
    ('广电', 'l2', '文化与传媒', 0),
    ('出版', 'l2', '文化与传媒', 0),
    ('体育演艺与内容制作', 'l2', '文化与传媒', 0),
    ('旅游', 'l2', '文化与传媒', 0),
    ('会展', 'l2', '文化与传媒', 0),
    ('酒店', 'l2', '文化与传媒', 0),
    ('广告传媒', 'l2', '文化与传媒', 0),
    ('整车制造', 'l2', '制造与工业', 0),
    ('汽车零部件', 'l2', '制造与工业', 0),
    ('汽车销售与服务', 'l2', '制造与工业', 0),
    ('家电电器', 'l2', '制造与工业', 0),
    ('化工', 'l2', '制造与工业', 0),
    ('纺织', 'l2', '制造与工业', 0),
    ('橡胶塑料', 'l2', '制造与工业', 0),
    ('钢铁', 'l2', '制造与工业', 0),
    ('采掘与矿业', 'l2', '制造与工业', 0),
    ('有色金属', 'l2', '制造与工业', 0),
    ('装备制造', 'l2', '制造与工业', 0),
    ('高端装备', 'l2', '制造与工业', 0),
    ('测量测绘', 'l2', '制造与工业', 0),
    ('检测服务', 'l2', '制造与工业', 0),
    ('新材料', 'l2', '制造与工业', 0),
    ('机器人', 'l2', '制造与工业', 0),
    ('航空航天', 'l2', '制造与工业', 0),
    ('海洋装备', 'l2', '制造与工业', 0),
    ('电线电缆', 'l2', '制造与工业', 0),
    ('零售', 'l2', '商贸与消费', 0),
    ('批发', 'l2', '商贸与消费', 0),
    ('贸易', 'l2', '商贸与消费', 0),
    ('日化美妆', 'l2', '商贸与消费', 0),
    ('服装鞋帽', 'l2', '商贸与消费', 0),
    ('珠宝奢侈品', 'l2', '商贸与消费', 0),
    ('酒水饮料', 'l2', '商贸与消费', 0),
    ('粮油食品', 'l2', '商贸与消费', 0),
    ('休闲食品', 'l2', '商贸与消费', 0),
    ('食品加工', 'l2', '商贸与消费', 0),
    ('餐饮', 'l2', '商贸与消费', 0),
    ('农产品加工', 'l2', '商贸与消费', 0),
    ('盐业', 'l2', '商贸与消费', 0),
    ('跨境电商', 'l2', '商贸与消费', 0),
    ('药品生产', 'l2', '医药与健康', 0),
    ('医药流通', 'l2', '医药与健康', 0),
    ('医疗器械', 'l2', '医药与健康', 0),
    ('医院', 'l2', '医药与健康', 0),
    ('医疗康养服务', 'l2', '医药与健康', 0),
    ('生物医药', 'l2', '医药与健康', 0),
    ('医疗研发外包', 'l2', '医药与健康', 0),
    ('医美', 'l2', '医药与健康', 0),
    ('高校院校', 'l2', '教育与科研', 0),
    ('教育培训', 'l2', '教育与科研', 0),
    ('科研院所', 'l2', '教育与科研', 0),
    ('人力资源服务', 'l2', '教育与科研', 0),
    ('生态环保', 'l2', '环保与公用事业', 0),
    ('水务', 'l2', '环保与公用事业', 0),
    ('燃气', 'l2', '环保与公用事业', 0),
    ('农业', 'l2', '农林牧渔', 0),
    ('畜牧业', 'l2', '农林牧渔', 0),
    ('农垦', 'l2', '农林牧渔', 0),
    ('渔业', 'l2', '农林牧渔', 0),
    ('商务服务', 'l2', '商务与专业服务', 0),
    ('资产管理', 'l2', '商务与专业服务', 0),
    ('咨询服务', 'l2', '商务与专业服务', 0),

    ('半导体', 'alias', '信息技术与通信', 0),
    ('集成电路', 'alias', '信息技术与通信', 0),
    ('芯片', 'alias', '信息技术与通信', 0),
    ('软件', 'alias', '信息技术与通信', 0),
    ('信息技术', 'alias', '信息技术与通信', 0),
    ('互联网', 'alias', '信息技术与通信', 0),
    ('通信', 'alias', '信息技术与通信', 0),
    ('大数据', 'alias', '信息技术与通信', 0),
    ('云计算', 'alias', '信息技术与通信', 0),
    ('北斗', 'alias', '信息技术与通信', 0),
    ('卫星应用', 'alias', '信息技术与通信', 0),
    ('光通信', 'alias', '信息技术与通信', 0),
    ('光电子', 'alias', '信息技术与通信', 0),
    ('PCB', 'alias', '信息技术与通信', 0),
    ('电子', 'alias', '信息技术与通信', 0),
    ('工业互联网', 'alias', '信息技术与通信', 0),
    ('医药健康', 'alias', '医药与健康', 0),
    ('医药', 'alias', '医药与健康', 0),
    ('大健康', 'alias', '医药与健康', 0),
    ('医药商业', 'alias', '医药与健康', 0),
    ('生物技术', 'alias', '医药与健康', 0),
    ('生物制药', 'alias', '医药与健康', 0),
    ('制药', 'alias', '医药与健康', 0),
    ('医疗健康', 'alias', '医药与健康', 0),
    ('康养', 'alias', '医药与健康', 0),
    ('新能源', 'alias', '能源', 0),
    ('电力', 'alias', '能源', 0),
    ('动力电池', 'alias', '能源', 0),
    ('电池', 'alias', '能源', 0),
    ('氢能', 'alias', '能源', 0),
    ('食品制造业', 'alias', '商贸与消费', 0),
    ('食品制造', 'alias', '商贸与消费', 0),
    ('食品', 'alias', '商贸与消费', 0),
    ('消费品', 'alias', '商贸与消费', 0),
    ('快速消费品', 'alias', '商贸与消费', 0),
    ('商业流通', 'alias', '商贸与消费', 0),
    ('电商', 'alias', '商贸与消费', 0),
    ('先进制造', 'alias', '制造与工业', 0),
    ('制造业', 'alias', '制造与工业', 0),
    ('有色金属压铸', 'alias', '制造与工业', 0),
    ('汽车', 'alias', '制造与工业', 0),
    ('材料', 'alias', '制造与工业', 0),
    ('精细化工', 'alias', '制造与工业', 0),
    ('低空经济', 'alias', '制造与工业', 0),
    ('无人机', 'alias', '制造与工业', 0),
    ('纺织业', 'alias', '制造与工业', 0),
    ('采矿业', 'alias', '制造与工业', 0),
    ('矿业', 'alias', '制造与工业', 0),
    ('有色金属及矿业', 'alias', '制造与工业', 0),
    ('物流仓储', 'alias', '交通与物流', 0),
    ('物流', 'alias', '交通与物流', 0),
    ('交通基础设施', 'alias', '交通与物流', 0),
    ('交通运输', 'alias', '交通与物流', 0),
    ('建材家居', 'alias', '房地产与建筑', 0),
    ('建材', 'alias', '房地产与建筑', 0),
    ('建筑', 'alias', '房地产与建筑', 0),
    ('工程建设', 'alias', '房地产与建筑', 0),
    ('环保', 'alias', '环保与公用事业', 0),
    ('公用事业', 'alias', '环保与公用事业', 0),
    ('节能环保', 'alias', '环保与公用事业', 0),
    ('企业服务', 'alias', '商务与专业服务', 0),
    ('咨询', 'alias', '商务与专业服务', 0),
    ('文旅消费', 'alias', '文化与传媒', 0),
    ('文化旅游', 'alias', '文化与传媒', 0),
    ('文化传媒', 'alias', '文化与传媒', 0),
    ('传媒', 'alias', '文化与传媒', 0),
    ('文旅', 'alias', '文化与传媒', 0),
    ('体育', 'alias', '文化与传媒', 0),
    ('教育', 'alias', '教育与科研', 0),
    ('教育机构', 'alias', '教育与科研', 0),
    ('职业教育', 'alias', '教育与科研', 0),
    ('金融服务', 'alias', '金融', 0),
    ('国防军工', 'alias', '军工', 0)
) as v(term, level, l1_name, sort_order)
on conflict (team_id, workspace_id, lower(term)) do nothing;

update seller_target st
set industry_l1 = tax.l1_name
from industry_taxonomy tax
where st.industry_primary is not null
  and st.industry_l1 is null
  and tax.active = true
  and lower(tax.term) = lower(st.industry_primary);

update buyer_intent bi
set industries_json = jsonb_build_array(tax.l1_name)
from industry_taxonomy tax
where bi.industry_primary is not null
  and bi.industries_json = '[]'::jsonb
  and tax.active = true
  and lower(tax.term) = lower(bi.industry_primary);

commit;
