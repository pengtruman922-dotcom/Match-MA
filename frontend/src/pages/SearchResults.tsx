import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Building2, FileSearch, Search, Target, UserRound } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { globalSearch } from '../lib/api';
import type { GlobalSearchGroup, GlobalSearchResponse } from '../types/api';

export default function SearchResults() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialQuery = searchParams.get('q') || '';
  const [query, setQuery] = useState(initialQuery);
  const [result, setResult] = useState<GlobalSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setQuery(initialQuery);
    if (!initialQuery.trim()) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    globalSearch
      .query({ q: initialQuery.trim(), limit_per_type: 10 })
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '搜索失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialQuery]);

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    const next = query.trim();
    if (!next) return;
    navigate(`/search?q=${encodeURIComponent(next)}`);
  }

  return (
    <div className="space-y-5">
      <div className="bg-white border border-gray-200 p-5">
        <form onSubmit={submitSearch} className="flex items-center gap-3">
          <div className="relative flex-1 max-w-2xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="input pl-9"
              placeholder="搜索标的、买家或买家意向..."
              autoFocus
            />
          </div>
          <button type="submit" className="px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700">
            搜索
          </button>
        </form>
      </div>

      {!initialQuery.trim() ? (
        <EmptyState title="请输入搜索关键词" description="可模糊搜索标的、买家主体和买家意向。" />
      ) : loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : error ? (
        <div className="border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      ) : result && result.total_count > 0 ? (
        <div className="space-y-5">
          <div className="text-sm text-gray-500">
            搜索 <span className="text-gray-900 font-medium">{result.query}</span>，共找到 {result.total_count} 条结果
          </div>
          {result.groups.map((group) => (
            <ResultGroup key={group.key} group={group} />
          ))}
        </div>
      ) : (
        <EmptyState title="暂无搜索结果" description="可以尝试更换关键词，或先新建标的/买家意向。" />
      )}
    </div>
  );
}

function ResultGroup({ group }: { group: GlobalSearchGroup }) {
  if (group.count === 0) return null;
  const Icon = groupIcon(group.key);
  return (
    <section className="bg-white border border-gray-200">
      <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-brand-600" />
          <h2 className="text-sm font-semibold text-gray-900">{group.label}</h2>
          <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5">{group.count}</span>
        </div>
      </div>
      <div className="divide-y divide-gray-100">
        {group.items.map((item) => (
          <Link key={`${item.entity_type}-${item.entity_id}`} to={item.route} className="block px-5 py-4 hover:bg-gray-50 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-sm font-medium text-gray-900">{item.title}</p>
                  {item.match_reason && <span className="text-xs text-brand-700 bg-brand-50 px-1.5 py-0.5">{item.match_reason}</span>}
                </div>
                {item.subtitle && <p className="text-xs text-gray-500 mt-1 line-clamp-1">{item.subtitle}</p>}
                {item.snippet && <p className="text-sm text-gray-600 mt-2 line-clamp-2">{item.snippet}</p>}
              </div>
              <span className="text-xs text-gray-400 shrink-0">{formatDate(item.updated_at)}</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="bg-white border border-gray-200 py-16 text-center">
      <FileSearch className="w-9 h-9 text-gray-300 mx-auto mb-3" />
      <p className="text-sm font-medium text-gray-800">{title}</p>
      <p className="text-sm text-gray-400 mt-1">{description}</p>
    </div>
  );
}

function groupIcon(key: string): LucideIcon {
  if (key === 'seller_targets') return Target;
  if (key === 'buyer_parties') return Building2;
  if (key === 'buyer_intents') return UserRound;
  return FileSearch;
}

function formatDate(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}
