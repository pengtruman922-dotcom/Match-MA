import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  Building2,
  ChevronDown,
  FileText,
  Image,
  Loader2,
  Paperclip,
  Plus,
  Search,
  Sparkles,
  Tag,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { attachments, businessUpdates, buyerParties, buyerIntents, users } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type {
  AppUserOption,
  AttachmentUploadPolicy,
  BuyerFilterOption,
  BuyerIntent,
  BuyerIntentFilterOptions,
  BuyerIntentParseStatus,
  BuyerIntentSearchField,
  BuyerIntentSuggestion,
  BuyerParty,
  BuyerPartyCreate,
  BuyerPartyDedupCheck,
  BuyerPartyFilterOptions,
  BuyerPartySearchField,
  BuyerPartySuggestion,
} from '../types/api';
import { valueLabel } from '../lib/fieldLabels';

type BuyerSuggestion = BuyerIntentSuggestion | BuyerPartySuggestion;

const PAGE_SIZE = 20;
const INTENT_PARSE_STATUS_POLL_INTERVAL_MS = 5000;
const UPLOAD_POLICY_TIMEOUT_MS = 12000;
const INTENT_FILTERS: Array<keyof BuyerIntentFilters> = ['q', 'industry', 'region', 'status', 'listedStatus', 'requiresConsolidation', 'owner'];
const PARTY_FILTERS: Array<keyof BuyerPartyFilters> = ['q', 'buyerType', 'region', 'listedStatus', 'status', 'owner'];

const EMPTY_INTENT_FILTER_OPTIONS: BuyerIntentFilterOptions = {
  industries: [],
  regions: [],
  statuses: [],
  listed_statuses: [],
  consolidation_requirements: [],
};

const EMPTY_PARTY_FILTER_OPTIONS: BuyerPartyFilterOptions = {
  buyer_types: [],
  regions: [],
  listed_statuses: [],
  statuses: [],
};

const INTENT_SEARCH_FIELD_LABELS: Record<BuyerIntentSearchField | 'all', string> = {
  all: '全部字段',
  intent_name: '需求名称',
  buyer_name: '买家',
  raw_requirement_text: '需求',
  intent_summary: '摘要',
};

const PARTY_SEARCH_FIELD_LABELS: Record<BuyerPartySearchField | 'all', string> = {
  all: '全部字段',
  buyer_name: '买家',
  legal_name: '法律主体',
  main_business: '主营业务',
  profile_summary: '材料摘要',
};

