import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import CountBars from '../features/dashboard/CountBars';
import { BUYER_PROVINCE_TIERS } from '../features/dashboard/distribution';
import { stats } from '../lib/api';
import type { PlatformOverview } from '../types/api';

// 底图路径约 130 KB，只有这一页用得上；打成独立 chunk，别让其它页面陪着加载。
// 两张地图共用同一个模块，所以 chunk 只下载一次。
const ChinaChoropleth = lazy(() => import('../features/dashboard/ChinaChoropleth'));

/**
 * 数据看板：**存量画像**，用于内部大屏与一对一客户演示。
 *
 * 只出聚合数：页面上不出现任何标的与买家名称——演示场景下这些是敏感信息。
 * 取数走 `/stats/overview`，全库、不分交易状态、不按负责人过滤，因为这里回答的
 * 是「盘子长什么样」而不是「我手上有什么」。
 */
export default function Dashboard() {
  const [data, setData] = useState<PlatformOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await stats.overview());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '取数失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-gray-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-brand-600" />
        正在加载
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <p className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </p>
        <button type="button" onClick={() => void load()} className="mt-2 text-xs font-medium underline">
          重新加载
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { targets, buyers } = data;

  return (
    <div className="space-y-5">
      {/* 页面不写标题也不写口径说明：导航上已经写着「数据看板」，而口径属于
          文档不属于大屏。只留一个更新时间，用来判断屏上的数还新不新。 */}
      <div className="flex items-center justify-end gap-3 text-xs text-gray-400">
        <span>更新于 {formatDateTime(data.generated_at)}</span>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-gray-400 hover:text-brand-600 disabled:opacity-50"
          aria-label="刷新"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {targets.total === 0 && buyers.total === 0 ? (
        <div className="border border-gray-200 bg-white py-16 text-center text-sm text-gray-400">
          还没有标的和买家，录入后这里会出现分布
        </div>
      ) : (
        <>
          <Panel title="标的省级分布">
            <MapFallbackBoundary>
              <ChinaChoropleth
                provinces={targets.provinces}
                unknownCount={targets.province_unknown_count}
                ariaLabel="标的省级分布地图，含台湾省与南海诸岛"
              />
            </MapFallbackBoundary>
          </Panel>

          <Panel title="买家省级分布">
            <MapFallbackBoundary>
              <ChinaChoropleth
                provinces={buyers.provinces}
                unknownCount={buyers.province_unknown_count}
                tiers={BUYER_PROVINCE_TIERS}
                unit="家"
                unknownLabel="未填所在地"
                ariaLabel="买家省级分布地图，含台湾省与南海诸岛"
              />
            </MapFallbackBoundary>
          </Panel>

          {/* 两块条形图并排，用 items-stretch（grid 默认）让面板等高。 */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Panel title="标的行业分布 top">
              <CountBars
                items={targets.industries.map((item) => ({
                  label: item.l2,
                  count: item.count,
                }))}
                labelClassName="w-24"
                emptyText="还没有标的填了二级行业"
                footnote={industryFootnote(targets)}
              />
            </Panel>

            <Panel title="标的营收规模">
              <CountBars
                items={targets.revenue_buckets.map((bucket) => ({
                  label: bucket.label,
                  count: bucket.count,
                }))}
                labelClassName="w-24"
                footnote={
                  targets.revenue_unknown_count > 0
                    ? `共 ${targets.total} 个标的，其中 ${targets.revenue_unknown_count} 个未填营收`
                    : `共 ${targets.total} 个标的`
                }
              />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

function industryFootnote(targets: PlatformOverview['targets']): string {
  const parts = [`共 ${targets.total} 个标的`];
  if (targets.industry_other_count > 0) {
    parts.push(`榜外另有 ${targets.industry_other_count} 个二级行业`);
  }
  if (targets.industry_unknown_count > 0) {
    parts.push(`${targets.industry_unknown_count} 个未细分到二级`);
  }
  // 字典里 食品 / 食品制造 / 食品加工 尚未合并，同义词会各占一行——
  // 说出来比让人以为榜单是准的强。去重工单见 `数据看板拆除验收单0729.md` §1.3。
  parts.push('二级行业字典存在同义词未合并，同一赛道可能分散在多行');
  return parts.join('；');
}

function MapFallbackBoundary({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-24 text-sm text-gray-400">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          正在加载底图
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function Panel({
  title,
  className = '',
  children,
}: {
  title: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`border border-gray-200 bg-white p-5 ${className}`}>
      <h2 className="mb-4 text-sm font-medium text-gray-900">{title}</h2>
      {children}
    </section>
  );
}

// 直接喂原值：Postgres 的 `now()::text` 是 `2026-07-29 04:12:33.512+00`，
// 浏览器认这个形式，但把空格换成 T 之后反而会因为 `+00` 少了分钟位而解析失败。
function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? '-'
    : date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
}
