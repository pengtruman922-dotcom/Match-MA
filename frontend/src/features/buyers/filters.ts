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
export const INTENT_PARSE_STATUS_POLL_INTERVAL_MS = 5000;
export const UPLOAD_POLICY_TIMEOUT_MS = 12000;

export type BuyerIntentFilters = {
  q: string;
  searchField?: BuyerIntentSearchField;
  industry: string;
  region: string;
  status: string;
  listedStatus: string;
  requiresConsolidation: string;
  owner: string;
  page: number;
};

export type BuyerPartyFilters = {
  q: string;
  searchField?: BuyerPartySearchField;
  buyerType: string;
  region: string;
  listedStatus: string;
  status: string;
  owner: string;
  page: number;
};

export const INTENT_FILTERS: Array<keyof BuyerIntentFilters> = ['q', 'industry', 'region', 'status', 'listedStatus', 'requiresConsolidation', 'owner'];
export const PARTY_FILTERS: Array<keyof BuyerPartyFilters> = ['q', 'buyerType', 'region', 'listedStatus', 'status', 'owner'];

export const EMPTY_INTENT_FILTER_OPTIONS: BuyerIntentFilterOptions = {
  industries: [],
  regions: [],
  statuses: [],
  listed_statuses: [],
  consolidation_requirements: [],
};

export const EMPTY_PARTY_FILTER_OPTIONS: BuyerPartyFilterOptions = {
  buyer_types: [],
  regions: [],
  listed_statuses: [],
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
  legal_name: '法律主体',
  main_business: '主营业务',
  profile_summary: '材料摘要',
};

export function readIntentFilters(searchParams: URLSearchParams): BuyerIntentFilters {
  const searchFieldParam = searchParams.get('searchField');
  return { q: searchParams.get('q') || '', searchField: isBuyerIntentSearchField(searchFieldParam) ? searchFieldParam : undefined, industry: searchParams.get('industry') || '', region: searchParams.get('region') || '', status: searchParams.get('status') || '', listedStatus: searchParams.get('listedStatus') || '', requiresConsolidation: searchParams.get('requiresConsolidation') || '', owner: searchParams.get('owner') || '', page: Math.max(1, Number(searchParams.get('page') || '1') || 1) };
}

export function readPartyFilters(searchParams: URLSearchParams): BuyerPartyFilters {
  const searchFieldParam = searchParams.get('partySearchField');
  return { q: searchParams.get('partyQ') || '', searchField: isBuyerPartySearchField(searchFieldParam) ? searchFieldParam : undefined, buyerType: searchParams.get('buyerType') || '', region: searchParams.get('partyRegion') || '', listedStatus: searchParams.get('partyListedStatus') || '', status: searchParams.get('partyStatus') || '', owner: searchParams.get('partyOwner') || '', page: Math.max(1, Number(searchParams.get('partyPage') || '1') || 1) };
}

export function isBuyerIntentSearchField(value: string | null): value is BuyerIntentSearchField { return value === 'intent_name' || value === 'buyer_name' || value === 'raw_requirement_text' || value === 'intent_summary'; }
export function isBuyerPartySearchField(value: string | null): value is BuyerPartySearchField { return value === 'buyer_name' || value === 'legal_name' || value === 'main_business' || value === 'profile_summary'; }

export { setOrDelete };

export function suggestionSubtitle(suggestion: BuyerSuggestion): string {
  if ('intent_name' in suggestion) {
    if (suggestion.match_type === 'intent') return suggestion.buyer_name || suggestion.snippet || '点击按意向检索';
    if (suggestion.match_type === 'buyer') return suggestion.intent_name;
    return suggestion.intent_name || suggestion.snippet || '点击按该字段检索';
  }
  if (suggestion.match_type === 'buyer') return suggestion.legal_name || suggestion.snippet || '点击按买家检索';
  if (suggestion.match_type === 'legal') return suggestion.buyer_name;
  return suggestion.buyer_name || suggestion.snippet || '点击按该字段检索';
}
