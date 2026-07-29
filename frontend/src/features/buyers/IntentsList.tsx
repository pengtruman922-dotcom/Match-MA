import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import { buyerIntents, users } from '../../lib/api';
import { isAdmin } from '../../lib/auth';
import type {
  AppUserOption,
  BuyerIntent,
  BuyerIntentFilterOptions,
  BuyerIntentParseStatus,
  BuyerIntentSuggestion,
  BusinessUpdateProcessingScope,
} from '../../types/api';
import { shortDate } from '../../lib/format';
import BulkActionBar from '../../components/BulkActionBar';
import PaginationFooter from '../../components/PaginationFooter';
import ListToolbar from './ListToolbar';
import CreateIntentModal from './CreateIntentModal';
import BusinessUpdateDrawer from '../../components/BusinessUpdateDrawer';
import UpdateEntryMenu from '../../components/UpdateEntryMenu';
import {
  EMPTY_INTENT_FILTER_OPTIONS,
  INTENT_FILTERS,
  INTENT_PARSE_STATUS_POLL_INTERVAL_MS,
  INTENT_SEARCH_FIELD_LABELS,
  PAGE_SIZE,
  readIntentFilters,
  setOrDelete,
  type BuyerIntentFilters,
} from './filters';
import {
  compactRequirementNotes,
  IntentStatusBadge,
  isActiveParseStatus,
  ParseStatusBadge,
} from './presentation';

export default function IntentsList({
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
  const [updateDrawer, setUpdateDrawer] = useState<{ item: BuyerIntent; scope: BusinessUpdateProcessingScope } | null>(null);

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
                onRecord={(scope) => setUpdateDrawer({ item, scope })}
              />
            ))}
          </tbody>
        </table>
      </div>

      <PaginationFooter page={filters.page} pageCount={pageCount} pageSize={PAGE_SIZE} loading={loading} onPageChange={(page) => updateFilters({ page })} />

      {externalShowCreate && <CreateIntentModal onClose={onExternalCreateClose} onCreated={() => { onExternalCreateClose(); onCreated(); fetchData(); }} />}
      {updateDrawer ? <BusinessUpdateDrawer
        open
        initialScope={updateDrawer.scope}
        defaultIntentId={updateDrawer.item.id}
        defaultIntentName={updateDrawer.item.intent_name}
        defaultBuyerPartyName={updateDrawer.item.buyer_name || undefined}
        onClose={() => setUpdateDrawer(null)}
        onSuccess={() => fetchData()}
      /> : null}
    </>
  );
}

function IntentRow({
  item,
  parseStatus,
  selected,
  onSelectedChange,
  onRecord,
}: {
  item: BuyerIntent;
  parseStatus?: BuyerIntentParseStatus;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onRecord: (scope: BusinessUpdateProcessingScope) => void;
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
      <td className="px-4 py-3 align-middle"><div className="flex items-center justify-center gap-1"><UpdateEntryMenu compact onSelect={onRecord} /><Link to={`/recommendations?mode=buyer-to-target&intentId=${item.id}`} className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 transition-colors hover:bg-brand-50"><Sparkles className="h-3 w-3" />推荐标的</Link></div></td>
    </tr>
  );
}
