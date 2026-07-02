import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  Building2,
  ChevronDown,
  ChevronUp,
  FileText,
  Image,
  Loader2,
  MessageSquarePlus,
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
import { attachments, businessUpdates, buyerParties, buyerIntents } from '../lib/api';
import type {
  AttachmentUploadPolicy,
  BuyerFilterOption,
  BuyerIntent,
  BuyerIntentCreate,
  BuyerIntentFilterOptions,
  BuyerIntentParseStatus,
  BuyerIntentSearchField,
  BuyerIntentSuggestion,
  BuyerParty,
  BuyerPartyCreate,
  BuyerPartyFilterOptions,
  BuyerPartySearchField,
  BuyerPartySuggestion,
} from '../types/api';
import { valueLabel } from '../lib/fieldLabels';

type Tab = 'intents' | 'parties';
type BuyerSuggestion = BuyerIntentSuggestion | BuyerPartySuggestion;

const PAGE_SIZE = 20;
const INTENT_PARSE_STATUS_POLL_INTERVAL_MS = 5000;
const UPLOAD_POLICY_TIMEOUT_MS = 12000;
const INTENT_FILTERS: Array<keyof BuyerIntentFilters> = ['q', 'industry', 'region', 'status', 'listedStatus', 'requiresConsolidation'];
const PARTY_FILTERS: Array<keyof BuyerPartyFilters> = ['q', 'buyerType', 'region', 'listedStatus', 'status'];

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
  intent_name: '意向',
  buyer_name: '买家',
  raw_requirement_text: '需求',
  intent_summary: '摘要',
};

const PARTY_SEARCH_FIELD_LABELS: Record<BuyerPartySearchField | 'all', string> = {
  all: '全部字段',
  buyer_name: '买家',
  legal_name: '法律主体',
  main_business: '主营业务',
  profile_summary: '画像',
};

type BuyerIntentFilters = {
  q: string;
  searchField?: BuyerIntentSearchField;
  industry: string;
  region: string;
  status: string;
  listedStatus: string;
  requiresConsolidation: string;
  page: number;
};

type BuyerPartyFilters = {
  q: string;
  searchField?: BuyerPartySearchField;
  buyerType: string;
  region: string;
  listedStatus: string;
  status: string;
  page: number;
};