type BuyerIntentFilters = {
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

type BuyerPartyFilters = {
  q: string;
  searchField?: BuyerPartySearchField;
  buyerType: string;
  region: string;
  listedStatus: string;
  status: string;
  owner: string;
  page: number;
};

export default function Buyers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [showCreateIntent, setShowCreateIntent] = useState(false);
  const [intentRefreshKey, setIntentRefreshKey] = useState(0);

  useEffect(() => {
    const action = searchParams.get('action');
    if (action !== 'new-intent' && action !== 'new-party') return;
    const next = new URLSearchParams(searchParams);
    next.delete('tab');
    setShowCreateIntent(true);
    next.delete('action');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">买家管理</h1>
          <p className="text-xs text-gray-400 mt-1">管理买家及其当前并购需求</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateIntent(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建买家
          </button>
        </div>
      </div>

      <IntentsList
        externalShowCreate={showCreateIntent}
        onExternalCreateClose={() => setShowCreateIntent(false)}
        refreshKey={intentRefreshKey}
        onCreated={() => setIntentRefreshKey((k) => k + 1)}
      />
    </div>
  );
}

function IntentsList({
  externalShowCreate,
  onExternalCreateClose,
  refreshKey,
  onCreated,
}: {
  externalShowCreate: boolean;
  onExternalCreateClose: () => void;
  refreshKey: number;
  onCreated: () => void;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readIntentFilters(searchParams), [searchParams]);
  const [items, setItems] = useState<BuyerIntent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState(filters.q);
  const [filterOptions, setFilterOptions] = useState<BuyerIntentFilterOptions>(EMPTY_INTENT_FILTER_OPTIONS);
  const [suggestions, setSuggestions] = useState<BuyerIntentSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [parseStatuses, setParseStatuses] = useState<Record<string, BuyerIntentParseStatus>>({});
  const admin = isAdmin();
  const [ownerOptions, setOwnerOptions] = useState<AppUserOption[]>([]);
  const [assignOwnerId, setAssignOwnerId] = useState('');
  const [assigning, setAssigning] = useState(false);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visibleIds = useMemo(() => items.map((item) => item.id), [items]);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const selectedCount = selectedIds.size;
  const activeFilterCount = INTENT_FILTERS.filter((key) => Boolean(filters[key])).length;

  const updateFilters = useCallback((patch: Partial<BuyerIntentFilters>, options?: { replace?: boolean }) => {
    const next = new URLSearchParams(searchParams);
    next.delete('tab');
    if ('q' in patch) setOrDelete(next, 'q', patch.q);
    if ('searchField' in patch) setOrDelete(next, 'searchField', patch.searchField);
    if ('industry' in patch) setOrDelete(next, 'industry', patch.industry);
    if ('region' in patch) setOrDelete(next, 'region', patch.region);
    if ('status' in patch) setOrDelete(next, 'status', patch.status);
    if ('listedStatus' in patch) setOrDelete(next, 'listedStatus', patch.listedStatus);
    if ('requiresConsolidation' in patch) setOrDelete(next, 'requiresConsolidation', patch.requiresConsolidation);
    if ('owner' in patch) setOrDelete(next, 'owner', patch.owner);
    if (patch.page !== undefined) {
      if (patch.page <= 1) next.delete('page');
      else next.set('page', String(patch.page));
    }
    setSearchParams(next, { replace: options?.replace });
  }, [searchParams, setSearchParams]);

  const fetchData = useCallback(() => {
    setLoading(true);
    buyerIntents
      .list({
        q: filters.q || undefined,
        search_field: filters.searchField,
        industry: filters.industry || undefined,
        region: filters.region || undefined,
        status: filters.status || undefined,
        listed_status: filters.listedStatus || undefined,
        requires_consolidation: filters.requiresConsolidation || undefined,
        owner: filters.owner || undefined,
        limit: PAGE_SIZE,
        offset: (filters.page - 1) * PAGE_SIZE,
      })
      .then((response) => {
        setItems(response.items);
        setTotal(response.total);
        setSelectedIds(new Set());
        if (response.items.length === 0 && response.total > 0 && filters.page > 1) {
          updateFilters({ page: filters.page - 1 }, { replace: true });
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [filters, updateFilters]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);
  useEffect(() => { buyerIntents.filterOptions().then(setFilterOptions).catch(() => {}); }, []);
  useEffect(() => { setSearchQuery(filters.q); }, [filters.q]);
  useEffect(() => {
    if (!admin) return;
    users.options().then(setOwnerOptions).catch(() => {});
  }, [admin]);

  useEffect(() => {
    if (items.length === 0) {
      setParseStatuses({});
      return;
    }
    let cancelled = false;
    Promise.all(
      items.map((item) =>
        buyerIntents
          .parseStatus(item.id)
          .then((status) => [item.id, status] as const)
          .catch(() => null)
      )
    ).then((pairs) => {
      if (cancelled) return;
      const next: Record<string, BuyerIntentParseStatus> = {};
      for (const pair of pairs) {
        if (pair) next[pair[0]] = pair[1];
      }
      setParseStatuses(next);
    });
    return () => {
      cancelled = true;
    };
  }, [items]);

  useEffect(() => {
    const activeIds = Object.entries(parseStatuses)
      .filter(([, status]) => isActiveParseStatus(status))
      .map(([id]) => id);
    if (activeIds.length === 0) return;
    const timer = window.setInterval(() => {
      Promise.all(
        activeIds.map((id) =>
          buyerIntents
            .parseStatus(id)
            .then((status) => [id, status] as const)
            .catch(() => null)
        )
      ).then((pairs) => {
        const shouldRefreshRows = pairs.some((pair) => {
          if (!pair) return false;
          const [id, status] = pair;
          return parseStatuses[id]?.latest_job?.status !== 'succeeded' && status.latest_job?.status === 'succeeded';
        });
        setParseStatuses((prev) => {
          const next = { ...prev };
          for (const pair of pairs) {
            if (!pair) continue;
            const [id, status] = pair;
            next[id] = status;
          }
          return next;
        });
        if (shouldRefreshRows) fetchData();
      });
    }, INTENT_PARSE_STATUS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [fetchData, parseStatuses]);

  useEffect(() => {
    const query = searchQuery.trim();
    if (!showSuggestions || !query) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }
    let cancelled = false;
    setSuggestionsLoading(true);
    const timer = window.setTimeout(() => {
      buyerIntents
        .suggestions({ q: query, limit: 5 })
        .then((nextSuggestions) => { if (!cancelled) setSuggestions(nextSuggestions); })
        .catch(() => { if (!cancelled) setSuggestions([]); })
        .finally(() => { if (!cancelled) setSuggestionsLoading(false); });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchQuery, showSuggestions]);

  const handleSearch = () => {
    const nextQuery = searchQuery.trim();
    updateFilters({ q: nextQuery, searchField: nextQuery === filters.q ? filters.searchField : undefined, page: 1 });
    setShowSuggestions(false);
  };

  const handleSuggestionSelect = (suggestion: BuyerIntentSuggestion) => {
    const nextQuery = ['requirement', 'summary'].includes(suggestion.match_type) ? searchQuery.trim() : suggestion.match_text;
    setSearchQuery(nextQuery);
    setShowSuggestions(false);
    updateFilters({ q: nextQuery, searchField: suggestion.search_field, page: 1 });
  };

  const toggleSelectAllVisible = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const toggleSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认删除已选择的 ${ids.length} 条并购需求？删除后不会出现在列表和推荐候选里。`)) return;
    setBulkDeleting(true);
    try {
      await buyerIntents.bulkDelete(ids);
      await buyerIntents.filterOptions().then(setFilterOptions).catch(() => {});
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量删除失败');
    } finally {
      setBulkDeleting(false);
    }
  };

  const handleBatchAssign = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || !assignOwnerId) return;
    const ownerName = ownerOptions.find((option) => option.id === assignOwnerId)?.name || '所选账号';
    if (!window.confirm(`将已选择的 ${ids.length} 条并购需求指派给「${ownerName}」？`)) return;
    setAssigning(true);
    try {
      await buyerIntents.batchAssignOwner(ids, assignOwnerId);
      await buyerIntents.filterOptions().then(setFilterOptions).catch(() => {});
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量指派失败');
    } finally {
      setAssigning(false);
    }
  };

  const clearFilters = () => {
    setSearchQuery('');
    updateFilters({ q: '', searchField: undefined, industry: '', region: '', status: '', listedStatus: '', requiresConsolidation: '', owner: '', page: 1 });
  };

  return (
    <>
      <ListToolbar
        searchValue={searchQuery}
        placeholder="搜索需求名称、买家或需求内容..."
        suggestions={suggestions}
        suggestionsOpen={showSuggestions && searchQuery.trim().length > 0}
        suggestionsLoading={suggestionsLoading}
        onSearchValueChange={(value) => { setSearchQuery(value); setShowSuggestions(true); }}
        onSearchFocus={() => setShowSuggestions(true)}
        onSearchBlur={() => window.setTimeout(() => setShowSuggestions(false), 120)}
        onSearch={handleSearch}
        onSuggestionSelect={(suggestion) => handleSuggestionSelect(suggestion as BuyerIntentSuggestion)}
        searchFieldBadge={filters.q && filters.searchField ? `按${INTENT_SEARCH_FIELD_LABELS[filters.searchField]}检索：${filters.q}` : ''}
        filters={[
          { label: '行业', value: filters.industry, options: filterOptions.industries, onChange: (value) => updateFilters({ industry: value, page: 1 }) },
          { label: '地区', value: filters.region, options: filterOptions.regions, onChange: (value) => updateFilters({ region: value, page: 1 }) },
          { label: '状态', value: filters.status, options: filterOptions.statuses, onChange: (value) => updateFilters({ status: value, page: 1 }) },
          { label: '上市要求', value: filters.listedStatus, options: filterOptions.listed_statuses, onChange: (value) => updateFilters({ listedStatus: value, page: 1 }) },
          { label: '并表要求', value: filters.requiresConsolidation, options: filterOptions.consolidation_requirements, onChange: (value) => updateFilters({ requiresConsolidation: value, page: 1 }) },
          ...(admin ? [{ label: '负责人', value: filters.owner, options: filterOptions.owners || [], onChange: (value: string) => updateFilters({ owner: value, page: 1 }) }] : []),
        ]}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
        total={total}
        totalLabel="条并购需求"
      />

      {selectedCount > 0 && (
        <BulkActionBar
          count={selectedCount}
          label="条需求"
          deleting={bulkDeleting}
          onClear={() => setSelectedIds(new Set())}
          onDelete={handleBulkDelete}
          assignOptions={ownerOptions}
          assignValue={assignOwnerId}
          onAssignValueChange={setAssignOwnerId}
          onAssign={handleBatchAssign}
          assigning={assigning}
        />
      )}

      <div className="bg-white border border-gray-200 overflow-x-auto">
        <table className="w-full min-w-[1160px] table-fixed text-sm">
          <colgroup>
            <col className="w-12" />
            <col className="w-64" />
            <col className="w-40" />
            <col className="w-72" />
            <col className="w-24" />
            <col className="w-24" />
            <col className="w-28" />
            <col className="w-28" />
            <col className="w-28" />
          </colgroup>
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 w-12"><input type="checkbox" disabled={visibleIds.length === 0} checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="选择当前页买家意向" className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">需求名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">买家名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">关键需求</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">解析状态</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">推荐状态</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">负责人</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">最近更新</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-gray-400">暂无匹配的买家</td></tr>
            ) : items.map((item) => (
              <IntentRow
                key={item.id}
                item={item}
                parseStatus={parseStatuses[item.id]}
                selected={selectedIds.has(item.id)}
                onSelectedChange={(checked) => toggleSelected(item.id, checked)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <PaginationFooter page={filters.page} pageCount={pageCount} pageSize={PAGE_SIZE} loading={loading} onPageChange={(page) => updateFilters({ page })} />

      {externalShowCreate && <CreateIntentModal onClose={onExternalCreateClose} onCreated={() => { onExternalCreateClose(); onCreated(); fetchData(); }} />}
    </>
  );
}

function IntentRow({
  item,
  parseStatus,
  selected,
  onSelectedChange,
}: {
  item: BuyerIntent;
  parseStatus?: BuyerIntentParseStatus;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
}) {
  return (
    <tr className="h-[72px] transition-colors hover:bg-brand-50/30">
      <td className="px-4 py-3 align-middle"><input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择${item.intent_name}`} className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></td>
      <td className="px-4 py-3 align-middle">
        <Link to={`/buyer-intents/${item.id}`} className="line-clamp-2 font-medium leading-5 text-gray-900 transition-colors hover:text-brand-600" title={item.intent_name}>{item.intent_name}</Link>
      </td>
      <td className="px-4 py-3 align-middle text-gray-700"><p className="line-clamp-2 leading-5" title={item.buyer_name || '未关联买家'}>{item.buyer_name || <span className="text-amber-600">未关联买家</span>}</p></td>
      <td className="px-4 py-3 align-middle text-gray-600"><p className="line-clamp-2 leading-5" title={compactRequirementNotes(item)}>{compactRequirementNotes(item) || '-'}</p></td>
      <td className="px-4 py-3 text-center align-middle"><ParseStatusBadge item={item} parseStatus={parseStatus} /></td>
      <td className="px-4 py-3 text-center align-middle"><IntentStatusBadge status={item.status} /></td>
      <td className="px-4 py-3 align-middle text-gray-600"><p className="line-clamp-2" title={item.owner_name || '未指派'}>{item.owner_name || <span className="text-gray-300">未指派</span>}</p></td>
      <td className="whitespace-nowrap px-4 py-3 align-middle text-gray-500">{shortDate(item.updated_at)}</td>
      <td className="px-4 py-3 align-middle"><Link to={`/recommendations?mode=buyer-to-target&intentId=${item.id}`} className="mx-auto inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 transition-colors hover:bg-brand-50"><Sparkles className="h-3 w-3" />推荐标的</Link></td>
    </tr>
  );
}


export function PartiesList({
  externalShowCreate,
  onExternalCreateClose,
  refreshKey,
  onCreated,
}: {
  externalShowCreate: boolean;
  onExternalCreateClose: () => void;
  refreshKey: number;
  onCreated: () => void;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readPartyFilters(searchParams), [searchParams]);
  const [items, setItems] = useState<BuyerParty[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState(filters.q);
  const [filterOptions, setFilterOptions] = useState<BuyerPartyFilterOptions>(EMPTY_PARTY_FILTER_OPTIONS);
  const [suggestions, setSuggestions] = useState<BuyerPartySuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const admin = isAdmin();
  const [ownerOptions, setOwnerOptions] = useState<AppUserOption[]>([]);
  const [assignOwnerId, setAssignOwnerId] = useState('');
  const [assigning, setAssigning] = useState(false);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visibleIds = useMemo(() => items.map((item) => item.id), [items]);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const selectedCount = selectedIds.size;
  const activeFilterCount = PARTY_FILTERS.filter((key) => Boolean(filters[key])).length;

  const updateFilters = useCallback((patch: Partial<BuyerPartyFilters>, options?: { replace?: boolean }) => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', 'parties');
    if ('q' in patch) setOrDelete(next, 'partyQ', patch.q);
    if ('searchField' in patch) setOrDelete(next, 'partySearchField', patch.searchField);
    if ('buyerType' in patch) setOrDelete(next, 'buyerType', patch.buyerType);
    if ('region' in patch) setOrDelete(next, 'partyRegion', patch.region);
    if ('listedStatus' in patch) setOrDelete(next, 'partyListedStatus', patch.listedStatus);
    if ('status' in patch) setOrDelete(next, 'partyStatus', patch.status);
    if ('owner' in patch) setOrDelete(next, 'partyOwner', patch.owner);
    if (patch.page !== undefined) {
      if (patch.page <= 1) next.delete('partyPage');
      else next.set('partyPage', String(patch.page));
    }
    setSearchParams(next, { replace: options?.replace });
  }, [searchParams, setSearchParams]);

  const fetchData = useCallback(() => {
    setLoading(true);
    buyerParties
      .list({
        q: filters.q || undefined,
        search_field: filters.searchField,
        buyer_type: filters.buyerType || undefined,
        region: filters.region || undefined,
        listed_status: filters.listedStatus || undefined,
        status: filters.status || undefined,
        owner: filters.owner || undefined,
        limit: PAGE_SIZE,
        offset: (filters.page - 1) * PAGE_SIZE,
      })
      .then((response) => {
        setItems(response.items);
        setTotal(response.total);
        setSelectedIds(new Set());
        if (response.items.length === 0 && response.total > 0 && filters.page > 1) {
          updateFilters({ page: filters.page - 1 }, { replace: true });
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [filters, updateFilters]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);
  useEffect(() => { buyerParties.filterOptions().then(setFilterOptions).catch(() => {}); }, []);
  useEffect(() => { setSearchQuery(filters.q); }, [filters.q]);
  useEffect(() => {
    if (!admin) return;
    users.options().then(setOwnerOptions).catch(() => {});
  }, [admin]);

  useEffect(() => {
    const query = searchQuery.trim();
    if (!showSuggestions || !query) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }
    let cancelled = false;
    setSuggestionsLoading(true);
    const timer = window.setTimeout(() => {
      buyerParties
        .suggestions({ q: query, limit: 5 })
        .then((nextSuggestions) => { if (!cancelled) setSuggestions(nextSuggestions); })
        .catch(() => { if (!cancelled) setSuggestions([]); })
        .finally(() => { if (!cancelled) setSuggestionsLoading(false); });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchQuery, showSuggestions]);

  const handleSearch = () => {
    const nextQuery = searchQuery.trim();
    updateFilters({ q: nextQuery, searchField: nextQuery === filters.q ? filters.searchField : undefined, page: 1 });
    setShowSuggestions(false);
  };

  const handleSuggestionSelect = (suggestion: BuyerPartySuggestion) => {
    const nextQuery = ['business', 'profile'].includes(suggestion.match_type) ? searchQuery.trim() : suggestion.match_text;
    setSearchQuery(nextQuery);
    setShowSuggestions(false);
    updateFilters({ q: nextQuery, searchField: suggestion.search_field, page: 1 });
  };

  const toggleSelectAllVisible = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const toggleSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认删除已选择的 ${ids.length} 个买家主体？删除后不会出现在列表和推荐候选里。`)) return;
    setBulkDeleting(true);
    try {
      await buyerParties.bulkDelete(ids);
      await buyerParties.filterOptions().then(setFilterOptions).catch(() => {});
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量删除失败');
    } finally {
      setBulkDeleting(false);
    }
  };

  const handleBatchAssign = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || !assignOwnerId) return;
    const ownerName = ownerOptions.find((option) => option.id === assignOwnerId)?.name || '所选账号';
    if (!window.confirm(`将已选择的 ${ids.length} 个买家主体指派给「${ownerName}」？`)) return;
    setAssigning(true);
    try {
      await buyerParties.batchAssignOwner(ids, assignOwnerId);
      await buyerParties.filterOptions().then(setFilterOptions).catch(() => {});
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量指派失败');
    } finally {
      setAssigning(false);
    }
  };

  const clearFilters = () => {
    setSearchQuery('');
    updateFilters({ q: '', searchField: undefined, buyerType: '', region: '', listedStatus: '', status: '', owner: '', page: 1 });
  };

  return (
    <>
      <ListToolbar
        searchValue={searchQuery}
        placeholder="搜索买家名称、法律主体、业务或画像..."
        suggestions={suggestions}
        suggestionsOpen={showSuggestions && searchQuery.trim().length > 0}
        suggestionsLoading={suggestionsLoading}
        onSearchValueChange={(value) => { setSearchQuery(value); setShowSuggestions(true); }}
        onSearchFocus={() => setShowSuggestions(true)}
        onSearchBlur={() => window.setTimeout(() => setShowSuggestions(false), 120)}
        onSearch={handleSearch}
        onSuggestionSelect={(suggestion) => handleSuggestionSelect(suggestion as BuyerPartySuggestion)}
        searchFieldBadge={filters.q && filters.searchField ? `按${PARTY_SEARCH_FIELD_LABELS[filters.searchField]}检索：${filters.q}` : ''}
        filters={[
          { label: '买家类型', value: filters.buyerType, options: filterOptions.buyer_types, onChange: (value) => updateFilters({ buyerType: value, page: 1 }) },
          { label: '地区', value: filters.region, options: filterOptions.regions, onChange: (value) => updateFilters({ region: value, page: 1 }) },
          { label: '上市状态', value: filters.listedStatus, options: filterOptions.listed_statuses, onChange: (value) => updateFilters({ listedStatus: value, page: 1 }) },
          { label: '状态', value: filters.status, options: filterOptions.statuses, onChange: (value) => updateFilters({ status: value, page: 1 }) },
          ...(admin ? [{ label: '负责人', value: filters.owner, options: filterOptions.owners || [], onChange: (value: string) => updateFilters({ owner: value, page: 1 }) }] : []),
        ]}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
        total={total}
        totalLabel="买家主体"
      />

      {selectedCount > 0 && (
        <BulkActionBar
          count={selectedCount}
          label="买家主体"
          deleting={bulkDeleting}
          onClear={() => setSelectedIds(new Set())}
          onDelete={handleBulkDelete}
          assignOptions={ownerOptions}
          assignValue={assignOwnerId}
          onAssignValueChange={setAssignOwnerId}
          onAssign={handleBatchAssign}
          assigning={assigning}
        />
      )}

      <div className="bg-white border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 w-12"><input type="checkbox" disabled={visibleIds.length === 0} checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="选择当前页买家主体" className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">买家名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">类型</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">地区</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">上市状态</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">主营业务</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">状态</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">负责人</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-gray-400">暂无匹配的买家主体</td></tr>
            ) : items.map((item) => <PartyRow key={item.id} item={item} selected={selectedIds.has(item.id)} onSelectedChange={(checked) => toggleSelected(item.id, checked)} />)}
          </tbody>
        </table>
      </div>

      <PaginationFooter page={filters.page} pageCount={pageCount} pageSize={PAGE_SIZE} loading={loading} onPageChange={(page) => updateFilters({ page })} />

      {externalShowCreate && <CreatePartyModal onClose={onExternalCreateClose} onCreated={() => { onExternalCreateClose(); onCreated(); fetchData(); }} />}
    </>
  );
}

function PartyRow({ item, selected, onSelectedChange }: { item: BuyerParty; selected: boolean; onSelectedChange: (checked: boolean) => void }) {
  const region = [item.region_province, item.region_city].filter(Boolean).join(' ') || '-';
  return (
    <tr className="hover:bg-brand-50/30 transition-colors">
      <td className="px-4 py-3"><input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择${item.buyer_name}`} className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></td>
      <td className="px-4 py-3"><Link to={`/buyers/${item.id}`} className="font-medium text-gray-900 hover:text-brand-600 transition-colors">{item.buyer_name}</Link>{item.legal_name && <span className="text-xs text-gray-400 ml-2">{item.legal_name}</span>}</td>
      <td className="px-4 py-3 text-gray-600">{valueLabel('buyer_type', item.buyer_type)}</td>
      <td className="px-4 py-3 text-gray-600 max-w-[160px] truncate" title={region === '-' ? undefined : region}>{region}</td>
      <td className="px-4 py-3 text-gray-600">{valueLabel('listed_status', item.listed_status)}</td>
      <td className="px-4 py-3 text-gray-600 truncate max-w-[240px]" title={item.main_business || undefined}>{item.main_business || '-'}</td>
      <td className="px-4 py-3 text-center"><PartyStatusBadge status={item.status} /></td>
      <td className="px-4 py-3 text-gray-600">{item.owner_name || <span className="text-gray-300">未指派</span>}</td>
      <td className="px-4 py-3 text-center"><Link to={`/buyers/${item.id}`} className="text-xs text-brand-600 hover:text-brand-700 font-medium">查看</Link></td>
    </tr>
  );
}


function ListToolbar({
  searchValue,
  placeholder,
  suggestions,
  suggestionsOpen,
  suggestionsLoading,
  onSearchValueChange,
  onSearchFocus,
  onSearchBlur,
  onSearch,
  onSuggestionSelect,
  searchFieldBadge,
  filters,
  activeFilterCount,
  onClear,
  total,
  totalLabel,
}: {
  searchValue: string;
  placeholder: string;
  suggestions: BuyerSuggestion[];
  suggestionsOpen: boolean;
  suggestionsLoading: boolean;
  onSearchValueChange: (value: string) => void;
  onSearchFocus: () => void;
  onSearchBlur: () => void;
  onSearch: () => void;
  onSuggestionSelect: (suggestion: BuyerSuggestion) => void;
  searchFieldBadge: string;
  filters: Array<{ label: string; value: string; options: BuyerFilterOption[]; onChange: (value: string) => void }>;
  activeFilterCount: number;
  onClear: () => void;
  total: number;
  totalLabel: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[280px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchValue}
            onChange={(event) => onSearchValueChange(event.target.value)}
            onFocus={onSearchFocus}
            onBlur={onSearchBlur}
            onKeyDown={(event) => event.key === 'Enter' && onSearch()}
            placeholder={placeholder}
            className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 transition-colors bg-white"
          />
          <BuyerSuggestionList open={suggestionsOpen} loading={suggestionsLoading} suggestions={suggestions} onSelect={onSuggestionSelect} />
        </div>
        {filters.map((filter) => <FilterSelect key={filter.label} label={filter.label} value={filter.value} options={filter.options} onChange={filter.onChange} />)}
        <button onClick={onSearch} className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-600 hover:text-brand-600 transition-colors bg-white">搜索</button>
        {activeFilterCount > 0 && <button onClick={onClear} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">清空条件</button>}
        <span className="text-xs text-gray-400">共 {total} 个{totalLabel}</span>
      </div>
      {searchFieldBadge && <div className="flex items-center gap-2 text-xs text-gray-500"><span className="inline-flex items-center gap-1 bg-brand-50 text-brand-700 px-2 py-1"><Tag className="w-3 h-3" />{searchFieldBadge}</span></div>}
    </div>
  );
}

function BuyerSuggestionList({ open, loading, suggestions, onSelect }: { open: boolean; loading: boolean; suggestions: BuyerSuggestion[]; onSelect: (suggestion: BuyerSuggestion) => void }) {
  if (!open) return null;
  return (
    <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-40 border border-gray-200 bg-white shadow-lg">
      {loading ? (
        <div className="flex items-center gap-2 px-3 py-3 text-xs text-gray-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />正在查找匹配项...</div>
      ) : suggestions.length === 0 ? (
        <div className="px-3 py-3 text-xs text-gray-400">暂无匹配建议，回车可全文搜索</div>
      ) : (
        <div className="py-1">
          {suggestions.map((suggestion) => (
            <button key={`${suggestion.id}-${suggestion.search_field}`} type="button" onMouseDown={(event) => { event.preventDefault(); onSelect(suggestion); }} className="w-full px-3 py-2 text-left hover:bg-brand-50 transition-colors">
              <div className="flex items-center gap-2"><span className="max-w-[260px] truncate text-sm text-gray-900">{suggestion.match_text}</span><span className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600"><Tag className="h-2.5 w-2.5" />{suggestion.match_label}</span></div>
              <p className="mt-0.5 truncate text-[11px] text-gray-400">{suggestionSubtitle(suggestion)}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: BuyerFilterOption[]; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const selectedOption = options.find((option) => option.value === value);
  const displayText = selectedOption ? selectedOption.label : '全部';
  return (
    <div className="relative w-[180px]">
      <button type="button" onClick={() => setOpen((current) => !current)} onBlur={() => window.setTimeout(() => setOpen(false), 120)} className="flex w-full items-center justify-between gap-2 border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-600 outline-none transition-colors hover:border-brand-300 focus:border-brand-600" title={`${label} ${displayText}`}>
        <span className="truncate">{label} {displayText}</span><ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+4px)] z-40 max-h-64 w-[220px] overflow-y-auto border border-gray-200 bg-white py-1 shadow-lg">
          <button type="button" onMouseDown={(event) => { event.preventDefault(); onChange(''); setOpen(false); }} className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-brand-50 ${!value ? 'text-brand-700' : 'text-gray-700'}`}><span className="truncate">{label} 全部</span></button>
          {options.map((option) => (
            <button key={option.value} type="button" onMouseDown={(event) => { event.preventDefault(); onChange(option.value); setOpen(false); }} className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-brand-50 ${value === option.value ? 'text-brand-700' : 'text-gray-700'}`} title={option.label}>
              <span className="truncate">{option.label}</span><span className="shrink-0 text-xs text-gray-400">{option.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function BulkActionBar({
  count,
  label,
  deleting,
  onClear,
  onDelete,
  assignOptions,
  assignValue,
  onAssignValueChange,
  onAssign,
  assigning,
}: {
  count: number;
  label: string;
  deleting: boolean;
  onClear: () => void;
  onDelete: () => void;
  assignOptions?: AppUserOption[];
  assignValue?: string;
  onAssignValueChange?: (value: string) => void;
  onAssign?: () => void;
  assigning?: boolean;
}) {
  const admin = isAdmin();
  return (
    <div className="flex items-center justify-between gap-3 border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
      <span className="text-amber-800">已选择 {count} 个{label}</span>
      <div className="flex items-center gap-2">
        <button onClick={onClear} className="px-3 py-1.5 text-xs text-amber-700 hover:text-amber-900">取消选择</button>
        {admin && assignOptions && onAssign && (
          <>
            <select
              value={assignValue || ''}
              onChange={(event) => onAssignValueChange?.(event.target.value)}
              className="border border-amber-300 bg-white px-2 py-1.5 text-xs text-gray-700"
            >
              <option value="">选择负责人...</option>
              {assignOptions
                .filter((option) => option.status === 'active')
                .map((option) => (
                  <option key={option.id} value={option.id}>{option.name}</option>
                ))}
            </select>
            <button
              onClick={onAssign}
              disabled={assigning || !assignValue}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {assigning && <Loader2 className="w-3 h-3 animate-spin" />}
              批量指派
            </button>
          </>
        )}
        {admin && (
          <button onClick={onDelete} disabled={deleting} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">
            {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
            批量删除
          </button>
        )}
      </div>
    </div>
  );
}

function PaginationFooter({ page, pageCount, pageSize, loading, onPageChange }: { page: number; pageCount: number; pageSize: number; loading: boolean; onPageChange: (page: number) => void }) {
  return (
    <div className="flex items-center justify-between gap-3 border border-gray-200 border-t-0 bg-white px-4 py-3 text-sm text-gray-500">
      <span>第 {page} / {pageCount} 页 · 每页 {pageSize} 条</span>
      <div className="flex items-center gap-2"><button onClick={() => onPageChange(Math.max(1, page - 1))} disabled={page <= 1 || loading} className="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-700">上一页</button><button onClick={() => onPageChange(Math.min(pageCount, page + 1))} disabled={page >= pageCount || loading} className="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-700">下一页</button></div>
    </div>
  );
}

function listingRequirementLabel(item: BuyerIntent): string {
  const parts = [item.preferred_listed_status ? valueLabel('preferred_listed_status', item.preferred_listed_status) : null, item.listing_board_requirement_summary, item.financing_stage_requirement_summary].filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

function marketCapRangeLabel(item: BuyerIntent): string {
  if (item.market_cap_range_summary) return item.market_cap_range_summary;
  const min = item.min_market_cap_yuan ? `${(Number(item.min_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  const max = item.max_market_cap_yuan ? `${(Number(item.max_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  if (min && max) return `${min}-${max}`;
  if (min) return `≥${min}`;
  if (max) return `≤${max}`;
  return '-';
}

function compactRequirementNotes(item: BuyerIntent): string {
  const industry = [item.industry_primary, item.industry_secondary].filter(Boolean).join('/');
  const profit = item.min_net_profit_yuan ? `净利≥${formatCompactMoney(Number(item.min_net_profit_yuan))}` : null;
  const marketCap = marketCapRangeLabel(item);
  const parts = [
    industry || null,
    item.region_scope_summary,
    listingRequirementLabel(item) !== '-' ? listingRequirementLabel(item) : null,
    profit,
    item.max_pe ? `PE≤${Number(item.max_pe).toFixed(0)}` : null,
    marketCap !== '-' ? `市值${marketCap}` : null,
    item.max_debt_ratio ? `负债率≤${Number(item.max_debt_ratio).toFixed(0)}%` : null,
    item.max_premium_rate ? `溢价≤${Number(item.max_premium_rate).toFixed(0)}%` : item.premium_tolerance_summary,
    item.major_risk_tolerance_summary,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '暂无关键门槛';
}

function formatCompactMoney(value: number): string {
  if (!Number.isFinite(value)) return '-';
  if (Math.abs(value) < 10000) return `${value.toFixed(0)}元`;
  if (Math.abs(value) < 100000000) return `${(value / 10000).toFixed(0)}万`;
  return `${(value / 100000000).toFixed(1)}亿`;
}

function shortDate(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function ParseStatusBadge({ item, parseStatus }: { item: BuyerIntent; parseStatus?: BuyerIntentParseStatus }) {
  const job = parseStatus?.latest_job;
  const status = job?.status;
  const isActive = status === 'queued' || status === 'running' || status === 'retry_waiting';
  let label = hasStructuredIntentFields(item) ? '已解析' : '待解析';
  let color = hasStructuredIntentFields(item) ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500';

  if (status === 'queued') {
    label = '排队中';
    color = 'bg-blue-50 text-blue-700';
  } else if (status === 'running') {
    label = '解析中';
    color = 'bg-blue-50 text-blue-700';
  } else if (status === 'retry_waiting') {
    label = '重试中';
    color = 'bg-amber-50 text-amber-700';
  } else if (status === 'succeeded') {
    label = '已解析';
    color = 'bg-emerald-50 text-emerald-700';
  } else if (status === 'failed') {
    label = '解析失败';
    color = 'bg-red-50 text-red-700';
  } else if (status === 'cancelled') {
    label = '已取消';
    color = 'bg-gray-100 text-gray-600';
  }

  const title = job?.error_message
    || (job ? `任务 ${job.status}，尝试 ${job.attempt_count}/${job.max_attempts}` : undefined);

  return (
    <span title={title} className={`inline-flex items-center justify-center gap-1 whitespace-nowrap px-2 py-0.5 text-xs font-medium ${color}`}>
      {isActive && <Loader2 className="h-3 w-3 animate-spin" />}
      {label}
    </span>
  );
}

function isActiveParseStatus(status: BuyerIntentParseStatus): boolean {
  const jobStatus = status.latest_job?.status;
  return jobStatus === 'queued' || jobStatus === 'running' || jobStatus === 'retry_waiting';
}

function hasStructuredIntentFields(item: BuyerIntent): boolean {
  return Boolean(
    item.intent_summary
    || item.industry_primary
    || item.industry_secondary
    || item.region_scope_summary
    || item.min_revenue_yuan
    || item.min_net_profit_yuan
    || item.max_valuation_yuan
    || item.market_cap_range_summary
    || (item.preferred_listed_status && item.preferred_listed_status !== 'unknown')
    || (item.requires_consolidation && item.requires_consolidation !== 'unknown')
    || (item.requires_control && item.requires_control !== 'unknown')
    || item.transaction_type
    || item.major_risk_tolerance_summary
    || item.preference_summary
  );
}

function IntentStatusBadge({ status }: { status: string }) {
  const color = status === 'active'
    ? 'bg-emerald-50 text-emerald-700'
    : status === 'paused'
      ? 'bg-amber-50 text-amber-700'
      : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-2 py-0.5 font-medium ${color}`}>{valueLabel('buyer_intent_status', status)}</span>;
}

function PartyStatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-2 py-0.5 font-medium ${color}`}>{valueLabel('buyer_party_status', status)}</span>;
}

function dedupMatchLabel(value: string): string {
  if (value === 'buyer_name') return '买家名称';
  if (value === 'legal_name') return '公司全称';
  if (value === 'alias') return '别名';
  return value;
}


function readIntentFilters(searchParams: URLSearchParams): BuyerIntentFilters {
  const searchFieldParam = searchParams.get('searchField');
  return { q: searchParams.get('q') || '', searchField: isBuyerIntentSearchField(searchFieldParam) ? searchFieldParam : undefined, industry: searchParams.get('industry') || '', region: searchParams.get('region') || '', status: searchParams.get('status') || '', listedStatus: searchParams.get('listedStatus') || '', requiresConsolidation: searchParams.get('requiresConsolidation') || '', owner: searchParams.get('owner') || '', page: Math.max(1, Number(searchParams.get('page') || '1') || 1) };
}

function readPartyFilters(searchParams: URLSearchParams): BuyerPartyFilters {
  const searchFieldParam = searchParams.get('partySearchField');
  return { q: searchParams.get('partyQ') || '', searchField: isBuyerPartySearchField(searchFieldParam) ? searchFieldParam : undefined, buyerType: searchParams.get('buyerType') || '', region: searchParams.get('partyRegion') || '', listedStatus: searchParams.get('partyListedStatus') || '', status: searchParams.get('partyStatus') || '', owner: searchParams.get('partyOwner') || '', page: Math.max(1, Number(searchParams.get('partyPage') || '1') || 1) };
}

function isBuyerIntentSearchField(value: string | null): value is BuyerIntentSearchField { return value === 'intent_name' || value === 'buyer_name' || value === 'raw_requirement_text' || value === 'intent_summary'; }
function isBuyerPartySearchField(value: string | null): value is BuyerPartySearchField { return value === 'buyer_name' || value === 'legal_name' || value === 'main_business' || value === 'profile_summary'; }
function setOrDelete(params: URLSearchParams, key: string, value: string | undefined) { if (value) params.set(key, value); else params.delete(key); }

function suggestionSubtitle(suggestion: BuyerSuggestion): string {
  if ('intent_name' in suggestion) {
    if (suggestion.match_type === 'intent') return suggestion.buyer_name || suggestion.snippet || '点击按意向检索';
    if (suggestion.match_type === 'buyer') return suggestion.intent_name;
    return suggestion.intent_name || suggestion.snippet || '点击按该字段检索';
  }
  if (suggestion.match_type === 'buyer') return suggestion.legal_name || suggestion.snippet || '点击按买家检索';
  if (suggestion.match_type === 'legal') return suggestion.buyer_name;
  return suggestion.buyer_name || suggestion.snippet || '点击按该字段检索';
}

type BuyerIntakeForm = {
  buyer_name: string;
  raw_requirement_text: string;
};

const DEFAULT_BUYER_INTAKE_FORM: BuyerIntakeForm = {
  buyer_name: '',
  raw_requirement_text: '',
};

function CreateIntentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [dedupCheck, setDedupCheck] = useState<BuyerPartyDedupCheck | null>(null);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [checkingDedup, setCheckingDedup] = useState(false);
  const [form, setForm] = useState<BuyerIntakeForm>(DEFAULT_BUYER_INTAKE_FORM);
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (uploadPolicy) return;
    let cancelled = false;
    setPolicyError(null);
    setPolicyLoading(true);
    withTimeout(
      attachments.uploadPolicy(),
      UPLOAD_POLICY_TIMEOUT_MS,
      '读取上传规则超时，可先按默认规则继续选择附件'
    )
      .then((policy) => {
        if (!cancelled) setUploadPolicy(policy);
      })
      .catch((err) => {
        if (!cancelled) setPolicyError(err instanceof Error ? err.message : '读取上传规则失败');
      })
      .finally(() => {
        if (!cancelled) setPolicyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [uploadPolicy]);

  function updateForm<K extends keyof BuyerIntakeForm>(key: K, value: BuyerIntakeForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function addFiles(incoming: File[]) {
    if (!incoming.length) return;
    const nextFiles = [...selectedFiles];
    const errors: string[] = [];
    const maxFiles = uploadPolicy?.max_files_per_business_update || 10;
    const maxBytes = uploadPolicy?.max_upload_bytes || 25 * 1024 * 1024;
    for (const file of incoming) {
      if (nextFiles.length >= maxFiles) {
        errors.push(`单次最多上传 ${maxFiles} 个附件。`);
        break;
      }
      if (file.size > maxBytes) {
        errors.push(`${file.name} 超过 ${formatBytes(maxBytes)}。`);
        continue;
      }
      if (nextFiles.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) {
        continue;
      }
      nextFiles.push(file);
    }
    setSelectedFiles(nextFiles);
    setFileError(errors[0] || null);
  }

  function handleFileSelect(event: ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files || []));
    event.target.value = '';
  }

  function handleFileDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    addFiles(Array.from(event.dataTransfer.files || []));
  }

  function removeFile(index: number) {
    setSelectedFiles((files) => files.filter((_, itemIndex) => itemIndex !== index));
    setFileError(null);
  }

  const handleDedupCheck = async () => {
    const buyerName = form.buyer_name.trim();
    if (!buyerName) return;
    setCheckingDedup(true);
    try {
      const response = await buyerParties.dedupCheck({ q: buyerName, limit: 5 });
      setDedupCheck(response);
      setDedupChecked(true);
    } catch {
      setDedupCheck(null);
      setDedupChecked(true);
    } finally {
      setCheckingDedup(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const buyerName = form.buyer_name.trim();
    if (!buyerName) return;

    setSaving(true);
    setSubmitError(null);
    try {
      const materialText = form.raw_requirement_text.trim();
      const shouldParse = selectedFiles.length > 0 || materialText.length > 0;
      const rawText = buildBuyerIntakeRawText(buyerName, materialText);
      const createdParty = await buyerParties.create({ buyer_name: buyerName });
      const createdIntent = await buyerIntents.create({
        buyer_party_id: createdParty.id,
        intent_name: defaultBuyerIntentName(buyerName),
        raw_requirement_text: shouldParse ? rawText : undefined,
      });

      if (shouldParse) {
        if (selectedFiles.length > 0) {
          const formData = new FormData();
          formData.set('raw_text', rawText);
          formData.set('input_type', 'mixed');
          formData.set('auto_process', 'true');
          formData.set('process_after_ocr', 'true');
          formData.set('include_attachment_text', 'true');
          formData.set('bound_buyer_intent_ids', JSON.stringify([createdIntent.id]));
          formData.set(
            'metadata_json',
            JSON.stringify({
              source: 'frontend_buyer_create_modal',
              buyer_party_id: createdParty.id,
              buyer_intent_id: createdIntent.id,
              buyer_name: buyerName,
            })
          );
          selectedFiles.forEach((file) => formData.append('files', file));
          await businessUpdates.upload(formData);
        } else {
          await buyerIntents.parse(createdIntent.id, { raw_requirement_text: rawText });
        }
      }
      onCreated();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="新建买家" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
          <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
          <p className="leading-relaxed">
            录入买家和当前并购需求。系统会从文本和附件中解析需求内容，买家资料可在详情页中手工维护。
          </p>
        </div>

        <Field label="买家名称 *">
          <div className="flex gap-2">
            <input
              type="text"
              value={form.buyer_name}
              onChange={(e) => {
                updateForm('buyer_name', e.target.value);
                setDedupChecked(false);
                setDedupCheck(null);
              }}
              placeholder="例如：北控集团、杭州某上市公司"
              className="input flex-1"
              autoFocus
            />
            <button
              type="button"
              onClick={handleDedupCheck}
              disabled={checkingDedup || !form.buyer_name.trim()}
              className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap"
            >
              {checkingDedup ? '查重中' : '查重'}
            </button>
          </div>
        </Field>

        {dedupChecked && Boolean(dedupCheck?.matches.length) && (
          <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-700">发现相似买家，请确认是否重复录入：</p>
            {dedupCheck!.matches.map((match) => (
              <div key={`${match.buyer_name}-${match.match_type}`} className="text-sm text-gray-800">
                <span className="font-medium">{match.buyer_name}</span>
                {match.legal_name && <span className="text-xs text-gray-500"> · {match.legal_name}</span>}
                <span className="ml-2 text-xs text-amber-700">负责人：{match.owner_name || '未指派'}</span>
                <span className="ml-2 text-xs text-gray-500">匹配：{dedupMatchLabel(match.match_type)}</span>
              </div>
            ))}
            <p className="text-xs text-amber-700">如确认为同一买家，建议取消后在该买家详情中录入更新；当前仍允许继续创建。</p>
          </div>
        )}
        {dedupChecked && !dedupCheck?.matches.length && (
          <p className="text-xs text-emerald-600">未发现同名买家。</p>
        )}

        <Field label="需求材料">
          <textarea
            value={form.raw_requirement_text}
            onChange={(e) => updateForm('raw_requirement_text', e.target.value)}
            className="input min-h-[170px] resize-y leading-relaxed"
            placeholder={'可粘贴买家的聊天记录、邮件、投资偏好或访谈纪要。\n建议包含：关注行业、地区范围、上市/非上市偏好、市值或估值、利润/PE/负债率、股权比例、交易方式、排除项。\n示例：关注长三角医药健康资产，净利润2000万以上，优先控股并表，不接受重大诉讼或执行风险。'}
          />
        </Field>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">附件/截图</label>
          <div
            className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-600 transition-colors hover:border-brand-300 hover:bg-brand-50/40"
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleFileDrop}
          >
            <div className="flex gap-2">
              <div className="flex items-center gap-2 text-gray-800 font-medium">
                <Upload className="w-4 h-4 text-brand-600" />
                拖拽文件到这里，或上传图片、PDF、Office、文本附件
              </div>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="ml-auto shrink-0 bg-white border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-brand-300 hover:text-brand-700"
              >
                选择文件
              </button>
            </div>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} />
            <UploadPolicyCard policy={uploadPolicy} loading={policyLoading} error={policyError} />
            <SelectedFiles files={selectedFiles} onRemove={removeFile} />
            {fileError && <InlineWarning message={fileError} />}
          </div>
        </div>

        {submitError && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>}

        <div className="flex items-center justify-between gap-3 pt-2">
          <p className="text-xs text-gray-400">
            {selectedFiles.length > 0 || form.raw_requirement_text.trim()
              ? '创建后会自动进入解析队列，解析结果可在需求详情查看。'
              : '仅创建买家和基础需求，不触发解析。'}
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
            <button type="submit" disabled={saving || !form.buyer_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-2">
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {saving ? '创建中...' : selectedFiles.length > 0 || form.raw_requirement_text.trim() ? '创建并解析' : '创建买家'}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function defaultBuyerIntentName(buyerName: string): string {
  const yearMonth = new Date().toISOString().slice(0, 7);
  return `${buyerName}-并购需求（${yearMonth}）`;
}

function buildBuyerIntakeRawText(buyerName: string, materialText: string): string {
  const lines = [
    '【新建买家及并购需求初始输入】',
    `买家名称：${buyerName}`,
    '',
    '解析要求：只提取买家意向字段（行业、地区、利润、市值/估值、PE、溢价、负债率、上市偏好、股权比例、交易方式、风险容忍和排除项）。不要生成或修改买家主体资料。行业和地区请输出中文，不要臆造材料中没有的信息。',
  ];

  if (materialText) {
    lines.push('', '【需求原文/补充材料】', materialText);
  }

  return lines.join('\n');
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timer: number | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer !== undefined) window.clearTimeout(timer);
  });
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function UploadPolicyCard({
  policy,
  loading,
  error,
}: {
  policy: AttachmentUploadPolicy | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        正在读取上传规则...
      </div>
    );
  }

  if (error) return <InlineWarning message={error} />;
  if (!policy) return <p className="mt-3 text-xs text-gray-400">上传规则暂不可用。</p>;

  const image = policy.image_policy.constraints;
  const pdf = policy.pdf_policy.text_detection;
  const doc2xStatus = policy.pdf_policy.scanned_pdf.doc2x_configured ? '已配置' : '未配置';

  return (
    <div className="mt-3 space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <PolicyStat label="单文件上限" value={`${policy.max_upload_mb} MB`} />
        <PolicyStat label="附件数量" value={`${policy.max_files_per_business_update} 个/次`} />
        <PolicyStat label="图片数量" value={`${image.max_count_per_business_update} 张/次`} />
      </div>
      <div className="grid grid-cols-1 gap-2 text-xs">
        <PolicyLine
          icon={Image}
          title="截图 / 图片"
          body={`支持 ${image.supported_types.join('、')}；不走 OCR，直接交给多模态模型；会压缩到最长边 ${image.model_preprocess_max_side_px}px。`}
        />
        <PolicyLine
          icon={FileText}
          title="PDF"
          body={`前 ${pdf.sample_page_limit} 页累计文本不少于 ${pdf.min_total_chars_for_text_pdf} 字按文本 PDF 本地解析；扫描件走 Doc2X 异步 OCR（${doc2xStatus}）。`}
        />
      </div>
    </div>
  );
}

function SelectedFiles({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  if (!files.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {files.map((file, index) => (
        <div key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center justify-between gap-3 bg-white border border-gray-200 px-3 py-2">
          <div className="min-w-0 flex items-center gap-2">
            <Paperclip className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-gray-800">{file.name}</p>
              <p className="text-[11px] text-gray-400">{formatBytes(file.size)}</p>
            </div>
          </div>
          <button type="button" onClick={() => onRemove(index)} className="shrink-0 text-xs text-gray-400 hover:text-red-600">
            移除
          </button>
        </div>
      ))}
    </div>
  );
}

function InlineWarning({ message }: { message: string }) {
  return (
    <div className="mt-3 flex items-start gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function PolicyStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border border-gray-200 px-3 py-2">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function PolicyLine({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) {
  return (
    <div className="flex gap-2 bg-white border border-gray-200 px-3 py-2">
      <Icon className="w-3.5 h-3.5 text-brand-600 mt-0.5 shrink-0" />
      <div>
        <p className="font-medium text-gray-800">{title}</p>
        <p className="mt-0.5 text-gray-500 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}

function CreatePartyModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<BuyerPartyCreate>({ buyer_name: '' });
  const [saving, setSaving] = useState(false);
  const [dedupCheck, setDedupCheck] = useState<BuyerPartyDedupCheck | null>(null);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [checkingDedup, setCheckingDedup] = useState(false);

  const handleDedupCheck = async () => {
    if (!form.buyer_name.trim()) return;
    setCheckingDedup(true);
    try {
      const response = await buyerParties.dedupCheck({ q: form.buyer_name.trim(), limit: 5 });
      setDedupCheck(response);
      setDedupChecked(true);
    } catch {
      setDedupCheck(null);
      setDedupChecked(true);
    } finally {
      setCheckingDedup(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.buyer_name.trim()) return;
    setSaving(true);
    try {
      await buyerParties.create(form);
      onCreated();
    } catch {
      alert('创建失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="新建买家主体" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="买家名称 *">
          <div className="flex gap-2">
            <input
              type="text"
              value={form.buyer_name}
              onChange={(e) => {
                setForm({ ...form, buyer_name: e.target.value });
                setDedupChecked(false);
                setDedupCheck(null);
              }}
              className="input flex-1"
              placeholder="例如：浙江某国资平台"
              autoFocus
            />
            <button
              type="button"
              onClick={handleDedupCheck}
              disabled={checkingDedup || !form.buyer_name.trim()}
              className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap"
            >
              {checkingDedup ? '查重中' : '查重'}
            </button>
          </div>
        </Field>
        {dedupChecked && Boolean(dedupCheck?.matches.length) && (
          <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-700">系统里已有同名或别名买家，请确认是否重复录入：</p>
            {dedupCheck!.matches.map((match) => (
              <div key={`${match.buyer_name}-${match.match_type}`} className="text-sm text-gray-800">
                <span className="font-medium">{match.buyer_name}</span>
                {match.legal_name && <span className="text-xs text-gray-500"> · {match.legal_name}</span>}
                <span className="ml-2 text-xs text-amber-700">负责人：{match.owner_name || '未指派'}</span>
                <span className="ml-2 text-xs text-gray-500">匹配：{dedupMatchLabel(match.match_type)}</span>
              </div>
            ))}
          </div>
        )}
        {dedupChecked && !dedupCheck?.matches.length && (
          <p className="text-xs text-emerald-600">未发现同名买家。</p>
        )}
        <Field label="公司全称">
          <input type="text" value={form.legal_name || ''} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} className="input" placeholder="浙江某国资平台有限公司" />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="买家类型">
            <input type="text" value={form.buyer_type || ''} onChange={(e) => setForm({ ...form, buyer_type: e.target.value })} className="input" placeholder="state_owned_platform" />
          </Field>
          <Field label="所在省份">
            <input type="text" value={form.region_province || ''} onChange={(e) => setForm({ ...form, region_province: e.target.value })} className="input" placeholder="浙江省" />
          </Field>
        </div>
        <Field label="主营业务">
          <input type="text" value={form.main_business || ''} onChange={(e) => setForm({ ...form, main_business: e.target.value })} className="input" placeholder="国资产业投资与并购整合" />
        </Field>
        <Field label="资金实力/规模">
          <textarea value={form.capital_strength_summary || ''} onChange={(e) => setForm({ ...form, capital_strength_summary: e.target.value })} className="input min-h-[60px] resize-y" />
        </Field>
        <Field label="材料摘要">
          <textarea value={form.profile_summary || ''} onChange={(e) => setForm({ ...form, profile_summary: e.target.value })} className="input min-h-[60px] resize-y" />
        </Field>
        <Field label="备注">
          <textarea value={form.notes || ''} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="input min-h-[70px] resize-y" placeholder="人工维护，不参与推荐" />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
          <button type="submit" disabled={saving || !form.buyer_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
            {saving ? '创建中...' : '创建'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white border border-gray-200 shadow-lg w-full max-w-2xl mx-4 max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
