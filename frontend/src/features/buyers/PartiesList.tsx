import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2, Trash2 } from 'lucide-react';
import { buyerParties, users } from '../../lib/api';
import { canManageOwnedEntity, isAdmin } from '../../lib/auth';
import type {
  AppUserOption,
  BuyerParty,
  BuyerPartyFilterOptions,
  BuyerPartySuggestion,
} from '../../types/api';
import BulkActionBar from '../../components/BulkActionBar';
import PaginationFooter from '../../components/PaginationFooter';
import ListToolbar from './ListToolbar';
import CreatePartyModal from './CreatePartyModal';
import {
  EMPTY_PARTY_FILTER_OPTIONS,
  PAGE_SIZE,
  PARTY_FILTERS,
  PARTY_SEARCH_FIELD_LABELS,
  readPartyFilters,
  setOrDelete,
  type BuyerPartyFilters,
} from './filters';
import { PartyStatusBadge, partyLocationText, partyMarketValue } from './presentation';
import { valueLabel } from '../../lib/fieldLabels';

export default function PartiesList({
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
  const [deletingId, setDeletingId] = useState<string | null>(null);
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
    if ('ownershipType' in patch) setOrDelete(next, 'partyOwnership', patch.ownershipType);
    if ('businessTag' in patch) setOrDelete(next, 'partyTag', patch.businessTag);
    if ('region' in patch) setOrDelete(next, 'partyRegion', patch.region);
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
        ownership_type: filters.ownershipType || undefined,
        business_tag: filters.businessTag || undefined,
        region: filters.region || undefined,
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
    const nextQuery = suggestion.match_text;
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

  const handleDelete = async (item: BuyerParty) => {
    if (!window.confirm(`确认删除买家主体「${item.buyer_name}」？删除后不会出现在列表和推荐候选里。`)) return;
    setDeletingId(item.id);
    try {
      await buyerParties.delete(item.id);
      await buyerParties.filterOptions().then(setFilterOptions).catch(() => {});
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
    updateFilters({ q: '', searchField: undefined, ownershipType: '', businessTag: '', region: '', status: '', owner: '', page: 1 });
  };

  return (
    <>
      <ListToolbar
        searchValue={searchQuery}
        placeholder="搜索买家名称、别名或联系人..."
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
          { label: '企业性质', value: filters.ownershipType, options: filterOptions.ownership_types, onChange: (value) => updateFilters({ ownershipType: value, page: 1 }) },
          { label: '业务标签', value: filters.businessTag, options: filterOptions.business_tags, onChange: (value) => updateFilters({ businessTag: value, page: 1 }) },
          { label: '地区', value: filters.region, options: filterOptions.regions, onChange: (value) => updateFilters({ region: value, page: 1 }) },
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
              <th className="text-left px-4 py-3 font-medium text-gray-600">主营业务</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">企业性质</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">市值/估值</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">地区</th>
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
            ) : items.map((item) => (
              <PartyRow
                key={item.id}
                item={item}
                selected={selectedIds.has(item.id)}
                onSelectedChange={(checked) => toggleSelected(item.id, checked)}
                onDelete={() => handleDelete(item)}
                deleting={deletingId === item.id}
              />
            ))}
          </tbody>
        </table>
      </div>

      <PaginationFooter page={filters.page} pageCount={pageCount} pageSize={PAGE_SIZE} loading={loading} onPageChange={(page) => updateFilters({ page })} />

      {externalShowCreate && <CreatePartyModal onClose={onExternalCreateClose} onCreated={() => { onExternalCreateClose(); onCreated(); fetchData(); }} />}
    </>
  );
}

function PartyRow({
  item,
  selected,
  onSelectedChange,
  onDelete,
  deleting,
}: {
  item: BuyerParty;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const region = partyLocationText(item) || '-';
  const tags = (item.business_tags_json || []).join('、') || '-';
  const ownership = item.ownership_type === 'unknown' ? '-' : valueLabel('ownership_type', item.ownership_type);
  // 市值/估值是一个展示位，带时间一起显示：没有时间的财务数字不可用。
  const marketValue = partyMarketValue(item);
  const canDelete = canManageOwnedEntity(item.owner_user_id);
  return (
    <tr className="hover:bg-brand-50/30 transition-colors">
      <td className="px-4 py-3"><input type="checkbox" checked={selected} onChange={(event) => onSelectedChange(event.target.checked)} aria-label={`选择${item.buyer_name}`} className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600" /></td>
      <td className="px-4 py-3"><Link to={`/buyers/${item.id}`} className="font-medium text-gray-900 hover:text-brand-600 transition-colors">{item.buyer_name}</Link></td>
      <td className="px-4 py-3 text-gray-600 max-w-[220px] truncate" title={tags === '-' ? undefined : tags}>{tags}</td>
      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{ownership}</td>
      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
        {marketValue
          ? <span title={marketValue.asOf ? `${marketValue.label} ${marketValue.value}（${marketValue.asOf}）` : undefined}>{marketValue.label} {marketValue.value}{marketValue.asOf ? <span className="ml-1 text-xs text-gray-400">{marketValue.asOf}</span> : null}</span>
          : '-'}
      </td>
      <td className="px-4 py-3 text-gray-600 max-w-[160px] truncate" title={region === '-' ? undefined : region}>{region}</td>
      <td className="px-4 py-3 text-center"><PartyStatusBadge status={item.status} /></td>
      <td className="px-4 py-3 text-gray-600">{item.owner_name || <span className="text-gray-300">未指派</span>}</td>
      <td className="px-4 py-3 text-center">
        <div className="inline-flex items-center gap-1">
          <Link to={`/buyers/${item.id}`} className="px-2 py-1 text-xs text-brand-600 hover:text-brand-700 font-medium">查看</Link>
          {canDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
              删除
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