export default function Buyers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = readTab(searchParams);
  const [showCreateIntent, setShowCreateIntent] = useState(false);
  const [showCreateParty, setShowCreateParty] = useState(false);
  const [intentRefreshKey, setIntentRefreshKey] = useState(0);
  const [partyRefreshKey, setPartyRefreshKey] = useState(0);

  const setTab = useCallback((nextTab: Tab) => {
    const next = new URLSearchParams(searchParams);
    if (nextTab === 'intents') next.delete('tab');
    else next.set('tab', nextTab);
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    const action = searchParams.get('action');
    if (action !== 'new-intent' && action !== 'new-party') return;
    const next = new URLSearchParams(searchParams);
    if (action === 'new-intent') {
      next.delete('tab');
      setShowCreateIntent(true);
    } else {
      next.set('tab', 'parties');
      setShowCreateParty(true);
    }
    next.delete('action');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">买家管理</h1>
          <p className="text-xs text-gray-400 mt-1">统一维护买家意向、买家主体和后续推荐入口</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateIntent(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建买家意向
          </button>
          <button
            onClick={() => { setTab('parties'); setShowCreateParty(true); }}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors bg-white"
          >
            <Plus className="w-4 h-4" />
            新建买家
          </button>
        </div>
      </div>

      <div className="border-b border-gray-200 flex items-center gap-0.5">
        <button
          onClick={() => setTab('intents')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${tab === 'intents' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
        >
          买家意向
        </button>
        <button
          onClick={() => setTab('parties')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${tab === 'parties' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
        >
          买家主体
        </button>
      </div>

      {tab === 'intents' ? (
        <IntentsList
          externalShowCreate={showCreateIntent}
          onExternalCreateClose={() => setShowCreateIntent(false)}
          refreshKey={intentRefreshKey}
          onCreated={() => setIntentRefreshKey((k) => k + 1)}
        />
      ) : (
        <PartiesList
          externalShowCreate={showCreateParty}
          onExternalCreateClose={() => setShowCreateParty(false)}
          refreshKey={partyRefreshKey}
          onCreated={() => setPartyRefreshKey((k) => k + 1)}
        />
      )}
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
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterOptions, setFilterOptions] = useState<BuyerIntentFilterOptions>(EMPTY_INTENT_FILTER_OPTIONS);
  const [suggestions, setSuggestions] = useState<BuyerIntentSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [parseStatuses, setParseStatuses] = useState<Record<string, BuyerIntentParseStatus>>({});

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
    if (!window.confirm(`确认删除已选择的 ${ids.length} 个买家意向？删除后不会出现在列表和推荐候选里。`)) return;
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

  const clearFilters = () => {
    setSearchQuery('');
    updateFilters({ q: '', searchField: undefined, industry: '', region: '', status: '', listedStatus: '', requiresConsolidation: '', page: 1 });
  };

  return (
    <>
      <ListToolbar
        searchValue={searchQuery}
        placeholder="搜索意向、买家、需求或摘要..."
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
        ]}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
        total={total}
        totalLabel="买家意向"
      />

      {selectedCount > 0 && <BulkActionBar count={selectedCount} label="买家意向" deleting={bulkDeleting} onClear={() => setSelectedIds(new Set())} onDelete={handleBulkDelete} />}

      <div className="bg-white border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 w-12"><input type="checkbox" disabled={visibleIds.length === 0} checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="选择当前页买家意向" className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">意向名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">买家主体</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">行业</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">地区</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">上市要求</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">利润要求</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">市值范围</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">解析状态</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">状态</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={11} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={11} className="px-4 py-8 text-center text-gray-400">暂无匹配的买家意向</td></tr>
            ) : items.map((item) => (
              <IntentRow
                key={item.id}
                item={item}
                parseStatus={parseStatuses[item.id]}
                expanded={expandedId === item.id}
                selected={selectedIds.has(item.id)}
                onSelectedChange={(checked) => toggleSelected(item.id, checked)}
                onToggle={() => setExpandedId(expandedId === item.id ? null : item.id)}
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
  expanded,
  selected,
  onSelectedChange,
  onToggle,
}: {
  item: BuyerIntent;
  parseStatus?: BuyerIntentParseStatus;
  expanded: boolean;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="hover:bg-brand-50/30 transition-colors">
        <td className="px-4 py-3"><input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择${item.intent_name}`} className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></td>
        <td className="px-4 py-3"><div className="flex items-center gap-1"><button onClick={onToggle} className="text-gray-400 hover:text-gray-600" type="button">{expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</button><span className="font-medium text-gray-900">{item.intent_name}</span></div></td>
        <td className="px-4 py-3 text-gray-600">{item.buyer_party_id ? <Link to={`/buyers/${item.buyer_party_id}?intentId=${item.id}`} className="hover:text-brand-600 transition-colors">{item.buyer_name || '已关联买家'}</Link> : '-'}</td>
        <td className="px-4 py-3 text-gray-600">{item.industry_primary || '-'}</td>
        <td className="px-4 py-3 text-gray-600 max-w-[180px] truncate" title={item.region_scope_summary || undefined}>{item.region_scope_summary || '-'}</td>
        <td className="px-4 py-3 text-gray-600">{listingRequirementLabel(item)}</td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">{item.min_net_profit_yuan ? `${(Number(item.min_net_profit_yuan) / 10000).toFixed(0)}万` : '-'}</td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">{marketCapRangeLabel(item)}</td>
        <td className="px-4 py-3 text-center"><ParseStatusBadge item={item} parseStatus={parseStatus} /></td>
        <td className="px-4 py-3 text-center"><IntentStatusBadge status={item.status} /></td>
        <td className="px-4 py-3"><div className="flex items-center justify-center gap-1"><Link to={`/recommendations?mode=buyer-to-target&intentId=${item.id}`} className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 transition-colors"><Sparkles className="w-3 h-3" />推荐标的</Link><span className="text-gray-200">|</span><button className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 transition-colors" type="button"><MessageSquarePlus className="w-3 h-3" />录入更新</button></div></td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50/50"><td colSpan={11} className="px-8 py-2.5"><div className="space-y-1"><p className="text-xs text-gray-600 line-clamp-2">{item.raw_requirement_text || item.intent_summary || '暂无摘要'}{item.requires_consolidation === 'yes' && <span className="text-gray-500 ml-2">· 需并表</span>}{item.buyer_party_id ? '' : <span className="text-amber-600 ml-2">· 未关联买家主体</span>}</p><p className="text-xs text-gray-500 line-clamp-1">{compactRequirementNotes(item)}</p></div></td></tr>
      )}
    </>
  );
}


function PartiesList({
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

  const clearFilters = () => {
    setSearchQuery('');
    updateFilters({ q: '', searchField: undefined, buyerType: '', region: '', listedStatus: '', status: '', page: 1 });
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
        ]}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
        total={total}
        totalLabel="买家主体"
      />

      {selectedCount > 0 && <BulkActionBar count={selectedCount} label="买家主体" deleting={bulkDeleting} onClear={() => setSelectedIds(new Set())} onDelete={handleBulkDelete} />}

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
              <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">暂无匹配的买家主体</td></tr>
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

function BulkActionBar({ count, label, deleting, onClear, onDelete }: { count: number; label: string; deleting: boolean; onClear: () => void; onDelete: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
      <span className="text-amber-800">已选择 {count} 个{label}</span>
      <div className="flex items-center gap-2"><button onClick={onClear} className="px-3 py-1.5 text-xs text-amber-700 hover:text-amber-900">取消选择</button><button onClick={onDelete} disabled={deleting} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">{deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}批量删除</button></div>
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
  const parts = [item.max_debt_ratio ? `负债率≤${Number(item.max_debt_ratio).toFixed(0)}%` : null, item.max_premium_rate ? `溢价≤${Number(item.max_premium_rate).toFixed(0)}%` : item.premium_tolerance_summary, item.major_risk_tolerance_summary, item.buyer_industry_advantage_summary].filter(Boolean);
  return parts.length ? parts.join(' · ') : '暂无补充约束';
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
  const isActive = status === 'active';
  return <span className={`text-xs px-2 py-0.5 font-medium ${isActive ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>{valueLabel('buyer_intent_status', status)}</span>;
}

function PartyStatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-2 py-0.5 font-medium ${color}`}>{valueLabel('buyer_party_status', status)}</span>;
}

function readTab(searchParams: URLSearchParams): Tab { return searchParams.get('tab') === 'parties' ? 'parties' : 'intents'; }

function readIntentFilters(searchParams: URLSearchParams): BuyerIntentFilters {
  const searchFieldParam = searchParams.get('searchField');
  return { q: searchParams.get('q') || '', searchField: isBuyerIntentSearchField(searchFieldParam) ? searchFieldParam : undefined, industry: searchParams.get('industry') || '', region: searchParams.get('region') || '', status: searchParams.get('status') || '', listedStatus: searchParams.get('listedStatus') || '', requiresConsolidation: searchParams.get('requiresConsolidation') || '', page: Math.max(1, Number(searchParams.get('page') || '1') || 1) };
}

function readPartyFilters(searchParams: URLSearchParams): BuyerPartyFilters {
  const searchFieldParam = searchParams.get('partySearchField');
  return { q: searchParams.get('partyQ') || '', searchField: isBuyerPartySearchField(searchFieldParam) ? searchFieldParam : undefined, buyerType: searchParams.get('buyerType') || '', region: searchParams.get('partyRegion') || '', listedStatus: searchParams.get('partyListedStatus') || '', status: searchParams.get('partyStatus') || '', page: Math.max(1, Number(searchParams.get('partyPage') || '1') || 1) };
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

type IntentStep = 'buyer_link' | 'buyer_search' | 'buyer_new' | 'intent_details';
type BuyerLinkChoice = 'link_existing' | 'create_new' | 'no_link';

type IntentForm = {
  intent_name: string;
  industry_primary: string;
  region_scope_summary: string;
  min_net_profit_yuan: string;
  max_pe: string;
  market_cap_range: string;
  preferred_listed_status: string;
  requires_consolidation: string;
  max_premium_rate: string;
  max_debt_ratio: string;
  raw_requirement_text: string;
  negative_summary: string;
};

const DEFAULT_INTENT_FORM: IntentForm = {
  intent_name: '',
  industry_primary: '',
  region_scope_summary: '',
  min_net_profit_yuan: '',
  max_pe: '',
  market_cap_range: '',
  preferred_listed_status: '',
  requires_consolidation: '',
  max_premium_rate: '',
  max_debt_ratio: '',
  raw_requirement_text: '',
  negative_summary: '',
};

function CreateIntentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [step, setStep] = useState<IntentStep>('buyer_link');
  const [linkChoice, setLinkChoice] = useState<BuyerLinkChoice | null>(null);
  const [selectedParty, setSelectedParty] = useState<BuyerParty | null>(null);
  const [newPartyName, setNewPartyName] = useState('');
  const [dedupResults, setDedupResults] = useState<BuyerParty[]>([]);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<BuyerParty[]>([]);
  const [searching, setSearching] = useState(false);
  const [form, setForm] = useState<IntentForm>(DEFAULT_INTENT_FORM);
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (step !== 'intent_details' || uploadPolicy) return;
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
  }, [step, uploadPolicy]);

  function updateForm<K extends keyof IntentForm>(key: K, value: IntentForm[K]) {
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

  const handleBuyerLinkChoice = (choice: BuyerLinkChoice) => {
    setLinkChoice(choice);
    if (choice === 'link_existing') setStep('buyer_search');
    else if (choice === 'create_new') setStep('buyer_new');
    else setStep('intent_details');
  };

  const handleSearch = async (q: string) => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const response = await buyerParties.list({ q: q.trim(), limit: 10 });
      setSearchResults(response.items);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleNewPartyCheck = async () => {
    if (!newPartyName.trim()) return;
    setSearching(true);
    try {
      const response = await buyerParties.list({ q: newPartyName.trim(), limit: 5 });
      setDedupResults(response.items);
      setDedupChecked(true);
    } catch {
      setDedupResults([]);
      setDedupChecked(true);
    } finally {
      setSearching(false);
    }
  };

  const handleSelectExisting = (party: BuyerParty) => {
    setSelectedParty(party);
    setStep('intent_details');
  };

  const handleConfirmNewParty = async () => {
    if (!newPartyName.trim()) return;
    setSaving(true);
    try {
      const created = await buyerParties.create({ buyer_name: newPartyName.trim() });
      setSelectedParty(created);
      setStep('intent_details');
    } catch {
      alert('创建买家主体失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const intentName = form.intent_name.trim();
    if (!intentName) return;

    const marketCap = parseMarketCapRange(form.market_cap_range);
    if (form.market_cap_range.trim() && marketCap.min === undefined && marketCap.max === undefined) {
      setSubmitError('市值范围暂无法识别，请使用如 5亿-30亿、5亿以上、30亿以内。');
      return;
    }

    setSaving(true);
    setSubmitError(null);
    try {
      const supplement = form.raw_requirement_text.trim();
      const shouldParse = selectedFiles.length > 0 || supplement.length > 0;
      const payload: BuyerIntentCreate = {
        intent_name: intentName,
        buyer_party_id: selectedParty?.id,
        raw_requirement_text: normalizeOptional(form.raw_requirement_text),
        industry_primary: normalizeOptional(form.industry_primary),
        region_scope_summary: normalizeOptional(form.region_scope_summary),
        min_net_profit_yuan: parseMoneyToYuan(form.min_net_profit_yuan),
        max_pe: parseNumberInput(form.max_pe),
        min_market_cap_yuan: marketCap.min,
        max_market_cap_yuan: marketCap.max,
        market_cap_range_summary: normalizeOptional(form.market_cap_range),
        preferred_listed_status: normalizeOptional(form.preferred_listed_status),
        requires_consolidation: normalizeOptional(form.requires_consolidation),
        max_premium_rate: parseNumberInput(form.max_premium_rate),
        max_debt_ratio: parseNumberInput(form.max_debt_ratio),
        negative_summary: normalizeOptional(form.negative_summary),
      };

      const created = await buyerIntents.create(payload);
      if (shouldParse) {
        const rawText = buildIntentRawText(form, payload, selectedParty);
        if (selectedFiles.length > 0) {
          // Attachments (incl. images) go through the business_update pipeline so OCR
          // + multimodal extraction fill the intent, mirroring the target create flow.
          const formData = new FormData();
          formData.set('raw_text', rawText);
          formData.set('input_type', 'mixed');
          formData.set('auto_process', 'true');
          formData.set('process_after_ocr', 'true');
          formData.set('include_attachment_text', 'true');
          formData.set('bound_buyer_intent_ids', JSON.stringify([created.id]));
          if (selectedParty) {
            formData.set('bound_buyer_party_ids', JSON.stringify([selectedParty.id]));
          }
          formData.set(
            'metadata_json',
            JSON.stringify({
              source: 'frontend_intent_create_modal',
              create_payload: payload,
              bound_buyer_intent_ids: [created.id],
            })
          );
          selectedFiles.forEach((file) => formData.append('files', file));
          await businessUpdates.upload(formData);
        } else {
          // Text-only requirements use the dedicated buyer intent parser.
          await buyerIntents.parse(created.id, { raw_requirement_text: supplement });
        }
      }
      onCreated();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  };

  const stepTitles: Record<IntentStep, string> = {
    buyer_link: '新建买家意向 — 关联买家',
    buyer_search: '新建买家意向 — 搜索买家',
    buyer_new: '新建买家意向 — 新建买家主体',
    intent_details: '新建买家意向 — 意向详情',
  };

  return (
    <Modal title={stepTitles[step]} onClose={onClose}>
      {/* Step indicator */}
      <div className="flex items-center gap-1.5 mb-5">
        {(['buyer_link', 'intent_details'] as const).map((s, i) => (
          <div key={s} className="flex items-center gap-1.5">
            <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium ${
              step === s || (i === 1 && (step === 'intent_details'))
                ? 'bg-brand-600 text-white'
                : step === 'intent_details' && s === 'buyer_link'
                  ? 'bg-emerald-500 text-white'
                  : 'bg-gray-200 text-gray-500'
            }`}>
              {i === 0 && step === 'intent_details' ? '✓' : i + 1}
            </div>
            <span className="text-xs text-gray-500">{i === 0 ? '关联买家' : '意向信息'}</span>
            {i === 0 && <div className="w-6 h-px bg-gray-200" />}
          </div>
        ))}
      </div>

      {/* Step 1a: Link choice */}
      {step === 'buyer_link' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600 mb-4">请选择如何关联买家主体：</p>
          {[
            { key: 'link_existing' as BuyerLinkChoice, label: '关联已有买家', desc: '从现有买家主体中搜索并关联' },
            { key: 'create_new' as BuyerLinkChoice, label: '新建买家主体', desc: '先创建买家主体，再建意向' },
            { key: 'no_link' as BuyerLinkChoice, label: '暂不关联', desc: '直接创建意向，后续再关联买家' },
          ].map((opt) => (
            <button
              key={opt.key}
              onClick={() => handleBuyerLinkChoice(opt.key)}
              className={`w-full text-left px-4 py-3 border transition-colors ${
                linkChoice === opt.key ? 'border-brand-500 bg-brand-50' : 'border-gray-200 hover:border-gray-300 bg-white'
              }`}
            >
              <div className="text-sm font-medium text-gray-900">{opt.label}</div>
              <div className="text-xs text-gray-500 mt-0.5">{opt.desc}</div>
            </button>
          ))}
        </div>
      )}

      {/* Step 1b: Search existing buyer */}
      {step === 'buyer_search' && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch(searchQuery)}
              placeholder="输入买家名称搜索..."
              className="input flex-1"
              autoFocus
            />
            <button
              onClick={() => handleSearch(searchQuery)}
              disabled={searching}
              className="px-3 py-2 bg-brand-600 text-white text-sm hover:bg-brand-700 disabled:opacity-50"
            >
              {searching ? '搜索中' : '搜索'}
            </button>
          </div>
          {searchResults.length > 0 && (
            <div className="border border-gray-200 divide-y divide-gray-100 max-h-48 overflow-y-auto">
              {searchResults.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleSelectExisting(p)}
                  className="w-full text-left px-4 py-2.5 hover:bg-brand-50 transition-colors"
                >
                  <span className="text-sm font-medium text-gray-900">{p.buyer_name}</span>
                  {p.legal_name && <span className="text-xs text-gray-400 ml-2">{p.legal_name}</span>}
                  {p.region_province && <span className="text-xs text-gray-400 ml-2">· {p.region_province}</span>}
                </button>
              ))}
            </div>
          )}
          {searchResults.length === 0 && searchQuery && !searching && (
            <p className="text-sm text-gray-400 text-center py-3">未找到匹配买家</p>
          )}
          <div className="flex justify-between pt-2">
            <button onClick={() => setStep('buyer_link')} className="px-3 py-2 text-sm border border-gray-200 text-gray-700">返回</button>
            <button onClick={() => { setStep('intent_details'); }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">跳过关联</button>
          </div>
        </div>
      )}

      {/* Step 1c: Create new buyer party */}
      {step === 'buyer_new' && (
        <div className="space-y-3">
          <Field label="买家名称 *">
            <div className="flex gap-2">
              <input
                type="text"
                value={newPartyName}
                onChange={(e) => { setNewPartyName(e.target.value); setDedupChecked(false); setDedupResults([]); }}
                placeholder="例如：浙江某国资平台"
                className="input flex-1"
                autoFocus
              />
              <button
                onClick={handleNewPartyCheck}
                disabled={searching || !newPartyName.trim()}
                className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap"
              >
                {searching ? '查重中' : '查重'}
              </button>
            </div>
          </Field>
          {dedupChecked && dedupResults.length > 0 && (
            <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
              <p className="text-xs font-medium text-amber-700">发现相似买家，请确认是否已存在：</p>
              {dedupResults.slice(0, 5).map((p) => (
                <div key={p.id} className="flex items-center justify-between">
                  <span className="text-sm text-gray-800">{p.buyer_name}</span>
                  <button onClick={() => handleSelectExisting(p)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">关联它</button>
                </div>
              ))}
            </div>
          )}
          {dedupChecked && dedupResults.length === 0 && (
            <p className="text-xs text-emerald-600">未发现重名买家</p>
          )}
          <div className="flex justify-between pt-2">
            <button onClick={() => setStep('buyer_link')} className="px-3 py-2 text-sm border border-gray-200 text-gray-700">返回</button>
            <button
              onClick={handleConfirmNewParty}
              disabled={saving || !newPartyName.trim()}
              className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {saving ? '创建中...' : '创建并继续'}
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Intent details */}
      {step === 'intent_details' && (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
            <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
            <p className="leading-relaxed">
              可以先填关键条件，再粘贴买家需求原文或上传附件。若材料里识别到更完整的行业、地区、利润/市值/溢价等要求，解析结果会自动补全字段。
            </p>
          </div>

          {selectedParty && (
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border border-gray-200 text-sm">
              <span className="text-gray-500">关联买家：</span>
              <span className="font-medium text-gray-900">{selectedParty.buyer_name}</span>
            </div>
          )}

          <Field label="意向名称 *">
            <input
              type="text"
              value={form.intent_name}
              onChange={(e) => updateForm('intent_name', e.target.value)}
              className="input"
              placeholder="例如：浙江国资医药健康并表需求"
              autoFocus
            />
          </Field>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="行业">
              <input type="text" value={form.industry_primary} onChange={(e) => updateForm('industry_primary', e.target.value)} className="input" placeholder="可选，如医药健康；留空由系统解析" />
            </Field>
            <Field label="地区范围">
              <input type="text" value={form.region_scope_summary} onChange={(e) => updateForm('region_scope_summary', e.target.value)} className="input" placeholder="如：浙江优先，长三角可接受" />
            </Field>
            <Field label="最低净利润">
              <input type="text" value={form.min_net_profit_yuan} onChange={(e) => updateForm('min_net_profit_yuan', e.target.value)} className="input" placeholder="例如：2000万、1亿" />
            </Field>
            <Field label="PE 上限">
              <input type="text" value={form.max_pe} onChange={(e) => updateForm('max_pe', e.target.value)} className="input" placeholder="例如：13" />
            </Field>
            <Field label="市值范围">
              <input type="text" value={form.market_cap_range} onChange={(e) => updateForm('market_cap_range', e.target.value)} className="input" placeholder="例如：5亿-30亿、5亿以上、30亿以内" />
            </Field>
            <Field label="上市状态偏好">
              <select value={form.preferred_listed_status} onChange={(e) => updateForm('preferred_listed_status', e.target.value)} className="input">
                <option value="">未明确</option>
                <option value="listed">已上市</option>
                <option value="preparing_listing">准备上市</option>
                <option value="unlisted">未上市</option>
                <option value="any">均可</option>
              </select>
            </Field>
            <Field label="并表要求">
              <select value={form.requires_consolidation} onChange={(e) => updateForm('requires_consolidation', e.target.value)} className="input">
                <option value="">未明确</option>
                <option value="yes">需要并表</option>
                <option value="no">不需要并表</option>
              </select>
            </Field>
            <Field label="溢价上限 (%)">
              <input type="text" value={form.max_premium_rate} onChange={(e) => updateForm('max_premium_rate', e.target.value)} className="input" placeholder="例如：20" />
            </Field>
            <Field label="负债率上限 (%)">
              <input type="text" value={form.max_debt_ratio} onChange={(e) => updateForm('max_debt_ratio', e.target.value)} className="input" placeholder="例如：65" />
            </Field>
          </div>

          <Field label="买家需求原文 / 补充材料">
            <textarea
              value={form.raw_requirement_text}
              onChange={(e) => updateForm('raw_requirement_text', e.target.value)}
              className="input min-h-[130px] resize-y leading-relaxed"
              placeholder="可粘贴买家的聊天记录、需求邮件、投资偏好说明等大段文本，系统会解析补全上面的结构化字段。"
            />
          </Field>

          <Field label="其他要求 / 排除项">
            <textarea
              value={form.negative_summary}
              onChange={(e) => updateForm('negative_summary', e.target.value)}
              className="input min-h-[60px] resize-y"
              placeholder="例如：不接受重大诉讼、冻结、执行或违规违法风险"
            />
          </Field>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">附件/截图</label>
            <div
              className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-600 transition-colors hover:border-brand-300 hover:bg-brand-50/40"
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleFileDrop}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2 text-gray-800 font-medium">
                  <Upload className="w-4 h-4 text-brand-600" />
                  拖拽文件到这里，或上传图片、PDF、Office、文本附件
                </div>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="shrink-0 bg-white border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-brand-300 hover:text-brand-700"
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
                ? '创建后会自动进入解析队列，解析结果可在意向详情查看。'
                : '仅创建基础意向，不触发解析。'}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setStep('buyer_link')} className="px-3 py-2 text-sm border border-gray-200 text-gray-700">返回</button>
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
              <button type="submit" disabled={saving || !form.intent_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-2">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {saving ? '创建中...' : selectedFiles.length > 0 || form.raw_requirement_text.trim() ? '创建并解析' : '创建意向'}
              </button>
            </div>
          </div>
        </form>
      )}
    </Modal>
  );
}

