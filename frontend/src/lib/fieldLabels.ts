export type EntityType = 'seller_target' | 'buyer_intent' | 'buyer_party' | 'buyer_seller_relation' | string;

const SELLER_TARGET_FIELD_LABELS: Record<string, string> = {
  target_name: '标的名称',
  target_type: '标的类型',
  target_subject_name: '标的主体',
  target_grade: '标的级别',
  lifecycle_status: '交易状态',
  information_status: '信息状态',
  industry_l1: '行业大类',
  industry_l2: '细分赛道',
  industry_pairs_json: '所属行业',
  location_province: '所在省',
  location_city: '所在市',
  location_district: '所在区',
  listed_status: '上市状态',
  market_cap_yuan: '市值',
  current_revenue_yuan: '当前营收',
  current_net_profit_yuan: '当前净利润',
  current_total_profit_yuan: '当前利润总额',
  current_assets_yuan: '当前总资产',
  current_debt_ratio: '当前负债率',
  current_operating_cash_flow_yuan: '经营现金流',
  financial_period_label: '财务期间',
  financial_period_end_date: '财务期间截止日',
  profitability_status: '盈利状态',
  cash_flow_status: '现金流状态',
  main_products_text: '主要产品',
  stock_code: '股票代码',
  major_risk_flags_json: '重大风险',
  acceptable_transaction_structures_json: '可接受交易结构',
  valuation_yuan: '估值',
  valuation_date: '估值时间',
  asking_price_yuan: '报价',
  asking_price_date: '报价时间',
  pe_ratio: '市盈率',
  pe_source_type: 'PE 来源',
  premium_rate: '溢价率',
  is_for_sale: '是否出售',
  can_control: '可控股',
  can_consolidate: '可并表',
  accepts_minority_investment: '接受少数股权',
  transfer_ratio_min: '出售比例下限',
  transfer_ratio_max: '出售比例上限',
  transfer_ratio_text: '出售比例说明',
  accepts_relocation: '接受迁址',
  accepts_return_investment: '接受返投',
  management_retention_possible: '管理层可留任',
  business_summary: '业务摘要',
  transaction_summary: '交易摘要',
  risk_summary: '风险摘要',
  gap_summary: '信息缺口',
  deleted_at: '删除时间',
};

const BUYER_PARTY_FIELD_LABELS: Record<string, string> = {
  buyer_name: '买家名称',
  aliases_json: '别名',
  industries_json: '所属行业',
  industry_l2_json: '所属细分行业',
  region_province: '所在省份',
  region_city: '所在城市',
  contact_name: '联系人',
  contact_info_json: '联系方式',
  notes: '备注',
  status: '状态',
  deleted_at: '删除时间',
};

const BUYER_INTENT_FIELD_LABELS: Record<string, string> = {
  intent_name: '意向名称',
  intent_grade: '需求级别',
  status: '推荐状态',
  pause_reason: '暂停原因',
  contact_name: '联系人',
  contact_info_json: '联系方式',
  raw_requirement_text: '原始需求',
  intent_summary: '意向摘要',
  parsed_requirement_json: '结构化需求',
  industry_primary: '一级行业',
  industry_secondary: '二级行业',
  industries_json: '关注行业',
  excluded_industries_json: '排除行业',
  industry_focus_tags_json: '细分赛道',
  region_scope_summary: '区域范围',
  region_constraints_json: '区域约束',
  min_revenue_yuan: '最低营收',
  min_net_profit_yuan: '最低净利润',
  min_total_profit_yuan: '最低利润总额',
  max_pe: '最高 PE',
  max_ps: '最高 PS',
  min_net_margin: '最低净利率',
  min_gross_margin: '最低毛利率',
  min_valuation_yuan: '最低估值',
  max_valuation_yuan: '最高估值',
  min_market_cap_yuan: '最低市值',
  max_market_cap_yuan: '最高市值',
  market_cap_range_summary: '市值范围',
  requires_control: '要求控股',
  requires_consolidation: '要求并表',
  accepts_minority_investment: '接受少数股权',
  desired_equity_ratio_min: '期望持股下限',
  desired_equity_ratio_max: '期望持股上限',
  equity_ratio_summary: '股权比例要求',
  equity_requirement_type: '股权要求类型',
  acceptable_control_paths_json: '可接受控制路径',
  preferred_listed_status: '偏好上市状态',
  listing_board_requirement_summary: '板块要求',
  industry_l2_json: '关注细分赛道',
  budget_min_yuan: '出资预算下限',
  budget_max_yuan: '出资预算上限',
  acceptable_cash_flow_status_json: '可接受现金流状态',
  acceptable_profitability_status_json: '可接受盈利状态',
  requires_relocation: '迁址要求',
  relocation_target_regions_json: '迁址目标地区',
  requires_return_investment: '返投要求',
  return_investment_multiple: '返投倍数',
  requires_team_retention: '团队留任要求',
  earnout_requirement: '对赌要求',
  listing_market_region: '上市地要求',
  financing_stage_requirement_summary: '融资阶段要求',
  transaction_type: '交易方式原文',
  transaction_types_json: '可接受交易结构',
  premium_tolerance_summary: '溢价容忍度',
  max_premium_rate: '最高溢价率',
  max_debt_ratio: '最高负债率',
  debt_ratio_requirement_summary: '负债率要求',
  major_risk_tolerance_summary: '风险容忍度',
  unacceptable_risk_flags_json: '不接受的重大风险',
  buyer_industry_advantage_summary: '买方产业优势',
  deleted_at: '删除时间',
};

