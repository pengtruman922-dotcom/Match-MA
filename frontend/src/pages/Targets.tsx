import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent, FormEvent, ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  Building2,
  ChevronDown,
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
import { attachments, businessUpdates, sellerTargets, users } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type {
  AppUserOption,
  AttachmentUploadPolicy,
  SellerTarget,
  SellerTargetCreate,
  SellerTargetFilterOption,
  SellerTargetFilterOptions,
  SellerTargetSearchField,
  SellerTargetSuggestion,
} from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';
import {
  sellerTargetDisplayStatus,
  sellerTargetDisplayStatusClass,
  sellerTargetDisplayStatusLabel,
  sellerTargetStatusLabel,
} from '../lib/sellerTargetStatus';

const PAGE_SIZE = 20;
const PARSE_POLL_INTERVAL_MS = 4000;

function isParsingTarget(item: SellerTarget): boolean {
  return item.information_status === 'parsing' || item.information_status === 'researching';
}

const SEARCH_FIELD_LABELS: Record<SellerTargetSearchField | 'all', string> = {
  all: '全部字段',
  target_name: '标的',
  target_subject_name: '主体',
  business_summary: '摘要',
};

type TargetFilters = {
  q: string;
  searchField?: SellerTargetSearchField;
  industry: string;
  region: string;
  status: string;
  owner: string;
  page: number;
};

export default function Targets() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readTargetFilters(searchParams), [searchParams]);
  const [items, setItems] = useState<SellerTarget[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState(filters.q);
  const [filterOptions, setFilterOptions] = useState<SellerTargetFilterOptions>({ industries: [], regions: [], statuses: [] });
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

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visibleIds = useMemo(() => items.map((item) => item.id), [items]);
  const selectedCount = selectedIds.size;
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const activeFilterCount = [filters.q, filters.industry, filters.region, filters.status, filters.owner].filter(Boolean).length;

  const updateFilters = useCallback((patch: Partial<TargetFilters>, options?: { replace?: boolean }) => {
    const next = new URLSearchParams(searchParams);
    if ('q' in patch) setOrDelete(next, 'q', patch.q);
    if ('searchField' in patch) setOrDelete(next, 'searchField', patch.searchField);
    if ('industry' in patch) setOrDelete(next, 'industry', patch.industry);
    if ('region' in patch) setOrDelete(next, 'region', patch.region);
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
        industry: filters.industry || undefined,
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
          <button className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors bg-white">
            批量调研
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[280px] max-w-md">
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
            placeholder="搜索标的名称、主体或摘要..."
            className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 transition-colors bg-white"
          />
          <SearchSuggestionList
            open={showSuggestions && searchQuery.trim().length > 0}
            loading={suggestionsLoading}
            suggestions={suggestions}
            onSelect={handleSuggestionSelect}
          />
        </div>
        <FilterSelect
          label="行业"
          value={filters.industry}
          options={filterOptions.industries}
          onChange={(value) => updateFilters({ industry: value, page: 1 })}
        />
        <FilterSelect
          label="地区"
          value={filters.region}
          options={filterOptions.regions}
          onChange={(value) => updateFilters({ region: value, page: 1 })}
        />
        <FilterSelect
          label="状态"
          value={filters.status}
          options={filterOptions.statuses}
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
              updateFilters({ q: '', searchField: undefined, industry: '', region: '', status: '', owner: '', page: 1 });
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
        <div className="flex items-center justify-between gap-3 border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
          <span className="text-amber-800">已选择 {selectedCount} 个标的</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setSelectedIds(new Set())} className="px-3 py-1.5 text-xs text-amber-700 hover:text-amber-900">
              取消选择
            </button>
            {admin && (
              <>
                <select
                  value={assignOwnerId}
                  onChange={(event) => setAssignOwnerId(event.target.value)}
                  className="border border-amber-300 bg-white px-2 py-1.5 text-xs text-gray-700"
                >
                  <option value="">选择负责人...</option>
                  {ownerOptions
                    .filter((option) => option.status === 'active')
                    .map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.name}
                      </option>
                    ))}
                </select>
                <button
                  onClick={handleBatchAssign}
                  disabled={assigning || !assignOwnerId}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  {assigning && <Loader2 className="w-3 h-3 animate-spin" />}
                  批量指派
                </button>
                <button
                  onClick={handleBulkDelete}
                  disabled={bulkDeleting}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {bulkDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                  批量删除
                </button>
              </>
            )}
          </div>
        </div>
      )}

      <div className="bg-white border border-gray-200">
        <div className="overflow-x-auto">
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
                <th className="w-[110px] text-center px-4 py-3 font-medium text-gray-600">状态</th>
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
                  <td colSpan={19} className="px-4 py-8 text-center">
                    <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" />
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={19} className="px-4 py-8 text-center text-gray-400">暂无匹配的标的数据</td>
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
        <div className="flex items-center justify-between gap-3 border-t border-gray-100 px-4 py-3 text-sm text-gray-500">
          <span>
            第 {filters.page} / {pageCount} 页 · 每页 {PAGE_SIZE} 条
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => updateFilters({ page: Math.max(1, filters.page - 1) })}
              disabled={filters.page <= 1 || loading}
              className="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-700"
            >
              上一页
            </button>
            <button
              onClick={() => updateFilters({ page: Math.min(pageCount, filters.page + 1) })}
              disabled={filters.page >= pageCount || loading}
              className="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-700"
            >
              下一页
            </button>
          </div>
        </div>
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
    </div>
  );
}