function parseMoneyToYuan(value: string): number | undefined {
  const text = value.trim();
  if (!text) return undefined;
  const normalized = text.replace(/[,，\s]/g, '').replace(/人民币|CNY|RMB/gi, '');
  const match = normalized.match(/^(\d+(?:\.\d+)?)(亿元|亿|万元|万|元)?$/);
  if (!match) return undefined;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return undefined;
  const unit = match[2] || '元';
  if (unit === '亿元' || unit === '亿') return amount * 100000000;
  if (unit === '万元' || unit === '万') return amount * 10000;
  return amount;
}

function parseNumberInput(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const num = Number(trimmed.replace(/[,，%\s]/g, ''));
  return Number.isFinite(num) ? num : undefined;
}

function parseMarketCapRange(value: string): { min?: number; max?: number } {
  const raw = value.trim();
  if (!raw) return {};
  const normalized = raw.replace(/\s/g, '');
  const rangeMatch = normalized.match(/^(.+?)(?:[-~—]|至|到)(.+)$/);
  if (rangeMatch) {
    return { min: parseMoneyToYuan(rangeMatch[1]), max: parseMoneyToYuan(rangeMatch[2]) };
  }
  if (/(以上|起|\+)$/.test(normalized) || /^(>=?|大于|超过)/.test(normalized)) {
    return { min: parseMoneyToYuan(normalized.replace(/以上|起|\+|>=?|大于|超过/g, '')) };
  }
  if (/(以内|以下)$/.test(normalized) || /^(<=?|不超过|小于)/.test(normalized)) {
    return { max: parseMoneyToYuan(normalized.replace(/以内|以下|<=?|不超过|小于/g, '')) };
  }
  const single = parseMoneyToYuan(normalized);
  return single !== undefined ? { min: single } : {};
}