const RELATION_FIELD_LABELS: Record<string, string> = {
  status: '关系状态',
  status_reason: '状态原因',
  first_recommended_at: '首次推荐时间',
  last_contact_at: '最近接触时间',
  last_event_at: '最近进展时间',
  last_event_summary: '最近进展摘要',
};



Object.assign(BUYER_PARTY_FIELD_LABELS, {
  buyer_name: '买家名称',
  aliases_json: '别名',
  industries_json: '所属行业',
  industry_l2_json: '所属细分行业',
  region_province: '所在省份',
  region_city: '所在城市',
  contact_name: '联系人',
  contact_info_json: '联系方式',
  notes: '备注',
  status: '状态',
  deleted_at: '删除时间',
});

Object.assign(BUYER_INTENT_FIELD_LABELS, {
  buyer_party_id: '关联买家',
  intent_name: '意向名称',
  intent_grade: '需求级别',
  status: '推荐状态',
  pause_reason: '暂停原因',
  contact_name: '联系人',
  contact_info_json: '联系方式',
  raw_requirement_text: '原始需求',
  intent_summary: '意向摘要',
  parsed_requirement_json: '结构化需求',
  industry_primary: '一级行业',
  industry_secondary: '二级行业',
  industries_json: '关注行业',
  excluded_industries_json: '排除行业',
  industry_focus_tags_json: '细分赛道',
  region_scope_summary: '区域范围',
  region_constraints_json: '区域约束',
  min_revenue_yuan: '最低营收',
  min_net_profit_yuan: '最低净利润',
  min_total_profit_yuan: '最低利润总额',
  max_pe: '最高PE',
  max_ps: '最高PS',
  min_net_margin: '最低净利率',
  min_gross_margin: '最低毛利率',
  min_valuation_yuan: '最低估值',
  max_valuation_yuan: '最高估值',
  min_market_cap_yuan: '最低市值',
  max_market_cap_yuan: '最高市值',
  market_cap_range_summary: '市值范围',
  requires_control: '要求控股',
  requires_consolidation: '要求并表',
  accepts_minority_investment: '接受少数股权',
  desired_equity_ratio_min: '期望持股下限',
  desired_equity_ratio_max: '期望持股上限',
  equity_ratio_summary: '股权比例要求',
  equity_requirement_type: '股权要求类型',
  acceptable_control_paths_json: '可接受控制路径',
  preferred_listed_status: '偏好上市状态',
  listing_board_requirement_summary: '板块要求',
  industry_l2_json: '关注细分赛道',
  budget_min_yuan: '出资预算下限',
  budget_max_yuan: '出资预算上限',
  acceptable_cash_flow_status_json: '可接受现金流状态',
  acceptable_profitability_status_json: '可接受盈利状态',
  requires_relocation: '迁址要求',
  relocation_target_regions_json: '迁址目标地区',
  requires_return_investment: '返投要求',
  return_investment_multiple: '返投倍数',
  requires_team_retention: '团队留任要求',
  earnout_requirement: '对赌要求',
  listing_market_region: '上市地要求',
  financing_stage_requirement_summary: '融资阶段要求',
  transaction_type: '交易方式原文',
  transaction_types_json: '可接受交易结构',
  premium_tolerance_summary: '溢价容忍度',
  max_premium_rate: '最高溢价率',
  max_debt_ratio: '最高负债率',
  debt_ratio_requirement_summary: '负债率要求',
  major_risk_tolerance_summary: '风险容忍度',
  unacceptable_risk_flags_json: '不接受的重大风险',
  buyer_industry_advantage_summary: '买方产业优势',
  deleted_at: '删除时间',
});

