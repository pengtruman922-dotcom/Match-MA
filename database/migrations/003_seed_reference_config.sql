-- Match-MA phase 1 reference config seed v0.1
-- Purpose:
-- - Seed lightweight, non-exhaustive dictionaries for phase 1 normalization.
-- - Seed region alias expansion hints for LLM parsing and server-side validation.
-- Notes:
-- - These dictionaries are not meant to be complete industry taxonomies.
-- - Long-tail extracted labels can remain raw or pending_normalization.

begin;

-- ---------------------------------------------------------------------------
-- 1. Primary industry dictionary
-- ---------------------------------------------------------------------------

insert into tag_dictionary (id, team_id, workspace_id, domain, canonical_key, display_name, parent_key, aliases_json, description, is_active, sort_order, metadata_json)
values
  ('00000000-0000-0000-0000-000000010001', null, null, 'industry', 'healthcare', '医药健康 / 生物医药', null, '["医药健康", "生物医药", "医疗健康", "医药", "医疗器械", "制药", "CXO"]'::jsonb, 'Primary industry bucket for healthcare and biopharma targets.', true, 10, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010002', null, null, 'industry', 'new_energy', '新能源 / 清洁能源 / 综合能源', null, '["新能源", "清洁能源", "综合能源", "光伏", "风电", "储能", "充换电", "垃圾发电"]'::jsonb, 'Primary industry bucket for new and clean energy.', true, 20, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010003', null, null, 'industry', 'new_materials_chemical', '新材料 / 化工', null, '["新材料", "化工", "精细化工", "高端化工材料", "铝基材料", "碳纤维", "聚烯烃"]'::jsonb, 'Primary industry bucket for new materials and chemicals.', true, 30, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010004', null, null, 'industry', 'digital_ai_semiconductor_software', '数字经济 / AI / 集成电路 / 软件信息', null, '["数字经济", "人工智能", "AI", "集成电路", "半导体", "软件", "信创", "物联网", "算力"]'::jsonb, 'Primary industry bucket for digital economy, AI, semiconductors and software.', true, 40, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010005', null, null, 'industry', 'agriculture_food', '大农业 / 食品加工', null, '["大农业", "农业", "食品加工", "粮油", "油脂油料", "团餐", "调味品", "种业", "智慧农业"]'::jsonb, 'Primary industry bucket for agriculture and food processing.', true, 50, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010006', null, null, 'industry', 'culture_tourism_consumer', '文旅 / 文体 / IP / 新消费', null, '["文旅", "文体", "IP", "新消费", "老字号", "博物馆", "轻资产运营"]'::jsonb, 'Primary industry bucket for culture, tourism, IP and consumer projects.', true, 60, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010007', null, null, 'industry', 'environmental_circular', '循环经济 / 环保', null, '["循环经济", "环保", "固废", "废水处理", "回收利用", "金属回收", "非金属回收"]'::jsonb, 'Primary industry bucket for environmental protection and circular economy.', true, 70, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010008', null, null, 'industry', 'financial_leasing', '融资租赁', null, '["融资租赁", "租赁"]'::jsonb, 'Primary industry bucket for financial leasing.', true, 80, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010009', null, null, 'industry', 'high_end_equipment_robotics', '高端装备 / 智能制造 / 机器人', null, '["高端装备", "智能制造", "机器人", "工业机器人", "装备制造", "清洁能源装备", "电力设备"]'::jsonb, 'Primary industry bucket for high-end equipment and robotics.', true, 90, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010010', null, null, 'industry', 'automotive_parts', '汽车零部件', null, '["汽车零部件", "汽配", "汽车配套"]'::jsonb, 'Primary industry bucket for automotive parts.', true, 100, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010011', null, null, 'industry', 'marine_ocean_engineering', '海洋产业 / 海工装备', null, '["海洋产业", "海工装备", "海洋装备", "海工", "海洋基金"]'::jsonb, 'Primary industry bucket for marine and ocean engineering.', true, 110, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010012', null, null, 'industry', 'engineering_infrastructure', '工程设备 / 基础设施服务', null, '["工程设备", "基础设施服务", "工程设备制造", "维护监测", "基础设施"]'::jsonb, 'Primary industry bucket for engineering equipment and infrastructure services.', true, 120, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010013', null, null, 'industry', 'supply_chain_cross_border', '供应链 / 国际贸易 / 跨境电商', null, '["供应链", "国际贸易", "跨境电商", "外贸"]'::jsonb, 'Primary industry bucket for supply chain and cross-border commerce.', true, 130, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010014', null, null, 'industry', 'low_altitude_aerospace', '低空经济 / 航空航天', null, '["低空经济", "航空航天", "无人机", "反无人机", "飞控", "北斗", "飞机维修"]'::jsonb, 'Primary industry bucket for low-altitude economy and aerospace.', true, 140, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010015', null, null, 'industry', 'urban_renewal_building_materials', '城市更新 / 新型建材', null, '["城市更新", "新型建材", "建材", "旧商圈激活"]'::jsonb, 'Primary industry bucket for urban renewal and building materials.', true, 150, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010016', null, null, 'industry', 'bio_manufacturing', '生物制造', null, '["生物制造", "合成生物", "生物制造产业链"]'::jsonb, 'Primary industry bucket for bio-manufacturing.', true, 160, '{"level": "primary"}'::jsonb),
  ('00000000-0000-0000-0000-000000010017', null, null, 'industry', 'traditional_manufacturing', '传统制造业 / 实体产业', null, '["传统制造业", "实体产业", "制造业", "重资产", "总装"]'::jsonb, 'Primary industry bucket for traditional manufacturing and real-economy assets.', true, 170, '{"level": "primary"}'::jsonb)
on conflict (id) do update set
  team_id = excluded.team_id,
  workspace_id = excluded.workspace_id,
  domain = excluded.domain,
  canonical_key = excluded.canonical_key,
  display_name = excluded.display_name,
  parent_key = excluded.parent_key,
  aliases_json = excluded.aliases_json,
  description = excluded.description,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order,
  metadata_json = excluded.metadata_json,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- 2. Transaction dictionaries
-- ---------------------------------------------------------------------------

insert into tag_dictionary (id, team_id, workspace_id, domain, canonical_key, display_name, parent_key, aliases_json, description, is_active, sort_order)
values
  ('00000000-0000-0000-0000-000000020001', null, null, 'deal_path', 'equity_transfer', '股权转让', null, '["老股转让", "股转", "收老股"]'::jsonb, 'Acquire shares through existing shareholder transfer.', true, 10),
  ('00000000-0000-0000-0000-000000020002', null, null, 'deal_path', 'capital_increase', '增资', null, '["增资扩股", "增资入股"]'::jsonb, 'Acquire or invest through capital increase.', true, 20),
  ('00000000-0000-0000-0000-000000020003', null, null, 'deal_path', 'asset_acquisition', '资产收购', null, '["资产包收购", "业务资产收购"]'::jsonb, 'Acquire assets rather than equity.', true, 30),
  ('00000000-0000-0000-0000-000000020004', null, null, 'deal_path', 'share_swap', '换股', null, '["股份支付", "发行股份购买资产"]'::jsonb, 'Share swap or share-based acquisition.', true, 40),
  ('00000000-0000-0000-0000-000000020005', null, null, 'deal_path', 'cash_and_share', '现金加股份', null, '["现金+股份", "现金加股票"]'::jsonb, 'Mixed cash and share consideration.', true, 50),
  ('00000000-0000-0000-0000-000000020006', null, null, 'deal_path', 'backdoor_listing', '借壳 / 重组上市', null, '["借壳", "壳资源", "重组上市"]'::jsonb, 'Backdoor listing or restructuring listing path.', true, 60),
  ('00000000-0000-0000-0000-000000020007', null, null, 'deal_path', 'voting_right_delegation', '表决权委托', null, '["表决权委托", "表决权安排"]'::jsonb, 'Control via voting right delegation.', true, 70),
  ('00000000-0000-0000-0000-000000020008', null, null, 'deal_path', 'concert_party', '一致行动', null, '["一致行动协议", "一致行动人"]'::jsonb, 'Control via concert party agreement.', true, 80),
  ('00000000-0000-0000-0000-000000020009', null, null, 'deal_path', 'board_control', '董事会控制', null, '["董事会席位", "董事会多数"]'::jsonb, 'Control through board composition.', true, 90),
  ('00000000-0000-0000-0000-000000020010', null, null, 'deal_path', 'mixed', '组合交易', null, '["组合方案", "混合交易"]'::jsonb, 'Combined transaction structure.', true, 100),
  ('00000000-0000-0000-0000-000000020011', null, null, 'deal_path', 'other', '其他交易路径', null, '["其他"]'::jsonb, 'Fallback deal path.', true, 9999),
  ('00000000-0000-0000-0000-000000021001', null, null, 'payment_method', 'cash', '现金', null, '["现金支付"]'::jsonb, 'Cash consideration.', true, 10),
  ('00000000-0000-0000-0000-000000021002', null, null, 'payment_method', 'share', '股份', null, '["股份支付", "股票支付"]'::jsonb, 'Share consideration.', true, 20),
  ('00000000-0000-0000-0000-000000021003', null, null, 'payment_method', 'cash_and_share', '现金加股份', null, '["现金+股份"]'::jsonb, 'Mixed cash and share consideration.', true, 30),
  ('00000000-0000-0000-0000-000000021004', null, null, 'payment_method', 'debt_assumption', '承债', null, '["债务承接", "承接债务"]'::jsonb, 'Debt assumption as consideration or structure.', true, 40),
  ('00000000-0000-0000-0000-000000021005', null, null, 'payment_method', 'installment', '分期支付', null, '["分期", "分期付款"]'::jsonb, 'Installment payment.', true, 50),
  ('00000000-0000-0000-0000-000000021006', null, null, 'payment_method', 'mixed', '组合支付', null, '["混合支付", "组合支付"]'::jsonb, 'Mixed consideration.', true, 60),
  ('00000000-0000-0000-0000-000000021007', null, null, 'payment_method', 'other', '其他支付方式', null, '["其他"]'::jsonb, 'Fallback payment method.', true, 9999),
  ('00000000-0000-0000-0000-000000022001', null, null, 'control_path', 'equity_control', '股权控股', null, '["股权控制", "控股权"]'::jsonb, 'Control through majority or controlling equity.', true, 10),
  ('00000000-0000-0000-0000-000000022002', null, null, 'control_path', 'voting_right_delegation', '表决权委托', null, '["表决权委托", "表决权安排"]'::jsonb, 'Control through voting right delegation.', true, 20),
  ('00000000-0000-0000-0000-000000022003', null, null, 'control_path', 'concert_party', '一致行动', null, '["一致行动协议", "一致行动人"]'::jsonb, 'Control through concert party arrangements.', true, 30),
  ('00000000-0000-0000-0000-000000022004', null, null, 'control_path', 'board_control', '董事会控制', null, '["董事会席位", "董事会多数"]'::jsonb, 'Control through board rights.', true, 40),
  ('00000000-0000-0000-0000-000000022005', null, null, 'control_path', 'agreement_control', '协议控制', null, '["协议安排", "控制协议"]'::jsonb, 'Control through contractual arrangements.', true, 50),
  ('00000000-0000-0000-0000-000000022006', null, null, 'control_path', 'capital_increase_plus_old_share', '增资加老股', null, '["增资+老股", "增资加股转"]'::jsonb, 'Control through capital increase plus old-share transfer.', true, 60),
  ('00000000-0000-0000-0000-000000022007', null, null, 'control_path', 'other', '其他控制路径', null, '["其他"]'::jsonb, 'Fallback control path.', true, 9999)
on conflict (id) do update set
  team_id = excluded.team_id,
  workspace_id = excluded.workspace_id,
  domain = excluded.domain,
  canonical_key = excluded.canonical_key,
  display_name = excluded.display_name,
  parent_key = excluded.parent_key,
  aliases_json = excluded.aliases_json,
  description = excluded.description,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- 3. P0 risk dictionary
-- ---------------------------------------------------------------------------

insert into tag_dictionary (id, team_id, workspace_id, domain, canonical_key, display_name, parent_key, aliases_json, description, is_active, sort_order)
values
  ('00000000-0000-0000-0000-000000030001', null, null, 'risk', 'litigation', '诉讼风险', 'legal', '["涉诉", "重大诉讼", "合同纠纷", "无诉讼"]'::jsonb, 'Pending or material litigation risk.', true, 10),
  ('00000000-0000-0000-0000-000000030002', null, null, 'risk', 'arbitration', '仲裁风险', 'legal', '["仲裁", "仲裁纠纷"]'::jsonb, 'Arbitration case risk.', true, 20),
  ('00000000-0000-0000-0000-000000030003', null, null, 'risk', 'enforcement', '被执行风险', 'legal', '["被执行", "执行案件", "执行风险"]'::jsonb, 'Court enforcement risk.', true, 30),
  ('00000000-0000-0000-0000-000000030004', null, null, 'risk', 'dishonest_debtor', '失信被执行', 'legal', '["失信", "老赖", "失信被执行人"]'::jsonb, 'Dishonest debtor risk.', true, 40),
  ('00000000-0000-0000-0000-000000030005', null, null, 'risk', 'asset_freeze', '资产冻结', 'legal', '["冻结", "查封", "股权冻结", "账户冻结"]'::jsonb, 'Asset, equity or account freeze risk.', true, 50),
  ('00000000-0000-0000-0000-000000030006', null, null, 'risk', 'equity_pledge', '股权质押', 'legal', '["股权质押", "高质押", "质押比例"]'::jsonb, 'High or abnormal equity pledge risk.', true, 60),
  ('00000000-0000-0000-0000-000000030007', null, null, 'risk', 'regulatory_violation', '违法违规', 'compliance', '["违法违规", "行政处罚", "重大违法"]'::jsonb, 'Regulatory violation or administrative penalty risk.', true, 70),
  ('00000000-0000-0000-0000-000000030008', null, null, 'risk', 'environmental', '环保风险', 'compliance', '["环保风险", "环保处罚", "环评", "排污"]'::jsonb, 'Environmental compliance risk.', true, 80),
  ('00000000-0000-0000-0000-000000030009', null, null, 'risk', 'safety_production', '安全生产风险', 'compliance', '["安全生产", "安全事故", "安全生产处罚"]'::jsonb, 'Safety production accident or penalty risk.', true, 90),
  ('00000000-0000-0000-0000-000000030010', null, null, 'risk', 'tax', '税务风险', 'compliance', '["税务风险", "欠税", "税务处罚", "税务争议"]'::jsonb, 'Tax penalty, arrears or dispute risk.', true, 100),
  ('00000000-0000-0000-0000-000000030011', null, null, 'risk', 'data_compliance', '数据合规风险', 'compliance', '["数据合规", "隐私风险", "数据安全"]'::jsonb, 'Data security and privacy compliance risk.', true, 110),
  ('00000000-0000-0000-0000-000000030012', null, null, 'risk', 'license_or_permit', '资质许可风险', 'compliance', '["资质不全", "许可证", "牌照", "许可缺失"]'::jsonb, 'Missing, expired or revoked key license risk.', true, 120),
  ('00000000-0000-0000-0000-000000030013', null, null, 'risk', 'high_debt_ratio', '高负债', 'financial', '["高负债", "负债率高"]'::jsonb, 'Debt ratio exceeds buyer tolerance.', true, 130),
  ('00000000-0000-0000-0000-000000030014', null, null, 'risk', 'debt_repayment', '偿债风险', 'financial', '["偿债风险", "债务压力", "到期债务"]'::jsonb, 'Debt repayment or liquidity pressure risk.', true, 140),
  ('00000000-0000-0000-0000-000000030015', null, null, 'risk', 'cash_flow', '现金流风险', 'financial', '["现金流差", "现金流不稳定", "经营现金流为负"]'::jsonb, 'Unstable or negative operating cash flow risk.', true, 150),
  ('00000000-0000-0000-0000-000000030016', null, null, 'risk', 'loss_making', '亏损风险', 'financial', '["亏损", "利润为负", "连续亏损", "不接受亏损"]'::jsonb, 'Loss-making or negative-profit risk.', true, 160),
  ('00000000-0000-0000-0000-000000030017', null, null, 'risk', 'audit_opinion', '审计意见异常', 'financial', '["非标审计意见", "保留意见", "无法表示意见"]'::jsonb, 'Modified audit opinion risk.', true, 170),
  ('00000000-0000-0000-0000-000000030018', null, null, 'risk', 'financial_fraud', '财务造假风险', 'financial', '["财务造假", "报表不实", "财务真实性"]'::jsonb, 'Financial fraud or statement reliability risk.', true, 180),
  ('00000000-0000-0000-0000-000000030019', null, null, 'risk', 'goodwill_impairment', '商誉减值风险', 'financial', '["商誉减值", "大额商誉"]'::jsonb, 'Goodwill impairment risk.', true, 190),
  ('00000000-0000-0000-0000-000000030020', null, null, 'risk', 'st_status', 'ST 风险', 'capital_market', '["ST", "*ST", "可能ST"]'::jsonb, 'ST or possible ST status risk.', true, 200),
  ('00000000-0000-0000-0000-000000030021', null, null, 'risk', 'delisting', '退市风险', 'capital_market', '["退市", "退市风险", "退市整理"]'::jsonb, 'Delisting risk.', true, 210),
  ('00000000-0000-0000-0000-000000030022', null, null, 'risk', 'share_price_abnormal', '股价异常风险', 'capital_market', '["股价异常", "异常波动", "操纵疑虑"]'::jsonb, 'Abnormal share price volatility risk.', true, 220),
  ('00000000-0000-0000-0000-000000030023', null, null, 'risk', 'major_shareholder_risk', '大股东风险', 'capital_market', '["大股东风险", "控股股东占款", "大股东违规"]'::jsonb, 'Controlling shareholder pledge, occupation or violation risk.', true, 230),
  ('00000000-0000-0000-0000-000000030024', null, null, 'risk', 'operation_stability', '经营稳定性风险', 'operation', '["经营不稳定", "业务不可持续", "经营稳定性"]'::jsonb, 'Business operation stability risk.', true, 240),
  ('00000000-0000-0000-0000-000000030025', null, null, 'risk', 'customer_concentration', '客户集中风险', 'operation', '["客户集中", "单一客户依赖", "大客户依赖"]'::jsonb, 'Customer concentration risk.', true, 250),
  ('00000000-0000-0000-0000-000000030026', null, null, 'risk', 'supplier_concentration', '供应商集中风险', 'operation', '["供应商集中", "供应链风险", "关键供应商"]'::jsonb, 'Supplier concentration risk.', true, 260),
  ('00000000-0000-0000-0000-000000030027', null, null, 'risk', 'technology_obsolescence', '技术过时风险', 'operation', '["技术过时", "技术落后", "技术路线落后"]'::jsonb, 'Technology obsolescence risk.', true, 270),
  ('00000000-0000-0000-0000-000000030028', null, null, 'risk', 'overcapacity', '产能过剩风险', 'operation', '["产能过剩", "过剩产能"]'::jsonb, 'Overcapacity risk.', true, 280),
  ('00000000-0000-0000-0000-000000030029', null, null, 'risk', 'cyclical_industry', '周期行业风险', 'operation', '["周期行业", "周期性强"]'::jsonb, 'Cyclical industry risk.', true, 290),
  ('00000000-0000-0000-0000-000000030030', null, null, 'risk', 'market_decline', '市场下滑风险', 'operation', '["市场下滑", "需求下滑", "市场萎缩"]'::jsonb, 'Market decline or downstream demand risk.', true, 300),
  ('00000000-0000-0000-0000-000000030031', null, null, 'risk', 'control_uncertainty', '控制权不确定', 'transaction', '["控制权不清晰", "控股不确定", "表决权不确定"]'::jsonb, 'Unclear path to control.', true, 310),
  ('00000000-0000-0000-0000-000000030032', null, null, 'risk', 'consolidation_uncertainty', '并表不确定', 'transaction', '["无法并表", "并表不确定", "并表路径不明确"]'::jsonb, 'Unclear accounting consolidation path.', true, 320),
  ('00000000-0000-0000-0000-000000030033', null, null, 'risk', 'ownership_dispute', '权属纠纷', 'transaction', '["权属不清", "产权纠纷", "股权纠纷", "资产权属"]'::jsonb, 'Equity, asset, land or IP ownership dispute.', true, 330),
  ('00000000-0000-0000-0000-000000030034', null, null, 'risk', 'related_party_transaction', '关联交易风险', 'transaction', '["关联交易", "关联交易占比"]'::jsonb, 'Related-party transaction risk.', true, 340),
  ('00000000-0000-0000-0000-000000030035', null, null, 'risk', 'earnout_dependency', '对赌依赖风险', 'transaction', '["对赌", "业绩承诺", "依赖对赌"]'::jsonb, 'High dependency on earnout or valuation adjustment.', true, 350),
  ('00000000-0000-0000-0000-000000030036', null, null, 'risk', 'management_instability', '管理团队不稳定', 'transaction', '["团队不稳定", "核心团队流失", "管理层不稳定"]'::jsonb, 'Management or core team instability risk.', true, 360),
  ('00000000-0000-0000-0000-000000030037', null, null, 'risk', 'other', '其他风险', 'other', '["其他风险", "未归类风险"]'::jsonb, 'Fallback risk category.', true, 9999)
on conflict (id) do update set
  team_id = excluded.team_id,
  workspace_id = excluded.workspace_id,
  domain = excluded.domain,
  canonical_key = excluded.canonical_key,
  display_name = excluded.display_name,
  parent_key = excluded.parent_key,
  aliases_json = excluded.aliases_json,
  description = excluded.description,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- 4. Region alias config
-- ---------------------------------------------------------------------------

insert into region_alias_config (id, team_id, workspace_id, alias_text, expanded_regions_json, region_level, description, is_active, sort_order)
values
  ('00000000-0000-0000-0000-000000040001', null, null, '长三角', '[{"province":"上海市"},{"province":"江苏省"},{"province":"浙江省"},{"province":"安徽省"}]'::jsonb, 'province', 'Default expansion for Yangtze River Delta. Can be overridden per team/workspace.', true, 10),
  ('00000000-0000-0000-0000-000000040002', null, null, '江浙沪', '[{"province":"江苏省"},{"province":"浙江省"},{"province":"上海市"}]'::jsonb, 'province', 'Common region expression for Jiangsu, Zhejiang and Shanghai.', true, 20),
  ('00000000-0000-0000-0000-000000040003', null, null, '江浙', '[{"province":"江苏省"},{"province":"浙江省"}]'::jsonb, 'province', 'Common region expression for Jiangsu and Zhejiang.', true, 30),
  ('00000000-0000-0000-0000-000000040004', null, null, '珠三角', '[{"province":"广东省","city":"广州市"},{"province":"广东省","city":"深圳市"},{"province":"广东省","city":"佛山市"},{"province":"广东省","city":"东莞市"},{"province":"广东省","city":"珠海市"},{"province":"广东省","city":"中山市"},{"province":"广东省","city":"惠州市"},{"province":"广东省","city":"江门市"},{"province":"广东省","city":"肇庆市"}]'::jsonb, 'city', 'Default Pearl River Delta city-level expansion.', true, 40),
  ('00000000-0000-0000-0000-000000040005', null, null, '沿海发达地区', '[{"province":"上海市"},{"province":"江苏省"},{"province":"浙江省"},{"province":"福建省"},{"province":"广东省"},{"province":"山东省"}]'::jsonb, 'province', 'Loose business shorthand. Should be treated as a preference unless buyer wording makes it hard.', true, 50)
on conflict (id) do update set
  team_id = excluded.team_id,
  workspace_id = excluded.workspace_id,
  alias_text = excluded.alias_text,
  expanded_regions_json = excluded.expanded_regions_json,
  region_level = excluded.region_level,
  description = excluded.description,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order,
  updated_at = now();

commit;