function normalizeOptional(value: string | undefined): string | undefined {
  const trimmed = (value || '').trim();
  return trimmed || undefined;
}

function buildIntentRawText(form: IntentForm, payload: BuyerIntentCreate, party: BuyerParty | null): string {
  const lines = [
    '【新建买家意向初始输入】',
    `意向名称：${payload.intent_name}`,
    party ? `关联买家：${party.buyer_name}` : null,
    form.industry_primary.trim() ? `行业：${form.industry_primary.trim()}` : null,
    form.region_scope_summary.trim() ? `地区范围：${form.region_scope_summary.trim()}` : null,
    form.min_net_profit_yuan.trim() ? `最低净利润：${form.min_net_profit_yuan.trim()}` : null,
    form.max_pe.trim() ? `PE上限：${form.max_pe.trim()}` : null,
    form.market_cap_range.trim() ? `市值范围：${form.market_cap_range.trim()}` : null,
    form.preferred_listed_status ? `上市状态偏好：${form.preferred_listed_status}` : null,
    form.requires_consolidation ? `并表要求：${form.requires_consolidation}` : null,
    form.max_premium_rate.trim() ? `溢价上限：${form.max_premium_rate.trim()}%` : null,
    form.max_debt_ratio.trim() ? `负债率上限：${form.max_debt_ratio.trim()}%` : null,
    form.negative_summary.trim() ? `其他要求/排除项：${form.negative_summary.trim()}` : null,
    '',
    '解析要求：请从下方需求原文和附件中提取买家的行业、地区、利润/市值/PE/溢价/负债率要求、上市偏好、并表控股要求、交易方式、风险容忍度等；如与上述初始输入冲突，以材料为准。行业和地区请输出中文，不要臆造材料中没有的信息。',
  ].filter((line): line is string => line !== null);

  if (form.raw_requirement_text.trim()) {
    lines.push('', '【需求原文/补充材料】', form.raw_requirement_text.trim());
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
          <input type="text" value={form.buyer_name} onChange={(e) => setForm({ ...form, buyer_name: e.target.value })} className="input" placeholder="例如：浙江某国资平台" autoFocus />
        </Field>
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
        <Field label="画像摘要">
          <textarea value={form.profile_summary || ''} onChange={(e) => setForm({ ...form, profile_summary: e.target.value })} className="input min-h-[60px] resize-y" />
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
