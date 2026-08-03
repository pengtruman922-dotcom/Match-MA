import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2, Sparkles, Trash2 } from 'lucide-react';
import { buyerIntents, users } from '../../lib/api';
import { isAdmin } from '../../lib/auth';
import type {
  AppUserOption,
  BuyerIntent,
  BuyerIntentFilterOptions,
  BuyerIntentSuggestion,
  BusinessUpdateProcessingScope,
} from '../../types/api';
import { formatMonthDayTime } from '../../lib/format';
import BulkActionBar from '../../components/BulkActionBar';
import PaginationFooter from '../../components/PaginationFooter';
import ListToolbar from './ListToolbar';
import CreateIntentModal from './CreateIntentModal';
import BusinessUpdateDrawer from '../../components/BusinessUpdateDrawer';
import { useTableViewportHeight } from '../../hooks/useTableViewportHeight';
import UpdateEntryMenu from '../../components/UpdateEntryMenu';
import {
  EMPTY_INTENT_FILTER_OPTIONS,
  INTENT_FILTERS,
  INTENT_PARSE_STATUS_POLL_INTERVAL_MS,
  INTENT_SEARCH_FIELD_LABELS,
  PAGE_SIZE_OPTIONS,
  readIntentFilters,
  setOrDelete,
  storeIntentPageSize,
  type BuyerIntentFilters,
} from './filters';
import ScenarioBadge from './ScenarioBadge';
import {
  IntentStatusBadge,
  ParseStatusBadge,
  RequirementCell,
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
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const admin = isAdmin();
  const [ownerOptions, setOwnerOptions] = useState<AppUserOption[]>([]);
  const [assignOwnerId, setAssignOwnerId] = useState('');
  const [assigning, setAssigning] = useState(false);
  const [updateDrawer, setUpdateDrawer] = useState<{ item: BuyerIntent; scope: BusinessUpdateProcessingScope } | null>(null);

  const pageCount = Math.max(1, Math.ceil(total / filters.pageSize));
  const visibleIds = useMemo(() => items.map((item) => item.id), [items]);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const selectedCount = selectedIds.size;
  // 批量操作条的出现/消失会把表格整体上下推，需要重算表格区高度。
  const hasSelection = selectedCount > 0;
  const activeFilterCount = INTENT_FILTERS.filter((key) => Boolean(filters[key])).length;
  const { ref: tableWrapRef, maxHeight: tableMaxHeight } = useTableViewportHeight([hasSelection, loading]);

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
    if (patch.pageSize !== undefined) {
      next.set('pageSize', String(patch.pageSize));
      storeIntentPageSize(patch.pageSize);
    }
    if (patch.page !== undefined) {
      if (patch.page <= 1) next.delete('page');
      else next.set('page', String(patch.page));
    }
    setSearchParams(next, { replace: options?.replace });
  }, [searchParams, setSearchParams]);

  const fetchData = useCallback((silent = false) => {
    if (!silent) setLoading(true);
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
        limit: filters.pageSize,
        offset: (filters.page - 1) * filters.pageSize,
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
      .finally(() => { if (!silent) setLoading(false); });
  }, [filters, updateFilters]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);
  useEffect(() => { buyerIntents.filterOptions().then(setFilterOptions).catch(() => {}); }, []);
  useEffect(() => { setSearchQuery(filters.q); }, [filters.q]);
  useEffect(() => {
    if (!admin) return;
    users.options().then(setOwnerOptions).catch(() => {});
  }, [admin]);

  useEffect(() => {
    if (!items.some((item) => item.processing_state?.overall_status === 'processing')) return;
    const timer = window.setInterval(() => fetchData(true), INTENT_PARSE_STATUS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [fetchData, items]);

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

  const handleDelete = async (item: BuyerIntent) => {
    if (!window.confirm(`确认删除需求「${item.intent_name}」？删除后不会出现在列表和推荐候选里。`)) return;
    setDeletingId(item.id);
    try {
      await buyerIntents.delete(item.id);
      await buyerIntents.filterOptions().then(setFilterOptions).catch(() => {});
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
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

      {/* 与标的列表同一套范式：表格区限高自滚 + 表头吸顶，高度由共用 hook 动态计算。 */}
      <div
        ref={tableWrapRef}
        style={{ maxHeight: tableMaxHeight }}
        className="min-h-[320px] overflow-auto border border-gray-200 bg-white"
      >
        {/*
          colgroup 合计 1368px == min-w，因此发生横向滚动时（容器 < 1368）列宽恰为声明值，
          冻结列的 sticky 偏移量精确；容器更宽时列会等比放大，但那时没有横滚，sticky 不激活。
        */}
        <table className="w-full min-w-[1368px] table-fixed text-sm">
          <colgroup>
            <col className="w-12" />
            <col className="w-48" />
            <col className="w-28" />
            <col className="w-96" />
            <col className="w-28" />
            <col className="w-24" />
            <col className="w-24" />
            <col className="w-[88px]" />
            <col className="w-60" />
          </colgroup>
          {/*
            z 层级四层，缺一层横滚时表头冻结列会被表体冻结列盖住：
            普通 td auto < 冻结 td z-20 < 吸顶 th z-30 < 冻结+吸顶 th z-40。
            border-collapse: collapse 下 sticky 元素的 border 不跟随粘滞，
            表头下边框改用 inset shadow 画。
          */}
          <thead className="sticky top-0 z-30">
            <tr className="bg-gray-50 shadow-[inset_0_-1px_0_rgb(243,244,246)]">
              <th className="sticky left-0 top-0 z-40 bg-gray-50 px-4 py-3 text-left"><input type="checkbox" disabled={visibleIds.length === 0} checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="选择当前页买家意向" className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></th>
              <th className="sticky left-12 top-0 z-40 bg-gray-50 px-4 py-3 text-left font-medium text-gray-600">需求名称</th>
              <th className="sticky left-[240px] top-0 z-40 bg-gray-50 px-4 py-3 text-left font-medium text-gray-600">买家名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">关键需求</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">解析状态</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">推荐状态</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">负责人</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">更新时间</th>
              <th className="sticky right-0 top-0 z-40 bg-gray-50 px-2 py-3 text-center font-medium text-gray-600">操作</th>
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
                selected={selectedIds.has(item.id)}
                onSelectedChange={(checked) => toggleSelected(item.id, checked)}
                onRecord={(scope) => setUpdateDrawer({ item, scope })}
                onDelete={() => handleDelete(item)}
                deleting={deletingId === item.id}
              />
            ))}
          </tbody>
        </table>
      </div>

      <PaginationFooter
        page={filters.page}
        pageCount={pageCount}
        pageSize={filters.pageSize}
        loading={loading}
        onPageChange={(page) => updateFilters({ page })}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        onPageSizeChange={(pageSize) => updateFilters({ pageSize, page: 1 })}
      />

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
  selected,
  onSelectedChange,
  onRecord,
  onDelete,
  deleting,
}: {
  item: BuyerIntent;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onRecord: (scope: BusinessUpdateProcessingScope) => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const frozen = 'bg-white group-hover:bg-brand-50';
  return (
    <tr className="group h-[88px] transition-colors hover:bg-brand-50/30">
      <td className={`sticky left-0 z-20 px-4 py-3 align-middle ${frozen}`}><input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择${item.intent_name}`} className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></td>
      <td className={`sticky left-12 z-20 px-4 py-3 align-middle ${frozen}`}>
        <Link to={`/buyer-intents/${item.id}`} className="line-clamp-2 font-medium leading-5 text-gray-900 transition-colors hover:text-brand-600" title={item.intent_name}>{item.intent_name}</Link>
        <ScenarioBadge intentId={item.id} labels={item.scenario_labels || []} />
      </td>
      <td className={`sticky left-[240px] z-20 px-4 py-3 align-middle text-gray-700 ${frozen}`}><p className="line-clamp-2 leading-5" title={item.buyer_name || '未关联买家'}>{item.buyer_name || <span className="text-amber-600">未关联买家</span>}</p></td>
      <td className="px-4 py-3 align-middle text-gray-600"><RequirementCell item={item} /></td>
      <td className="px-4 py-3 text-center align-middle"><ParseStatusBadge item={item} /></td>
      <td className="px-4 py-3 text-center align-middle"><IntentStatusBadge status={item.status} /></td>
      <td className="px-4 py-3 align-middle text-gray-600"><p className="line-clamp-2" title={item.owner_name || '未指派'}>{item.owner_name || <span className="text-gray-300">未指派</span>}</p></td>
      <td className="whitespace-nowrap px-4 py-3 align-middle text-gray-500">{formatMonthDayTime(item.updated_at)}</td>
      <td className={`sticky right-0 z-20 px-2 py-3 align-middle ${frozen}`}>
        <div className="flex items-center justify-center gap-1 whitespace-nowrap">
          <UpdateEntryMenu compact onSelect={onRecord} />
          <Link to={`/recommendations?mode=buyer-to-target&intentId=${item.id}`} className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 transition-colors hover:bg-brand-50"><Sparkles className="h-3 w-3" />推荐标的</Link>
          {isAdmin() && (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
            >
              {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              删除
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
