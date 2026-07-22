import type { SellerTarget } from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';

/**
 * 标的信息的分组定义：结构化字段和定性画像按同一套业务大类排列。
 *
 * 分组刻意与画像六栏对齐（画像本就是按业务维度切的），另加一个身份与地区组。
 * 这样顾问看一个大类时，能同时看到「这一维度有哪些硬数据」和
 * 「结构化字段装不下的那部分怎么说」，而不是在两个 tab 之间对照。
 */

/**
 * screening = 该字段参与 SQL 硬筛或软打分。
 *
 * 这个标注不是装饰：补一个利润数字可能把标的从「未知」推进候选池，
 * 补一段业务描述只影响深评措辞。顾问需要知道哪些空缺值得先花时间。
 * 判定依据是 recommendation_flow 里实际读取的字段，
 * 加上 CAPABILITY_DIMENSIONS 映射的三个能力字段。
 */
export type InfoField = {
  /** 对应的列名。tests/test_info_group_sync.py 靠它比对「筛」角标是否与打分器一致。 */
  field: string;
  label: string;
  value: string | null;
  screening?: boolean;
};

export type InfoGroup = {
  key: string;
  label: string;
  sectionCode: string | null;
  fields: InfoField[];
};

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  return String(value);
}

function labelled(fieldPath: string, value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  const rendered = valueLabel(fieldPath, value);
  return rendered === '-' ? null : rendered;
}

