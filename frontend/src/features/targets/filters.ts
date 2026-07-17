import type { SellerTarget, SellerTargetSearchField } from '../../types/api';

export const PAGE_SIZE = 20;
export const PARSE_POLL_INTERVAL_MS = 4000;

export function isParsingTarget(item: SellerTarget): boolean {
  return item.information_status === 'parsing' || item.information_status === 'researching';
}

export const SEARCH_FIELD_LABELS: Record<SellerTargetSearchField | 'all', string> = {
  all: '全部字段',
  target_name: '标的',
  target_subject_name: '主体',
  business_summary: '摘要',
};

export type TargetFilters = {
  q: string;
  searchField?: SellerTargetSearchField;
  industry: string;
  region: string;
  recommendationStatus: string;
  parseStatus: string;
  owner: string;
  page: number;
};

export function readTargetFilters(searchParams: URLSearchParams): TargetFilters {
  const searchFieldParam = searchParams.get('searchField');
  const searchField = isSellerTargetSearchField(searchFieldParam) ? searchFieldParam : undefined;
  const page = Math.max(1, Number(searchParams.get('page') || '1') || 1);
  return {
    q: searchParams.get('q') || '',
    searchField,
    industry: searchParams.get('industry') || '',
    region: searchParams.get('region') || '',
    recommendationStatus: searchParams.get('recommendationStatus') || '',
    parseStatus: searchParams.get('parseStatus') || '',
    owner: searchParams.get('owner') || '',
    page,
  };
}

export function isSellerTargetSearchField(value: string | null): value is SellerTargetSearchField {
  return value === 'target_name' || value === 'target_subject_name' || value === 'business_summary';
}
