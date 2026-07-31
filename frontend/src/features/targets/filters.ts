import type { SellerTarget, SellerTargetSearchField } from '../../types/api';

export const PAGE_SIZE = 20;
export const PAGE_SIZE_OPTIONS = [20, 50, 100];
export const PARSE_POLL_INTERVAL_MS = 4000;
/** 每轮轮询的请求数上限，与每页条数解耦；超出的行按轮次轮转刷新。 */
export const PARSE_POLL_BATCH_SIZE = 20;

const PAGE_SIZE_STORAGE_KEY = 'targets.pageSize';

function readStoredPageSize(): number {
  try {
    const stored = Number(window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY));
    return PAGE_SIZE_OPTIONS.includes(stored) ? stored : PAGE_SIZE;
  } catch {
    return PAGE_SIZE;
  }
}

export function storePageSize(pageSize: number): void {
  try {
    window.localStorage.setItem(PAGE_SIZE_STORAGE_KEY, String(pageSize));
  } catch {
    // 隐私模式下 localStorage 不可写；URL 参数仍然生效，忽略即可。
  }
}

export function isParsingTarget(item: SellerTarget): boolean {
  return ['parsing', 'research_queued', 'researching', 'research_mapping'].includes(item.ai_processing_state);
}

export const SEARCH_FIELD_LABELS: Record<SellerTargetSearchField | 'all', string> = {
  all: '全部字段',
  target_name: '标的',
  target_subject_name: '主体',
  business_summary: '摘要',
  industry: '行业',
};

export const SEARCH_FIELD_OPTIONS: Array<{ value: '' | SellerTargetSearchField; label: string }> = [
  { value: '', label: '全部字段' },
  { value: 'target_name', label: '标的名称' },
  { value: 'target_subject_name', label: '标的主体' },
  { value: 'industry', label: '所属行业' },
  { value: 'business_summary', label: '业务摘要' },
];

export type TargetFilters = {
  q: string;
  searchField?: SellerTargetSearchField;
  industryL1: string;
  industryL2: string;
  province: string;
  city: string;
  district: string;
  status: string;
  owner: string;
  page: number;
  pageSize: number;
};

export function readTargetFilters(searchParams: URLSearchParams): TargetFilters {
  const searchFieldParam = searchParams.get('searchField');
  const searchField = isSellerTargetSearchField(searchFieldParam) ? searchFieldParam : undefined;
  const page = Math.max(1, Number(searchParams.get('page') || '1') || 1);
  // URL 参数 > localStorage > 默认 20；非法值一律回落到 20。
  const pageSizeParam = Number(searchParams.get('pageSize'));
  const pageSize = PAGE_SIZE_OPTIONS.includes(pageSizeParam) ? pageSizeParam : readStoredPageSize();
  return {
    q: searchParams.get('q') || '',
    searchField,
    industryL1: searchParams.get('industryL1') || '',
    industryL2: searchParams.get('industryL2') || '',
    province: searchParams.get('province') || '',
    city: searchParams.get('city') || '',
    district: searchParams.get('district') || '',
    status: searchParams.get('status') || '',
    owner: searchParams.get('owner') || '',
    page,
    pageSize,
  };
}

export function isSellerTargetSearchField(value: string | null): value is SellerTargetSearchField {
  return (
    value === 'target_name' ||
    value === 'target_subject_name' ||
    value === 'business_summary' ||
    value === 'industry'
  );
}

export function activeTargetFilterCount(filters: TargetFilters): number {
  // 市/区不单独计数：它们只是地区这一个条件的更细层级。
  return [
    filters.q,
    filters.industryL1,
    filters.province,
    filters.status,
    filters.owner,
  ].filter(Boolean).length;
}