export function buildInfoGroups(
  target: SellerTarget,
  helpers: {
    formatYuan: (value: string | null) => string;
    formatListedStatus: (value: string | null) => string;
    formatTransferRatio: (target: SellerTarget) => string | null;
    getSubjectDisplay: (target: SellerTarget) => string | null;
  },
): InfoGroup[] {
  const { formatYuan, formatListedStatus, formatTransferRatio, getSubjectDisplay } = helpers;
  const money = (value: string | null) => (value ? formatYuan(value) : null);

  return [
    {
      key: 'identity',
      label: '身份与地区',
      sectionCode: null,
      fields: [
        { field: 'target_name', label: '标的名称', value: text(target.target_name) },
        { field: 'target_subject_name', label: '标的主体', value: getSubjectDisplay(target) },
        { field: 'target_type', label: '类型', value: labelled('target_type', target.target_type) },
        { field: 'registered_province', label: '注册地', value: text([target.registered_province, target.registered_city].filter(Boolean).join('')) },
        { field: 'headquarter_province', label: '总部', value: text([target.headquarter_province, target.headquarter_city].filter(Boolean).join('')), screening: true },
        { field: 'raw_region_text', label: '地区原文', value: text(target.raw_region_text) },
        { field: 'region_granularity', label: '地区粒度', value: labelled('region_granularity', target.region_granularity) },
      ],
    },
    {
      key: 'business_product',
      label: '业务与产品',
      sectionCode: 'business_product',
      fields: [
        { field: 'industry_l1', label: '一级行业', value: text(target.industry_l1), screening: true },
        { field: 'industry_l2', label: '二级行业', value: text(target.industry_l2), screening: true },
        { field: 'industry_primary', label: '行业原文（一级）', value: text(target.industry_primary) },
        { field: 'industry_secondary', label: '行业原文（二级）', value: text(target.industry_secondary) },
        { field: 'business_summary', label: '业务摘要', value: text(target.business_summary) },
      ],
    },
    {
      key: 'chain_position',
      label: '产业链位置与行业地位',
      sectionCode: 'chain_position',
      // 这一组没有结构化字段是对的：链主、龙头这类判断只能靠画像，
      // 空着恰好说明画像为什么存在。
      fields: [],
    },
    {
      key: 'tech_team',
      label: '技术与团队能力',
      sectionCode: 'tech_team',
      fields: [
        { field: 'management_retention_possible', label: '团队可留任', value: labelled('management_retention_possible', target.management_retention_possible), screening: true },
        { field: 'management_team_summary', label: '管理团队', value: text(target.management_team_summary) },
      ],
    },
    {
      key: 'ops_quality',
      label: '经营质量',
      sectionCode: 'ops_quality',
      fields: [
        { field: 'current_revenue_yuan', label: '营收', value: money(target.current_revenue_yuan), screening: true },
        { field: 'current_net_profit_yuan', label: '净利润', value: money(target.current_net_profit_yuan), screening: true },
        { field: 'current_total_profit_yuan', label: '利润总额', value: money(target.current_total_profit_yuan), screening: true },
        { field: 'current_assets_yuan', label: '总资产', value: money(target.current_assets_yuan) },
        { field: 'current_debt_ratio', label: '资产负债率', value: text(target.current_debt_ratio), screening: true },
        { field: 'current_operating_cash_flow_yuan', label: '经营现金流', value: money(target.current_operating_cash_flow_yuan) },
        { field: 'financial_period_label', label: '财务期间', value: text(target.financial_period_label) },
        { field: 'profitability_status', label: '盈利状态', value: labelled('profitability_status', target.profitability_status), screening: true },
        { field: 'cash_flow_status', label: '现金流状态', value: labelled('cash_flow_status', target.cash_flow_status), screening: true },
        { field: 'operation_stability_status', label: '经营稳定性', value: labelled('operation_stability_status', target.operation_stability_status) },
      ],
    },
    {
      key: 'deal_terms',
      label: '交易属性与配合度',
      sectionCode: 'deal_terms',
      fields: [
        { field: 'listed_status', label: '上市状态', value: formatListedStatus(target.listed_status), screening: true },
        { field: 'market_cap_yuan', label: '市值', value: money(target.market_cap_yuan), screening: true },
        { field: 'listing_market_region', label: '上市地', value: labelled('listing_market_region', target.listing_market_region), screening: true },
        { field: 'valuation_yuan', label: '估值', value: money(target.valuation_yuan), screening: true },
        { field: 'valuation_date', label: '估值时间', value: text(target.valuation_date) },
        { field: 'asking_price_yuan', label: '报价', value: money(target.asking_price_yuan) },
        { field: 'asking_price_date', label: '报价时间', value: text(target.asking_price_date) },
        { field: 'pe_ratio', label: 'PE', value: target.pe_ratio ? Number(target.pe_ratio).toFixed(1) : null, screening: true },
        { field: 'pe_source_type', label: 'PE 口径', value: labelled('pe_source_type', target.pe_source_type) },
        { field: 'transfer_ratio_min', label: '出售比例', value: text(target.transfer_ratio_text) || formatTransferRatio(target), screening: true },
        { field: 'transfer_flexibility_type', label: '转让灵活度', value: labelled('transfer_flexibility_type', target.transfer_flexibility_type) },
        { field: 'can_control', label: '可控股', value: labelled('can_control', target.can_control), screening: true },
        { field: 'can_consolidate', label: '可并表', value: labelled('can_consolidate', target.can_consolidate), screening: true },
        { field: 'accepts_minority_investment', label: '接受少数股权', value: labelled('accepts_minority_investment', target.accepts_minority_investment) },
        { field: 'consolidation_path_summary', label: '并表路径', value: text(target.consolidation_path_summary) },
        { field: 'accepts_relocation', label: '接受迁址', value: labelled('accepts_relocation', target.accepts_relocation), screening: true },
        { field: 'accepts_return_investment', label: '接受返投', value: labelled('accepts_return_investment', target.accepts_return_investment), screening: true },
        { field: 'earnout_dependency_status', label: '对赌依赖', value: labelled('earnout_dependency_status', target.earnout_dependency_status) },
        { field: 'transaction_summary', label: '交易摘要', value: text(target.transaction_summary) },
      ],
    },
    {
      key: 'sell_intent_risk',
      label: '出售诉求与风险缺口',
      sectionCode: 'sell_intent_risk',
      fields: [
        { field: 'is_for_sale', label: '是否还卖', value: labelled('is_for_sale', target.is_for_sale) },
        { field: 'risk_summary', label: '风险摘要', value: text(target.risk_summary) },
        { field: 'gap_summary', label: '缺口摘要', value: text(target.gap_summary) },
      ],
    },
  ];
}

export function groupFilledCount(group: InfoGroup): number {
  return group.fields.filter((field) => field.value).length;
}