const FIELD_LABELS_BY_ENTITY: Record<string, Record<string, string>> = {
  seller_target: SELLER_TARGET_FIELD_LABELS,
  buyer_party: BUYER_PARTY_FIELD_LABELS,
  buyer_intent: BUYER_INTENT_FIELD_LABELS,
  buyer_seller_relation: RELATION_FIELD_LABELS,
};

// 匹配画像不是实体的列，在更新记录里以 profile_section.<code> 的形式出现。
const PROFILE_SECTION_FIELD_PREFIX = 'profile_section.';

// 退役栏目码（chain_position / tech_team / sell_intent_risk）保留在表里：
// 更新记录会翻出改栏之前的历史条目，那时它们就叫这个名字。
const PROFILE_SECTION_LABELS: Record<string, string> = {
  business_product: '产业优势',
  chain_position: '产业链位置与行业地位',
  tech_team: '技术与团队',
  ops_quality: '经营质量',
  deal_terms: '交易属性与配合度',
  sell_intent_risk: '出售诉求与风险缺口',
  intent_scope: '行业与地区·其他',
  intent_financial: '经营与财务·其他',
  intent_deal: '交易与能力要求·其他',
};

const PROFILE_INFO_STATUS_LABELS: Record<string, string> = {
  filled: '',
  not_found: '（暂无信息）',
  not_applicable: '（不适用）',
};

function profileSectionValueLabel(value: unknown): string {
  if (typeof value !== 'object' || value === null) return String(value);
  const row = value as { info_status?: string; content_text?: string };
  const status = PROFILE_INFO_STATUS_LABELS[row.info_status || 'filled'];
  return (row.content_text || '').trim() || status || '-';
}

export function fieldLabel(entityType: EntityType, fieldPath: string): string {
  if (fieldPath.startsWith(PROFILE_SECTION_FIELD_PREFIX)) {
    const code = fieldPath.slice(PROFILE_SECTION_FIELD_PREFIX.length);
    return `画像·${PROFILE_SECTION_LABELS[code] || code}`;
  }
  return FIELD_LABELS_BY_ENTITY[entityType]?.[fieldPath] || fieldPath;
}

const REQUIREMENT_STRENGTH_LABELS = {
  required: '必须满足',
  preferred: '优先/加分',
  not_required: '不作要求',
  unknown: '未提及',
};