function TargetRow({
  item,
  selected,
  onSelectedChange,
  onOpenUpdateDrawer,
  onDelete,
  deleting,
}: {
  item: SellerTarget;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onOpenUpdateDrawer: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const subject = getSubjectDisplay(item);
  const industry = [item.industry_primary, item.industry_secondary].filter(Boolean).join(' / ') || '-';
  const region = [item.headquarter_province, item.headquarter_city].filter(Boolean).join(' ') || '-';
  const price = getPreferredPrice(item);
  const priceDisplay = price ? `${formatYuan(price.value)}${price.kind === 'asking' ? '*' : ''}` : '-';
  const priceTitle = price
    ? `${price.kind === 'asking' ? '报价' : '估值'}：${formatYuan(price.value)}${price.kind === 'asking' ? '（明确报价）' : ''}`
    : '';
  const ratioText = formatTransferRatio(item);

  return (
    <tr className="group hover:bg-brand-50/30 transition-colors">
      <td className="sticky left-0 z-20 bg-white px-4 py-3 group-hover:bg-brand-50">
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelectedChange(event.target.checked)}
          aria-label={`选择${item.target_name}`}
          className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600"
        />
      </td>
      <td className="sticky left-12 z-10 bg-white px-4 py-3 group-hover:bg-brand-50">
        <ClampedLink to={`/targets/${item.id}`} value={item.target_name} className="font-medium text-gray-900 hover:text-brand-600 transition-colors" />
        {isParsingTarget(item) ? (
          <p className="mt-1 text-xs italic text-sky-500">摘要生成中...</p>
        ) : (
          item.business_summary && <ClampedText value={item.business_summary} className="mt-1 text-xs text-gray-400" />
        )}
      </td>
      <td className="w-20 max-w-20 px-3 py-3 text-gray-600"><ClampedText value={subject} /></td>
      <td className="px-4 py-3 text-center"><DisplayStatusBadge item={item} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={formatTargetType(item.target_type)} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={formatListedStatus(item.listed_status)} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={industry} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={region} /></td>
      <td className="px-4 py-3 text-right text-gray-700 font-mono" title={priceTitle}>{priceDisplay}</td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={price?.date || '-'} /></td>
      <td className="px-4 py-3 text-right text-gray-600 font-mono">
        {item.current_net_profit_yuan ? formatYuan(item.current_net_profit_yuan) : '-'}
      </td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={item.financial_period_label || '-'} /></td>
      <td className="px-4 py-3 text-right text-gray-600 font-mono">{formatPercent(item.current_debt_ratio)}</td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={ratioText} /></td>
      <td className="px-4 py-3 text-center"><YesNoBadge value={item.can_control} /></td>
      <td className="px-4 py-3 text-center"><YesNoBadge value={item.can_consolidate} /></td>
      <td className="px-4 py-3 text-gray-600">
        {item.latest_follow_up_on ? (
          <div>
            <p className="text-[11px] font-mono text-gray-400">{item.latest_follow_up_on}</p>
            <ClampedText value={item.latest_follow_up_content || ''} className="mt-0.5 text-xs" />
          </div>
        ) : (
          '-'
        )}
      </td>
      <td className="px-4 py-3 text-gray-600">
        {item.owner_name ? <ClampedText value={item.owner_name} /> : <span className="text-gray-300">未指派</span>}
      </td>
      <td className="sticky right-0 z-10 bg-white px-4 py-3 group-hover:bg-brand-50">
        <div className="flex items-center gap-1 whitespace-nowrap">
          <button
            onClick={onOpenUpdateDrawer}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-white transition-colors"
          >
            <MessageSquarePlus className="w-3 h-3" />
            更新
          </button>
          <Link
            to={`/recommendations?mode=target-to-buyer&targetId=${item.id}`}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-white transition-colors"
          >
            <Sparkles className="w-3 h-3" />
            推荐买家
          </Link>
          {isAdmin() && (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
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

function SearchSuggestionList({
  open,
  loading,
  suggestions,
  onSelect,
}: {
  open: boolean;
  loading: boolean;
  suggestions: SellerTargetSuggestion[];
  onSelect: (suggestion: SellerTargetSuggestion) => void;
}) {
  if (!open) return null;

  return (
    <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-40 border border-gray-200 bg-white shadow-lg">
      {loading ? (
        <div className="flex items-center gap-2 px-3 py-3 text-xs text-gray-400">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          正在查找匹配项...
        </div>
      ) : suggestions.length === 0 ? (
        <div className="px-3 py-3 text-xs text-gray-400">暂无匹配建议，回车可全文搜索</div>
      ) : (
        <div className="py-1">
          {suggestions.map((suggestion) => (
            <button
              key={`${suggestion.id}-${suggestion.search_field}`}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(suggestion);
              }}
              className="w-full px-3 py-2 text-left hover:bg-brand-50 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="max-w-[260px] truncate text-sm text-gray-900">{suggestion.match_text}</span>
                <span className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
                  <Tag className="h-2.5 w-2.5" />
                  {suggestion.match_label}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[11px] text-gray-400">
                {suggestion.match_type === 'summary' ? suggestion.target_name : suggestion.snippet || suggestion.target_subject_name || '点击按该字段检索'}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: SellerTargetFilterOption[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectedOption = options.find((option) => option.value === value);
  const displayText = selectedOption ? selectedOption.label : '全部';

  return (
    <div className="relative w-[180px]">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        className="flex w-full items-center justify-between gap-2 border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-600 outline-none transition-colors hover:border-brand-300 focus:border-brand-600"
        title={`${label} ${displayText}`}
      >
        <span className="truncate">{label} {displayText}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+4px)] z-40 max-h-64 w-[220px] overflow-y-auto border border-gray-200 bg-white py-1 shadow-lg">
          <button
            type="button"
            onMouseDown={(event) => {
              event.preventDefault();
              onChange('');
              setOpen(false);
            }}
            className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-brand-50 ${!value ? 'text-brand-700' : 'text-gray-700'}`}
          >
            <span className="truncate">{label} 全部</span>
          </button>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onChange(option.value);
                setOpen(false);
              }}
              className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-brand-50 ${value === option.value ? 'text-brand-700' : 'text-gray-700'}`}
              title={option.label}
            >
              <span className="truncate">{option.label}</span>
              <span className="shrink-0 text-xs text-gray-400">{option.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function readTargetFilters(searchParams: URLSearchParams): TargetFilters {
  const searchFieldParam = searchParams.get('searchField');
  const searchField = isSellerTargetSearchField(searchFieldParam) ? searchFieldParam : undefined;
  const page = Math.max(1, Number(searchParams.get('page') || '1') || 1);
  return {
    q: searchParams.get('q') || '',
    searchField,
    industry: searchParams.get('industry') || '',
    region: searchParams.get('region') || '',
    status: searchParams.get('status') || '',
    owner: searchParams.get('owner') || '',
    page,
  };
}

function isSellerTargetSearchField(value: string | null): value is SellerTargetSearchField {
  return value === 'target_name' || value === 'target_subject_name' || value === 'business_summary';
}

function setOrDelete(params: URLSearchParams, key: string, value: string | undefined) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function DisplayStatusBadge({ item }: { item: SellerTarget }) {
  const displayStatus = sellerTargetDisplayStatus(item);
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 font-medium ${sellerTargetDisplayStatusClass(displayStatus)}`}
      title={`信息状态：${sellerTargetStatusLabel(item.information_status, 'information')}`}
    >
      {displayStatus === 'parsing' && <Loader2 className="w-3 h-3 animate-spin" />}
      {sellerTargetDisplayStatusLabel(displayStatus)}
    </span>
  );
}

function YesNoBadge({ value }: { value: string | null }) {
  const normalized = value || 'unknown';
  const labelMap: Record<string, string> = {
    yes: '是',
    likely: '可能',
    no: '否',
    unknown: '未知',
  };
  const colorMap: Record<string, string> = {
    yes: 'bg-emerald-50 text-emerald-700',
    likely: 'bg-blue-50 text-blue-700',
    no: 'bg-gray-100 text-gray-600',
    unknown: 'bg-gray-100 text-gray-500',
  };
  return <span className={`text-xs px-2 py-0.5 font-medium ${colorMap[normalized] || colorMap.unknown}`}>{labelMap[normalized] || normalized}</span>;
}

function ClampedText({ value, className = '' }: { value: string; className?: string }) {
  return <span title={value === '-' ? undefined : value} className={`line-clamp-2 break-words ${className}`}>{value}</span>;
}

function ClampedLink({ to, value, className = '' }: { to: string; value: string; className?: string }) {
  return (
    <Link to={to} title={value} className={`line-clamp-2 break-words ${className}`}>
      {value}
    </Link>
  );
}

function formatYuan(val: string | number): string {
  const num = Number(val);
  if (!Number.isFinite(num)) return '-';
  const sign = num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${sign}${Math.round(abs / 10000)}万`;
  if (Number.isInteger(num)) return String(num);
  return String(Number(num.toFixed(2)));
}

function formatPercent(val: string | null): string {
  if (!val) return '-';
  const raw = Number(val);
  if (!Number.isFinite(raw)) return '-';
  const percentage = raw > 0 && raw <= 1 ? raw * 100 : raw;
  return `${Number(percentage.toFixed(1))}%`;
}

function formatTargetType(type: string | null): string {
  const map: Record<string, string> = {
    company: '公司',
    equity_package: '股权包',
    business_unit: '业务单元',
    asset_package: '资产包',
    project: '项目',
    other: '其他',
  };
  return type ? map[type] || type : '-';
}

function formatListedStatus(status: string | null): string {
  if (status === 'listed') return '已上市';
  if (status === 'unlisted' || status === 'pre_ipo') return '未上市';
  return '未知';
}

function getSubjectDisplay(item: SellerTarget): string {
  const subject = item.target_subject_name?.trim();
  return subject || '-';
}

function getPreferredPrice(item: SellerTarget): { kind: 'asking' | 'valuation'; value: string; date: string | null } | null {
  if (item.asking_price_yuan) return { kind: 'asking', value: item.asking_price_yuan, date: item.asking_price_date };
  if (item.valuation_yuan) return { kind: 'valuation', value: item.valuation_yuan, date: item.valuation_date };
  return null;
}

function formatTransferRatio(item: SellerTarget): string {
  if (item.transfer_ratio_text) return item.transfer_ratio_text;
  if (item.transfer_ratio_min && item.transfer_ratio_max) return `${formatRatio(item.transfer_ratio_min)}-${formatRatio(item.transfer_ratio_max)}`;
  if (item.transfer_ratio_min) return `>=${formatRatio(item.transfer_ratio_min)}`;
  if (item.transfer_ratio_max) return `<=${formatRatio(item.transfer_ratio_max)}`;
  return '-';
}

function formatRatio(value: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return `${Number(num.toFixed(1))}%`;
}

type CreateTargetForm = {
  targetName: string;
  targetType: string;
  targetSubjectName: string;
  industry: string;
  region: string;
  askingPrice: string;
  askingPriceDate: string;
  supplement: string;
};

const DEFAULT_CREATE_FORM: CreateTargetForm = {
  targetName: '',
  targetType: 'company',
  targetSubjectName: '',
  industry: '',
  region: '',
  askingPrice: '',
  askingPriceDate: '',
  supplement: '',
};

function CreateTargetModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [form, setForm] = useState<CreateTargetForm>(DEFAULT_CREATE_FORM);
  const [saving, setSaving] = useState(false);
  const [duplicates, setDuplicates] = useState<SellerTarget[]>([]);
  const [nameWarning, setNameWarning] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPolicyLoading(true);
    attachments
      .uploadPolicy()
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
  }, []);

  useEffect(() => {
    const name = form.targetName.trim();
    if (name.length < 2) {
      setDuplicates([]);
      setNameWarning(name.length === 1 ? '名称过短，建议补充公司全称或地区' : '');
      return;
    }

    const timer = window.setTimeout(() => {
      setNameWarning('');
      sellerTargets
        .list({ q: name, limit: 5 })
        .then((response) => setDuplicates(response.items.filter((item) => item.target_name !== name)))
        .catch(() => {});
    }, 300);

    return () => window.clearTimeout(timer);
  }, [form.targetName]);

  function updateForm<K extends keyof CreateTargetForm>(key: K, value: CreateTargetForm[K]) {
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
        errors.push(`单次业务更新最多上传 ${maxFiles} 个附件。`);
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetName = form.targetName.trim();
    if (!targetName) return;

    const askingPriceYuan = parseMoneyToYuan(form.askingPrice);
    if (form.askingPrice.trim() && askingPriceYuan === undefined) {
      setSubmitError('报价格式暂无法识别，请使用 5000万、1.2亿 或完整数字。');
      return;
    }

    setSaving(true);
    setSubmitError(null);
    try {
      const region = parseRegion(form.region);
      const shouldParse = selectedFiles.length > 0 || form.supplement.trim().length > 0;
      const payload: SellerTargetCreate = {
        target_name: targetName,
        target_type: form.targetType,
        target_subject_name: normalizeOptional(form.targetSubjectName),
        recommendation_status: 'not_recommendable',
        information_status: shouldParse ? 'parsing' : 'pending_review',
        industry_primary: normalizeOptional(form.industry),
        headquarter_province: region.province,
        headquarter_city: region.city,
        asking_price_yuan: askingPriceYuan,
        asking_price_date: normalizeOptional(form.askingPriceDate),
      };

      const created = await sellerTargets.create(payload);
      if (shouldParse) {
        const rawText = buildCreateTargetRawText(form, payload);
        if (selectedFiles.length > 0) {
          const formData = new FormData();
          formData.set('raw_text', rawText);
          formData.set('input_type', 'mixed');
          formData.set('auto_process', 'true');
          formData.set('process_after_ocr', 'true');
          formData.set('include_attachment_text', 'true');
          formData.set('bound_seller_target_ids', JSON.stringify([created.id]));
          formData.set(
            'metadata_json',
            JSON.stringify({
              source: 'frontend_target_create_modal',
              create_payload: payload,
              bound_seller_target_ids: [created.id],
            })
          );
          selectedFiles.forEach((file) => formData.append('files', file));
          await businessUpdates.upload(formData);
        } else {
          const update = await businessUpdates.create({
            raw_text: rawText,
            input_type: 'text',
            bound_seller_target_ids: [created.id],
            metadata_json: {
              source: 'frontend_target_create_modal',
              create_payload: payload,
            },
          });
          await businessUpdates.process(update.id);
        }
      }
      onCreated();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="新建标的" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
          <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
          <p className="leading-relaxed">
            可以先填简要信息，再粘贴大段材料或上传附件。若正式文件识别到更完整的标的名称、主体名称或行业分类，解析结果会优先采用正式材料。
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="标的名称" required>
            <input
              type="text"
              value={form.targetName}
              onChange={(event) => updateForm('targetName', event.target.value)}
              className="input"
              placeholder="例如：拼哒出行项目"
              autoFocus
            />
            {nameWarning && <p className="text-xs text-amber-600 mt-1">{nameWarning}</p>}
          </Field>
          <Field label="类型">
            <select value={form.targetType} onChange={(event) => updateForm('targetType', event.target.value)} className="input">
              <option value="company">公司</option>
              <option value="project">项目</option>
              <option value="asset_package">资产包</option>
              <option value="business_unit">业务单元</option>
              <option value="equity_package">股权包</option>
              <option value="other">其他</option>
            </select>
          </Field>
          <Field label="标的主体">
            <input
              type="text"
              value={form.targetSubjectName}
              onChange={(event) => updateForm('targetSubjectName', event.target.value)}
              className="input"
              placeholder="可留空；解析后如与标的相同会直接显示同名主体"
            />
          </Field>
          <Field label="行业">
            <input
              type="text"
              value={form.industry}
              onChange={(event) => updateForm('industry', event.target.value)}
              className="input"
              placeholder="可选，留空由系统解析"
            />
          </Field>
          <Field label="地区">
            <input
              type="text"
              value={form.region}
              onChange={(event) => updateForm('region', event.target.value)}
              className="input"
              placeholder="例如：浙江 杭州；可留空"
            />
          </Field>
          <Field label="报价">
            <input
              type="text"
              value={form.askingPrice}
              onChange={(event) => updateForm('askingPrice', event.target.value)}
              className="input"
              placeholder="例如：10亿、5000万"
            />
          </Field>
          <Field label="报价时间">
            <input
              type="text"
              value={form.askingPriceDate}
              onChange={(event) => updateForm('askingPriceDate', event.target.value)}
              className="input"
              placeholder="例如：2025年一季度、2026-06"
            />
          </Field>
        </div>

        <Field label="补充内容">
          <textarea
            value={form.supplement}
            onChange={(event) => updateForm('supplement', event.target.value)}
            className="input min-h-[150px] resize-y leading-relaxed"
            placeholder="可粘贴聊天记录、项目介绍、财务摘要或其他大段文本。"
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

        {duplicates.length > 0 && (
          <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-800">疑似重复</p>
            {duplicates.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-3 text-xs">
                <span className="text-gray-700 line-clamp-2">
                  {item.target_name} · {item.headquarter_province || '未知'} · {item.industry_primary || '未知'}
                </span>
                <Link to={`/targets/${item.id}`} className="text-brand-600 hover:text-brand-700 font-medium shrink-0" onClick={onClose}>
                  更新它
                </Link>
              </div>
            ))}
          </div>
        )}

        {submitError && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>}

        <div className="flex items-center justify-between gap-3 pt-2">
          <p className="text-xs text-gray-400">
            {selectedFiles.length > 0 || form.supplement.trim()
              ? '创建后会自动进入解析队列，解析结果可在更新记录复核。'
              : '仅创建基础标的，不触发解析。'}
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700 hover:border-gray-300 transition-colors">
              取消
            </button>
            <button type="submit" disabled={saving || !form.targetName.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-50 inline-flex items-center gap-2">
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {saving ? '创建中...' : duplicates.length > 0 ? '仍然新建' : selectedFiles.length > 0 || form.supplement.trim() ? '创建并解析' : '创建'}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
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

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white border border-gray-200 shadow-lg w-full max-w-3xl mx-4 max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white z-10">
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label} {required && <span className="text-brand-600">*</span>}
      </label>
      {children}
    </div>
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

function parseRegion(value: string): { province?: string; city?: string } {
  const text = value.trim();
  if (!text) return {};
  const parts = text.split(/[\s,，/／-]+/).filter(Boolean);
  if (parts.length >= 2) return { province: parts[0], city: parts.slice(1).join(' ') };
  return { province: text };
}

function normalizeOptional(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed || undefined;
}

function buildCreateTargetRawText(form: CreateTargetForm, payload: SellerTargetCreate): string {
  const lines = [
    '【新建标的初始输入】',
    `标的名称：${payload.target_name}`,
    `类型：${formatTargetType(payload.target_type || 'company')}`,
    form.targetSubjectName.trim() ? `标的主体：${form.targetSubjectName.trim()}` : null,
    form.industry.trim() ? `行业：${form.industry.trim()}` : null,
    form.region.trim() ? `地区：${form.region.trim()}` : null,
    form.askingPrice.trim() ? `报价：${form.askingPrice.trim()}` : null,
    form.askingPriceDate.trim() ? `报价时间：${form.askingPriceDate.trim()}` : null,
    '',
    '解析要求：如果附件或正式文件识别到更完整的标的名称、主体名称、一级/二级行业、行业标签或地区，请以正式材料为准，可以覆盖上述初始输入；行业和地区字段请输出中文。不要臆造材料中没有的信息。业务摘要（business_summary）请用一两句话概括标的主营业务与核心亮点，不要照抄或粘贴原文。',
  ].filter((line): line is string => line !== null);

  if (form.supplement.trim()) {
    lines.push('', '【补充内容】', form.supplement.trim());
  }

  return lines.join('\n');
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}
