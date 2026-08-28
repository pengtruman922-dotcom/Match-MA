import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, Loader2, Sparkles, Trash2 } from 'lucide-react';
import { buyerIntents, users } from '../../lib/api';
import { canManageOwnedEntity, isAdmin } from '../../lib/auth';
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
import ColumnManager from './ColumnManager';
import {
  readColumnPrefs,
  resolveColumns,
  writeColumnPrefs,
  type IntentColumnDef,
  type IntentColumnPrefs,
} from './intentColumns';
import {
  BuyerEnumCell,
  BuyerTagsCell,
  BuyerWorthCell,
  IntentIndustriesCell,
  IntentStatusBadge,
  ListingWantedCell,
  MoneyCell,
  ReadinessCell,
  RegionWantedCell,
  RevenueWantedCell,
  TextCell,
  WorthWantedCell,
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
  // 列偏好每人自己一份，存浏览器。19 列谁都不会全都要看，而「看哪几列」因事而异。
  const [columnPrefs, setColumnPrefs] = useState<IntentColumnPrefs>(() => readColumnPrefs());
  const columns = useMemo(() => resolveColumns(columnPrefs), [columnPrefs]);
  // min-w 必须跟着可见列走：写死的话隐藏几列后表格仍撑那么宽，右边空一大条；
  // 而它同时决定 sticky 偏移准不准（容器窄于 min-w 时列宽才等于声明值）。
  const tableMinWidth = useMemo(
    () => 48 + 208 + 176 + columns.reduce((sum, column) => sum + columnWidthPx(column.width), 0),
    [columns],
  );
  const applyColumnPrefs = useCallback((next: IntentColumnPrefs) => {
    setColumnPrefs(next);
    writeColumnPrefs(next);
  }, []);

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
    if ('buyerBusinessTag' in patch) setOrDelete(next, 'buyerTag', patch.buyerBusinessTag);
    if ('buyerListedStatus' in patch) setOrDelete(next, 'buyerListed', patch.buyerListedStatus);
    if ('buyerProvince' in patch) setOrDelete(next, 'buyerProvince', patch.buyerProvince);
    // desc 是默认，不写进 URL —— 免得每个链接都拖着一个 sortDir=desc。
    if ('sortDir' in patch) setOrDelete(next, 'sortDir', patch.sortDir === 'asc' ? 'asc' : '');
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
        buyer_business_tag: filters.buyerBusinessTag || undefined,
        buyer_listed_status: filters.buyerListedStatus || undefined,
        buyer_province: filters.buyerProvince || undefined,
        sort_dir: filters.sortDir,
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
          // 前三个问「它是谁」，后三个问「它要买什么」—— 标签刻意区分，
          // 否则「行业」「上市」「区域」在同一行里各有两个，用户分不清点哪个。
          { label: '级别', value: filters.status, options: filterOptions.statuses, onChange: (value) => updateFilters({ status: value, page: 1 }) },
          { label: '买家行业', value: filters.buyerBusinessTag, options: filterOptions.buyer_business_tags || [], onChange: (value) => updateFilters({ buyerBusinessTag: value, page: 1 }) },
          { label: '买家上市', value: filters.buyerListedStatus, options: filterOptions.buyer_listed_statuses || [], onChange: (value) => updateFilters({ buyerListedStatus: value, page: 1 }) },
          { label: '买家区域', value: filters.buyerProvince, options: filterOptions.buyer_provinces || [], onChange: (value) => updateFilters({ buyerProvince: value, page: 1 }) },
          { label: '关注行业', value: filters.industry, options: filterOptions.industries, onChange: (value) => updateFilters({ industry: value, page: 1 }) },
          { label: '关注区域', value: filters.region, options: filterOptions.regions, onChange: (value) => updateFilters({ region: value, page: 1 }) },
          { label: '上市要求', value: filters.listedStatus, options: filterOptions.listed_statuses, onChange: (value) => updateFilters({ listedStatus: value, page: 1 }) },
          ...(admin ? [{ label: '负责人', value: filters.owner, options: filterOptions.owners || [], onChange: (value: string) => updateFilters({ owner: value, page: 1 }) }] : []),
        ]}
        activeFilterCount={activeFilterCount}
        onClear={clearFilters}
        total={total}
        totalLabel="条并购需求"
        trailing={<ColumnManager prefs={columnPrefs} onChange={applyColumnPrefs} />}
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
          19 列合计 2088px == min-w，横滚时列宽恰为声明值，冻结列的 sticky 偏移才准
          （左侧 48+208=256px，右侧操作列 176px）。改列宽必须同步改 min-w 和这两个偏移。
        */}
        {/*
          列宽由列定义给出，min-w 按当前可见列动态算：冻结列 48+208=256px，
          右冻结操作列 176px，中间列按各自声明宽度累加。写死 min-w 的话
          隐藏几列之后表格仍然撑那么宽，右边会空出一大条。
        */}
        <table className="w-full table-fixed text-sm" style={{ minWidth: `${tableMinWidth}px` }}>
          <colgroup>
            <col className="w-12" />
            <col className="w-52" />
            {columns.map((column) => <col key={column.key} className={column.width} />)}
            <col className="w-44" />
          </colgroup>
          {/*
            z 层级四层，缺一层横滚时表头冻结列会被表体冻结列盖住：
            普通 td auto < 冻结 td z-20 < 吸顶 th z-30 < 冻结+吸顶 th z-40。
            border-collapse: collapse 下 sticky 元素的 border 不跟随粘滞，
            表头下边框改用 inset shadow 画。
          */}
          <thead className="sticky top-0 z-30">
            <tr className="bg-gray-50 shadow-[inset_0_-1px_0_rgb(243,244,246)]">
              <th className="sticky left-0 top-0 z-40 bg-gray-50 px-3 py-3 text-left"><input type="checkbox" disabled={visibleIds.length === 0} checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="选择当前页买家意向" className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></th>
              <th className="sticky left-12 top-0 z-40 bg-gray-50 px-3 py-3 text-left font-medium text-gray-600">买家名称</th>
              {columns.map((column) => (
                <th
                  key={column.key}
                  title={column.title}
                  className={`px-2 py-3 font-medium ${column.align === 'center' ? 'text-center' : 'text-left'} ${column.side === 'intent' ? 'text-brand-700' : 'text-gray-600'}`}
                >
                  {column.key === 'updatedAt' ? (
                    <button type="button" onClick={() => updateFilters({ sortDir: filters.sortDir === 'desc' ? 'asc' : 'desc', page: 1 })} className="inline-flex items-center gap-0.5 hover:text-brand-600" title={filters.sortDir === 'desc' ? '当前：最近更新在前，点击改为最早在前' : '当前：最早更新在前，点击改为最近在前'}>
                      {column.label}
                      {filters.sortDir === 'desc' ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />}
                    </button>
                  ) : column.label}
                </th>
              ))}
              <th className="sticky right-0 top-0 z-40 bg-gray-50 px-2 py-3 text-center font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={columns.length + 3} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={columns.length + 3} className="px-4 py-8 text-center text-gray-400">暂无匹配的买家</td></tr>
            ) : items.map((item) => (
              <IntentRow
                key={item.id}
                item={item}
                selected={selectedIds.has(item.id)}
                onSelectedChange={(checked) => toggleSelected(item.id, checked)}
                onRecord={(scope) => setUpdateDrawer({ item, scope })}
                onDelete={() => handleDelete(item)}
                deleting={deletingId === item.id}
                columns={columns}
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
  columns,
}: {
  item: BuyerIntent;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onRecord: (scope: BusinessUpdateProcessingScope) => void;
  onDelete: () => void;
  deleting: boolean;
  columns: IntentColumnDef[];
}) {
  const frozen = 'bg-white group-hover:bg-brand-50';
  const canDelete = canManageOwnedEntity(item.owner_user_id);
  return (
    <tr className="group h-[88px] transition-colors hover:bg-brand-50/30">
      <td className={`sticky left-0 z-20 px-4 py-3 align-middle ${frozen}`}><input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择${item.intent_name}`} className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></td>
      <td className={`sticky left-12 z-20 px-3 py-3 align-middle ${frozen}`}>
        {/* 只显示买家名称，不再拼需求名 —— 一个买家实质只挂一条需求。 */}
        <Link to={`/buyer-intents/${item.id}`} className="line-clamp-2 font-medium leading-5 text-gray-900 transition-colors hover:text-brand-600" title={item.buyer_name || '未关联买家'}>
          {item.buyer_name || <span className="text-amber-600">未关联买家</span>}
        </Link>
        <ScenarioBadge intentId={item.id} labels={item.scenario_labels || []} />
      </td>
      {columns.map((column) => (
        <td
          key={column.key}
          className={`px-2 py-3 align-middle ${column.align === 'center' ? 'text-center' : ''}`}
        >
          <IntentCell column={column} item={item} />
        </td>
      ))}
      <td className={`sticky right-0 z-20 px-2 py-3 align-middle ${frozen}`}>
        <div className="flex items-center justify-center gap-1 whitespace-nowrap">
          <UpdateEntryMenu compact onSelect={onRecord} />
          {/* 推荐页现在从一段需求文本起步，所以带上 intentId 让它预填该需求的原文。 */}
          <Link to={`/recommendations?intentId=${item.id}`} className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 transition-colors hover:bg-brand-50"><Sparkles className="h-3 w-3" />推荐标的</Link>
          {canDelete && (
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

/** 一列一个渲染分支。列定义只说「显示什么」，怎么显示在这里。 */
function IntentCell({ column, item }: { column: IntentColumnDef; item: BuyerIntent }) {
  switch (column.key) {
    case 'grade': return <IntentStatusBadge item={item} />;
    case 'readiness': return <ReadinessCell item={item} />;
    case 'ownership': return <BuyerEnumCell value={item.buyer_ownership_type} column="ownership_type" />;
    case 'province': return <TextCell value={item.buyer_location_province} />;
    case 'listedStatus': return <BuyerEnumCell value={item.buyer_listed_status} column="listed_status" />;
    case 'stockCode': return <TextCell value={item.buyer_stock_code} className="text-gray-600" />;
    case 'businessTags': return <BuyerTagsCell item={item} />;
    case 'worth': return <BuyerWorthCell item={item} />;
    case 'revenue': return <MoneyCell value={item.buyer_current_revenue_yuan} />;
    case 'wantIndustry': return <IntentIndustriesCell item={item} />;
    case 'wantListing': return <ListingWantedCell item={item} />;
    case 'wantWorth': return <WorthWantedCell item={item} />;
    case 'wantRevenue': return <RevenueWantedCell item={item} />;
    case 'wantRegion': return <RegionWantedCell item={item} />;
    case 'updatedAt': return <span className="whitespace-nowrap text-xs text-gray-500">{formatMonthDayTime(item.updated_at)}</span>;
    case 'owner': return <TextCell value={item.owner_name} className="text-gray-600" />;
    case 'contact': return <TextCell value={item.buyer_our_contact_name} className="text-gray-600" />;
    default: return null;
  }
}

/**
 * Tailwind 宽度类 → 像素。表格要按可见列算 min-w，而 Tailwind 的类名本身
 * 不带数值，运行时量不到，所以在这里换算一次。
 *
 * `w-N` 是 N × 4px（Tailwind 的 spacing scale），`w-[88px]` 是任意值。
 */
function columnWidthPx(width: string): number {
  const arbitrary = width.match(/^w-\[(\d+)px\]$/);
  if (arbitrary) return Number(arbitrary[1]);
  const scale = width.match(/^w-(\d+)$/);
  if (scale) return Number(scale[1]) * 4;
  // 认不出来的类名给个中庸值：宽度算错只是横滚多一点，不该让整张表塌掉。
  return 96;
}