const VALUE_LABELS: Record<string, Record<string, string>> = {
  requires_relocation: REQUIREMENT_STRENGTH_LABELS,
  requires_return_investment: REQUIREMENT_STRENGTH_LABELS,
  requires_team_retention: REQUIREMENT_STRENGTH_LABELS,
  earnout_requirement: REQUIREMENT_STRENGTH_LABELS,
  // 上市地：2026-08-07 从境内/境外换成具体交易所，与后端 _LISTING_EXCHANGE 同源。
  // 标的信息页走注册表的 enum_options 自动出中文，这张表只服务买家侧。
  listing_market_region: {
    sse: '上交所',
    szse: '深交所',
    bse: '北交所',
    hkex: '港交所',
    nyse: '纽交所',
    nasdaq: '纳斯达克',
    other: '其他',
    unknown: '未知',
  },
  target_type: {
    company: '公司',
    equity_package: '股权包',
    business_unit: '业务单元',
    asset_package: '资产包',
    project: '项目',
    other: '其他',
  },
  listed_status: {
    listed: '已上市',
    unlisted: '未上市',
    pre_ipo: '拟上市',
    unknown: '未知',
  },
  // 级别 A-E 没有中文别名，值就是标签，所以 target_grade / intent_grade 不进这张表。
  // 这两组是 E 的细分原因，更新记录里仍要显示中文。
  lifecycle_status: {
    active: '在售中',
    sold: '已售出',
    off_market: '已停售',
  },
  information_status: {
    normal: '已更新',
    insufficient: '待补充',
    pending_review: '待复核',
    parsing: '解析中',
    researching: '调研中',
    parse_failed: '解析失败',
  },
  yes_no_like: {
    yes: '是',
    likely: '可能',
    no: '否',
    unknown: '未知',
  },
  profitability_status: {
    profitable: '盈利',
    loss_making: '亏损',
    break_even: '盈亏平衡',
    unknown: '未知',
  },
  cash_flow_status: {
    stable_positive: '稳定为正',
    positive: '为正',
    negative: '为负',
    unstable: '不稳定',
    unknown: '未知',
  },
  major_risk_flags_json: {
    litigation: '涉诉',
    equity_frozen: '股权冻结',
    enforcement: '被执行',
    violation: '违规违法',
    none: '已核查无重大风险',
  },
  acceptable_transaction_structures_json: {
    equity_transfer: '股权转让（老股）',
    capital_increase: '增资扩股（新股）',
    asset_purchase: '资产收购',
    merger: '吸收合并',
    other: '其他',
  },
};

const YES_NO_LIKE_FIELDS = new Set([
  'is_for_sale',
  'can_control',
  'can_consolidate',
  'accepts_minority_investment',
  'accepts_relocation',
  'accepts_return_investment',
  'management_retention_possible',
  'requires_control',
  'requires_consolidation',
]);


Object.assign(VALUE_LABELS, {
  status: {
    active: '活跃',
    paused: '暂停',
    archived: '已归档',
    merged: '已合并',
    completed: '已完成',
  },
  buyer_party_status: {
    active: '活跃',
    archived: '已归档',
    merged: '已合并',
  },
  buyer_intent_status: {
    active: '持续推荐',
    paused: '暂停推荐',
    closed: '结束推荐',
  },
  preferred_listed_status: {
    listed: '已上市',
    unlisted: '未上市',
    pre_ipo: '拟上市',
    any: '均可',
    unknown: '未知',
  },
  listed_status: {
    listed: '已上市',
    unlisted: '未上市',
    pre_ipo: '拟上市',
    unknown: '未知',
  },
  equity_requirement_type: {
    control_required: '要求控股',
    consolidation_required: '要求并表',
    minority_acceptable: '接受少数股权',
    minority_only: '仅少数股权',
    flexible: '灵活可谈',
    specific_range: '指定比例',
    unknown: '未知',
  },
});

export function valueLabel(fieldPath: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (Array.isArray(value)) return value.length ? value.map((item) => valueLabel(fieldPath, item)).join('、') : '-';
  if (fieldPath.startsWith(PROFILE_SECTION_FIELD_PREFIX)) return profileSectionValueLabel(value);
  if (typeof value === 'object') return JSON.stringify(value);

  const text = String(value);
  const mapKey = YES_NO_LIKE_FIELDS.has(fieldPath) ? 'yes_no_like' : fieldPath;
  return VALUE_LABELS[mapKey]?.[text] || text;
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  direct_api: '手动编辑',
  seller_target_parse: '标的解析',
  business_update_extractor: '业务更新解析',
  relation_followup_draft_parser: '推进跟进整理',
  update_log_rollback: '更新回滚',
  rollback: '回滚',
};


Object.assign(SOURCE_TYPE_LABELS, {
  direct_api: '手动编辑',
  manual: '手动编辑',
  seller_target_parse: '标的解析',
  buyer_intent_parse: '买家意向解析',
  business_update_extractor: '业务更新解析',
  user_attachment: '附件解析',
  research_proposal: 'AI调研',
  update_log_rollback: '更新回滚',
  rollback: '回滚',
});

export function sourceTypeLabel(sourceType: string | null | undefined): string {
  if (!sourceType) return '-';
  return SOURCE_TYPE_LABELS[sourceType] || sourceType;
}
