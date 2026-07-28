import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Plus, Search, Tag } from 'lucide-react';
import { research, sellerTargets, users } from '../lib/api';
import BatchResearchDialog from '../features/targets/BatchResearchDialog';
import { isAdmin } from '../lib/auth';
import type {
  AppUserOption,
  SellerTarget,
  SellerTargetFilterOptions,
  SellerTargetSuggestion,
} from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';
import BulkActionBar from '../components/BulkActionBar';
import FilterSelect from '../components/FilterSelect';
import PaginationFooter from '../components/PaginationFooter';
import SearchSuggestionList from '../components/SearchSuggestionList';
import { setOrDelete } from '../lib/utils';
import CreateTargetModal from '../features/targets/CreateTargetModal';
import TargetRow from '../features/targets/TargetRow';
import IndustryFilter from '../features/targets/IndustryFilter';
import RegionFilter from '../features/targets/RegionFilter';
import {
  activeTargetFilterCount,
  isParsingTarget,
  PAGE_SIZE,
  PARSE_POLL_INTERVAL_MS,
  readTargetFilters,
  SEARCH_FIELD_LABELS,
  SEARCH_FIELD_OPTIONS,
  type TargetFilters,
} from '../features/targets/filters';

export default function Targets() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readTargetFilters(searchParams), [searchParams]);
  const [items, setItems] = useState<SellerTarget[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState(filters.q);
  const [filterOptions, setFilterOptions] = useState<SellerTargetFilterOptions>({
    industries: [],
    regions: [],
    statuses: [],
  });
  const [suggestions, setSuggestions] = useState<SellerTargetSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [updateDrawer, setUpdateDrawer] = useState<{ open: boolean; targetId?: string; targetName?: string }>({ open: false });
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const admin = isAdmin();
  const [ownerOptions, setOwnerOptions] = useState<AppUserOption[]>([]);
  const [assignOwnerId, setAssignOwnerId] = useState('');
  const [assigning, setAssigning] = useState(false);
  const [batchResearching, setBatchResearching] = useState(false);
  const [researchDialogOpen, setResearchDialogOpen] = useState(false);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visibleIds = useMemo(() => items.map((item) => item.id), [items]);
  const selectedCount = selectedIds.size;
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const activeFilterCount = activeTargetFilterCount(filters);

  const updateFilters = useCallback((patch: Partial<TargetFilters>, options?: { replace?: boolean }) => {
    const next = new URLSearchParams(searchParams);
    if ('q' in patch) setOrDelete(next, 'q', patch.q);
    if ('searchField' in patch) setOrDelete(next, 'searchField', patch.searchField);
    if ('industryL1' in patch) setOrDelete(next, 'industryL1', patch.industryL1);
    if ('industryL2' in patch) setOrDelete(next, 'industryL2', patch.industryL2);
    if ('province' in patch) setOrDelete(next, 'province', patch.province);
    if ('city' in patch) setOrDelete(next, 'city', patch.city);
    if ('district' in patch) setOrDelete(next, 'district', patch.district);
    if ('status' in patch) setOrDelete(next, 'status', patch.status);
    if ('owner' in patch) setOrDelete(next, 'owner', patch.owner);
    if (patch.page !== undefined) {
      if (patch.page <= 1) next.delete('page');
      else next.set('page', String(patch.page));
    }
    setSearchParams(next, { replace: options?.replace });
  }, [searchParams, setSearchParams]);

  const fetchTargets = useCallback(() => {
    setLoading(true);
    sellerTargets
      .list({
        q: filters.q || undefined,
        search_field: filters.searchField,
        industry_l1: filters.industryL1 || undefined,
        industry_l2: filters.industryL2 || undefined,
        province: filters.province || undefined,
        city: filters.city || undefined,
        district: filters.district || undefined,
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

  useEffect(() => {
    fetchTargets();
  }, [fetchTargets]);

  useEffect(() => {
    if (!admin) return;
    users.options().then(setOwnerOptions).catch(() => {});
  }, [admin]);

  // Poll rows still parsing so recommendation/summary flips show up without a
  // manual refresh. Completion signal is information_status leaving parsing.
  useEffect(() => {
    const activeIds = items.filter(isParsingTarget).map((item) => item.id);
    if (activeIds.length === 0) return;
    const timer = window.setInterval(() => {
      Promise.all(activeIds.map((id) => sellerTargets.get(id).catch(() => null))).then((rows) => {
        const updates = rows.filter((row): row is SellerTarget => row !== null);
        if (!updates.length) return;
        setItems((prev) => {
          let changed = false;
          const next = prev.map((item) => {
            const fresh = updates.find((row) => row.id === item.id);
            if (!fresh) return item;
            if (fresh.updated_at === item.updated_at && fresh.information_status === item.information_status) return item;
            changed = true;
            // The detail endpoint does not aggregate follow-ups; keep the list values.
            return {
              ...fresh,
              latest_follow_up_on: item.latest_follow_up_on,
              latest_follow_up_content: item.latest_follow_up_content,
            };
          });
          return changed ? next : prev;
        });
      });
    }, PARSE_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [items]);

  useEffect(() => {
    sellerTargets.filterOptions().then(setFilterOptions).catch(() => {});
  }, []);

  useEffect(() => {
    setSearchQuery(filters.q);
  }, [filters.q]);

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
      sellerTargets
        .suggestions({ q: query, limit: 5 })
        .then((nextSuggestions) => {
          if (!cancelled) setSuggestions(nextSuggestions);
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        })
        .finally(() => {
          if (!cancelled) setSuggestionsLoading(false);
        });
    }, 220);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchQuery, showSuggestions]);

  useEffect(() => {
    if (searchParams.get('action') === 'new') {
      setShowCreateModal(true);
      const next = new URLSearchParams(searchParams);
      next.delete('action');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleSearch = () => {
    const nextQuery = searchQuery.trim();
    updateFilters({ q: nextQuery, searchField: nextQuery === filters.q ? filters.searchField : undefined, page: 1 });
    setShowSuggestions(false);
  };

  const handleSuggestionSelect = (suggestion: SellerTargetSuggestion) => {
    const nextQuery = suggestion.match_type === 'summary' ? searchQuery.trim() : suggestion.match_text;
    setSearchQuery(nextQuery);
    setShowSuggestions(false);
    updateFilters({ q: nextQuery, searchField: suggestion.search_field, page: 1 });
  };

  const handleDelete = async (item: SellerTarget) => {
    if (!window.confirm(`确认删除标的「${item.target_name}」？删除后不会出现在列表和推荐候选里。`)) return;
    setDeletingId(item.id);
    try {
      await sellerTargets.delete(item.id);
      await sellerTargets.filterOptions().then(setFilterOptions).catch(() => {});
      fetchTargets();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认删除已选择的 ${ids.length} 个标的？删除后不会出现在列表和推荐候选里。`)) return;
    setBulkDeleting(true);
    try {
      await sellerTargets.bulkDelete(ids);
      await sellerTargets.filterOptions().then(setFilterOptions).catch(() => {});
      fetchTargets();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量删除失败');
    } finally {
      setBulkDeleting(false);
    }
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

  const handleBatchAssign = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || !assignOwnerId) return;
    const ownerName = ownerOptions.find((option) => option.id === assignOwnerId)?.name || '所选账号';
    if (!window.confirm(`将已选择的 ${ids.length} 个标的指派给「${ownerName}」？`)) return;
    setAssigning(true);
    try {
      await sellerTargets.batchAssignOwner(ids, assignOwnerId);
      await sellerTargets.filterOptions().then(setFilterOptions).catch(() => {});
      fetchTargets();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量指派失败');
    } finally {
      setAssigning(false);
    }
  };

  const openBatchResearch = () => {
    if (!selectedIds.size) {
      alert('请先勾选需要调研的标的。');
      return;
    }
    setResearchDialogOpen(true);
  };

  const submitBatchResearch = async (ids: string[]) => {
    setBatchResearching(true);
    try {
      const result = await research.startSellerTargets(ids);
      setResearchDialogOpen(false);
      alert(`已提交 ${result.queued_count} 个调研任务${result.reused_count ? `，复用 ${result.reused_count} 个进行中任务` : ''}。`);
      fetchTargets();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量调研启动失败');
    } finally {
      setBatchResearching(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">标的管理</h1>
          <p className="text-xs text-gray-400 mt-1">共 {total} 个标的{activeFilterCount > 0 ? `，已应用 ${activeFilterCount} 个条件` : ''}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建标的
          </button>
          <button
            type="button"
            disabled={batchResearching}
            onClick={openBatchResearch}
            className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors bg-white disabled:opacity-50"
          >
            {batchResearching ? '提交中…' : `批量调研${selectedCount ? `（${selectedCount}）` : ''}`}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex flex-1 min-w-[340px] max-w-lg items-stretch">
          {/* 字段选择器显性化：按业务摘要或行业检索原本只能通过建议列表触发。 */}
          <select
            value={filters.searchField || ''}
            onChange={(event) =>
              updateFilters({
                searchField: (event.target.value || undefined) as TargetFilters['searchField'],
                page: 1,
              })
            }
            className="shrink-0 border border-r-0 border-gray-200 bg-white px-2 py-2 text-sm text-gray-600 outline-none focus:border-brand-600"
          >
            {SEARCH_FIELD_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => {
                setSearchQuery(event.target.value);
                setShowSuggestions(true);
              }}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => window.setTimeout(() => setShowSuggestions(false), 120)}
              onKeyDown={(event) => event.key === 'Enter' && handleSearch()}
              placeholder="搜索标的名称、主体、行业或摘要..."
              className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 transition-colors bg-white"
            />
            <SearchSuggestionList
              open={showSuggestions && searchQuery.trim().length > 0}
              loading={suggestionsLoading}
              suggestions={suggestions}
              onSelect={handleSuggestionSelect}
              subtitle={(suggestion) =>
                suggestion.match_type === 'summary' ? suggestion.target_name : suggestion.snippet || suggestion.target_subject_name || '点击按该字段检索'
              }
            />
          </div>
        </div>
        <IndustryFilter
          value={{ l1: filters.industryL1, l2: filters.industryL2 }}
          options={filterOptions.industries}
          onChange={(next) => updateFilters({ industryL1: next.l1, industryL2: next.l2, page: 1 })}
        />
        <RegionFilter
          value={{ province: filters.province, city: filters.city, district: filters.district }}
          options={filterOptions.regions}
          onChange={(next) =>
            updateFilters({
              province: next.province,
              city: next.city,
              district: next.district,
              page: 1,
            })
          }
        />
        <FilterSelect
          label="状态"
          value={filters.status}
          options={filterOptions.statuses || []}
          onChange={(value) => updateFilters({ status: value, page: 1 })}
        />
        {admin && (
          <FilterSelect
            label="负责人"
            value={filters.owner}
            options={filterOptions.owners || []}
            onChange={(value) => updateFilters({ owner: value, page: 1 })}
          />
        )}
        <button onClick={handleSearch} className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-600 hover:text-brand-600 transition-colors bg-white">
          搜索
        </button>
        {activeFilterCount > 0 && (
          <button
            onClick={() => {
              setSearchQuery('');
              updateFilters({
                q: '',
                searchField: undefined,
                industryL1: '',
                industryL2: '',
                province: '',
                city: '',
                district: '',
                status: '',
                owner: '',
                page: 1,
              });
            }}
            className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
          >
            清空条件
          </button>
        )}
      </div>

      {filters.q && filters.searchField && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="inline-flex items-center gap-1 bg-brand-50 text-brand-700 px-2 py-1">
            <Tag className="w-3 h-3" />
            按{SEARCH_FIELD_LABELS[filters.searchField]}检索：{filters.q}
          </span>
        </div>
      )}

      {selectedCount > 0 && (
        <BulkActionBar
          count={selectedCount}
          label="标的"
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

      <div>
        <div className="bg-white border border-gray-200 overflow-x-auto">
          <table className="w-max min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="sticky left-0 z-30 w-12 bg-gray-50 px-4 py-3 text-left">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleSelectAllVisible}
                    aria-label="选择当前页标的"
                    className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600"
                  />
                </th>
                <th className="sticky left-12 z-20 w-[220px] bg-gray-50 text-left px-4 py-3 font-medium text-gray-600">标的名称</th>
                <th className="w-20 max-w-20 text-left px-3 py-3 font-medium text-gray-600">标的主体</th>
                <th className="w-[100px] text-center px-4 py-3 font-medium text-gray-600">状态</th>
                <th className="w-[100px] text-center px-4 py-3 font-medium text-gray-600">AI 处理</th>
                <th className="w-[92px] text-left px-4 py-3 font-medium text-gray-600">类型</th>
                <th className="w-[96px] text-left px-4 py-3 font-medium text-gray-600">上市状态</th>
                <th className="w-[150px] text-left px-4 py-3 font-medium text-gray-600">行业</th>
                <th className="w-[130px] text-left px-4 py-3 font-medium text-gray-600">地区</th>
                <th className="w-[130px] text-right px-4 py-3 font-medium text-gray-600">价格</th>
                <th className="w-[110px] text-left px-4 py-3 font-medium text-gray-600">价格时间</th>
                <th className="w-[120px] text-right px-4 py-3 font-medium text-gray-600">净利润</th>
                <th className="w-[110px] text-left px-4 py-3 font-medium text-gray-600">财务期间</th>
                <th className="w-[92px] text-right px-4 py-3 font-medium text-gray-600">负债率</th>
                <th className="w-[120px] text-left px-4 py-3 font-medium text-gray-600">出售比例</th>
                <th className="w-[76px] text-center px-4 py-3 font-medium text-gray-600">控股</th>
                <th className="w-[76px] text-center px-4 py-3 font-medium text-gray-600">并表</th>
                <th className="w-[200px] text-left px-4 py-3 font-medium text-gray-600">最近跟进</th>
                <th className="w-[100px] text-left px-4 py-3 font-medium text-gray-600">负责人</th>
                <th className="sticky right-0 z-20 w-[210px] bg-gray-50 text-left px-4 py-3 font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr>
                  <td colSpan={20} className="px-4 py-8 text-center">
                    <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" />
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={20} className="px-4 py-8 text-center text-gray-400">暂无匹配的标的数据</td>
                </tr>
              ) : (
                items.map((item) => (
                  <TargetRow
                    key={item.id}
                    item={item}
                    selected={selectedIds.has(item.id)}
                    onSelectedChange={(checked) => toggleSelected(item.id, checked)}
                    onOpenUpdateDrawer={() => setUpdateDrawer({ open: true, targetId: item.id, targetName: item.target_name })}
                    onDelete={() => handleDelete(item)}
                    deleting={deletingId === item.id}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
        <PaginationFooter page={filters.page} pageCount={pageCount} pageSize={PAGE_SIZE} loading={loading} onPageChange={(page) => updateFilters({ page })} />
      </div>

      {showCreateModal && (
        <CreateTargetModal
          onClose={() => setShowCreateModal(false)}
          onCreated={() => { setShowCreateModal(false); fetchTargets(); }}
        />
      )}

      <BusinessUpdateDrawer
        open={updateDrawer.open}
        onClose={() => setUpdateDrawer({ open: false })}
        defaultTargetId={updateDrawer.targetId}
        defaultTargetName={updateDrawer.targetName}
        onSuccess={fetchTargets}
      />

      {researchDialogOpen && (
        <BatchResearchDialog
          targets={items.filter((item) => selectedIds.has(item.id))}
          submitting={batchResearching}
          onCancel={() => setResearchDialogOpen(false)}
          onConfirm={(ids) => void submitBatchResearch(ids)}
        />
      )}
    </div>
  );
}
