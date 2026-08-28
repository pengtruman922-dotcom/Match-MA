import type {
  BuyerIntentFilterOptions,
  BuyerIntentSearchField,
  BuyerIntentSuggestion,
  BuyerPartyFilterOptions,
  BuyerPartySearchField,
  BuyerPartySuggestion,
} from '../../types/api';
import { setOrDelete } from '../../lib/utils';

export type BuyerSuggestion = BuyerIntentSuggestion | BuyerPartySuggestion;

export const PAGE_SIZE = 20;
export const PAGE_SIZE_OPTIONS = [20, 50, 100];
export const INTENT_PARSE_STATUS_POLL_INTERVAL_MS = 5000;

const PAGE_SIZE_STORAGE_KEY = 'buyerIntents.pageSize';

function readStoredPageSize(): number {
  try {
    const stored = Number(window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY));
    return PAGE_SIZE_OPTIONS.includes(stored) ? stored : PAGE_SIZE;
  } catch {
    return PAGE_SIZE;
  }
}

export function storeIntentPageSize(pageSize: number): void {
  try {
    window.localStorage.setItem(PAGE_SIZE_STORAGE_KEY, String(pageSize));
  } catch {
    // 隐私模式下 localStorage 不可写；URL 参数仍然生效，忽略即可。
  }
}
export const UPLOAD_POLICY_TIMEOUT_MS = 12000;

export type BuyerIntentFilters = {
  q: string;
  searchField?: BuyerIntentSearchField;
  /** 「它要买什么」那一侧。 */
  industry: string;
  region: string;
  status: string;
  listedStatus: string;
  requiresConsolidation: string;
  /** 「它是谁」那一侧。同名维度分两套：同一页既要能问「谁在找建材」，也要能问「哪些国企买家在找东西」。 */
  buyerBusinessTag: string;
  buyerListedStatus: string;
  buyerProvince: string;
  owner: string;
  /** 更新时间排序方向，默认最近在前。 */
  sortDir: 'desc' | 'asc';
  page: number;
  pageSize: number;
};

/**
 * 买家主体的筛选维度。所属行业 0824 退役：生产 39 条主体 0% 填了行业，
 * 那一栏永远是空的。取代它的是「买家自己是什么」（企业性质）与
 * 「买家自己做什么」（业务标签）—— 为标的找买家的第一判断依据。
 */
export type BuyerPartyFilters = {
  q: string;
  searchField?: BuyerPartySearchField;
  ownershipType: string;
  businessTag: string;
  region: string;
  status: string;
  owner: string;
  page: number;
};

// 「清空条件」按钮统计的就是这些；sortDir 不算条件（它永远有值）。
export const INTENT_FILTERS: Array<keyof BuyerIntentFilters> = ['q', 'industry', 'region', 'status', 'listedStatus', 'buyerBusinessTag', 'buyerListedStatus', 'buyerProvince', 'owner'];
export const PARTY_FILTERS: Array<keyof BuyerPartyFilters> = ['q', 'ownershipType', 'businessTag', 'region', 'status', 'owner'];

export const EMPTY_INTENT_FILTER_OPTIONS: BuyerIntentFilterOptions = {
  industries: [],
  regions: [],
  statuses: [],
  listed_statuses: [],
  consolidation_requirements: [],
  buyer_business_tags: [],
  buyer_listed_statuses: [],
  buyer_provinces: [],
};

export const EMPTY_PARTY_FILTER_OPTIONS: BuyerPartyFilterOptions = {
  ownership_types: [],
  business_tags: [],
  regions: [],
  statuses: [],
};

export const INTENT_SEARCH_FIELD_LABELS: Record<BuyerIntentSearchField | 'all', string> = {
  all: '全部字段',
  intent_name: '需求名称',
  buyer_name: '买家',
  raw_requirement_text: '需求',
  intent_summary: '摘要',
};

export const PARTY_SEARCH_FIELD_LABELS: Record<BuyerPartySearchField | 'all', string> = {
  all: '全部字段',
  buyer_name: '买家',
  alias: '别名',
  contact_name: '联系人',
};

export function readIntentFilters(searchParams: URLSearchParams): BuyerIntentFilters {
  const searchFieldParam = searchParams.get('searchField');
  // URL 参数 > localStorage > 默认 20；非法值一律回落到 20。
  const pageSizeParam = Number(searchParams.get('pageSize'));
  const pageSize = PAGE_SIZE_OPTIONS.includes(pageSizeParam) ? pageSizeParam : readStoredPageSize();
  return { q: searchParams.get('q') || '', searchField: isBuyerIntentSearchField(searchFieldParam) ? searchFieldParam : undefined, industry: searchParams.get('industry') || '', region: searchParams.get('region') || '', status: searchParams.get('status') || '', listedStatus: searchParams.get('listedStatus') || '', requiresConsolidation: searchParams.get('requiresConsolidation') || '', buyerBusinessTag: searchParams.get('buyerTag') || '', buyerListedStatus: searchParams.get('buyerListed') || '', buyerProvince: searchParams.get('buyerProvince') || '', owner: searchParams.get('owner') || '', sortDir: searchParams.get('sortDir') === 'asc' ? 'asc' : 'desc', page: Math.max(1, Number(searchParams.get('page') || '1') || 1), pageSize };
}

export function readPartyFilters(searchParams: URLSearchParams): BuyerPartyFilters {
  const searchFieldParam = searchParams.get('partySearchField');
  return { q: searchParams.get('partyQ') || '', searchField: isBuyerPartySearchField(searchFieldParam) ? searchFieldParam : undefined, ownershipType: searchParams.get('partyOwnership') || '', businessTag: searchParams.get('partyTag') || '', region: searchParams.get('partyRegion') || '', status: searchParams.get('partyStatus') || '', owner: searchParams.get('partyOwner') || '', page: Math.max(1, Number(searchParams.get('partyPage') || '1') || 1) };
}

export function isBuyerIntentSearchField(value: string | null): value is BuyerIntentSearchField { return value === 'intent_name' || value === 'buyer_name' || value === 'raw_requirement_text' || value === 'intent_summary'; }
export function isBuyerPartySearchField(value: string | null): value is BuyerPartySearchField { return value === 'buyer_name' || value === 'alias' || value === 'contact_name'; }

export { setOrDelete };

export function suggestionSubtitle(suggestion: BuyerSuggestion): string {
  if ('intent_name' in suggestion) {
    if (suggestion.match_type === 'intent') return suggestion.buyer_name || suggestion.snippet || '点击按意向检索';
    if (suggestion.match_type === 'buyer') return suggestion.intent_name;
    return suggestion.intent_name || suggestion.snippet || '点击按该字段检索';
  }
  if (suggestion.match_type === 'buyer') return suggestion.snippet || '点击按买家检索';
  if (suggestion.match_type === 'alias' || suggestion.match_type === 'contact') return suggestion.buyer_name;
  return suggestion.buyer_name || suggestion.snippet || '点击按该字段检索';
}
