import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Briefcase, Building2, Loader2, RefreshCw, ShieldCheck, UsersRound } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { users } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type { AppUserActivitySummary } from '../types/api';

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  consultant: '顾问',
  developer: '系统',
};

const STATUS_LABELS: Record<string, string> = {
  active: '在售中',
  sold: '已售出',
  off_market: '已停售',
  unknown: '未知',
};

export default function Dashboard() {
  const [items, setItems] = useState<AppUserActivitySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    users
      .activitySummary()
      .then(setItems)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (isAdmin()) load();
    else setLoading(false);
  }, [load]);

  const totals = useMemo(() => {
    return items.reduce(
      (acc, item) => {
        acc.sellerTargets += item.owned_seller_targets;
        acc.buyerParties += item.owned_buyer_parties;
        acc.buyerIntents += item.owned_buyer_intents;
        acc.weeklyNew +=
          item.weekly_new_seller_targets + item.weekly_new_buyer_parties + item.weekly_new_buyer_intents;
        acc.weeklyUpdates += item.weekly_business_updates + item.weekly_follow_ups + item.weekly_application_logs;
        return acc;
      },
      { sellerTargets: 0, buyerParties: 0, buyerIntents: 0, weeklyNew: 0, weeklyUpdates: 0 },
    );
  }, [items]);

  if (!isAdmin()) {
    return (
      <div className="mx-auto max-w-2xl py-16 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-gray-100">
          <ShieldCheck className="h-6 w-6 text-gray-400" />
        </div>
        <h1 className="mb-2 text-lg font-semibold text-gray-900">仅管理员可查看数据看板</h1>
        <p className="text-sm text-gray-500">普通账号当前只展示自己负责的数据，团队汇总由管理员统一查看。</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">数据看板</h1>
          <p className="mt-1 text-sm text-gray-500">按账号查看录入、负责对象和本周跟进情况。</p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-60"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </button>
      </div>

      {error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Metric icon={UsersRound} label="团队账号" value={items.length} />
        <Metric icon={Building2} label="负责标的" value={totals.sellerTargets} />
        <Metric icon={Briefcase} label="买家/意向" value={totals.buyerParties + totals.buyerIntents} />
        <Metric icon={BarChart3} label="本周新增对象" value={totals.weeklyNew} />
        <Metric icon={Activity} label="本周业务动作" value={totals.weeklyUpdates} />
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        {loading ? (
          <div className="flex items-center gap-2 p-6 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中...
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-3">账号</th>
                <th className="px-4 py-3">负责对象</th>
                <th className="px-4 py-3">标的状态</th>
                <th className="px-4 py-3">本周新增</th>
                <th className="px-4 py-3">本周动作</th>
                <th className="px-4 py-3">最近活跃</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item) => (
                <tr key={item.user.id} className={item.user.status === 'disabled' ? 'bg-gray-50 text-gray-400' : ''}>
                  <td className="px-4 py-3">
                    <div className="min-w-40">
                      <div className="font-medium text-gray-900">{item.user.name}</div>
                      <div className="mt-0.5 text-xs text-gray-400">
                        {item.user.username || '-'} · {ROLE_LABELS[item.user.role] || item.user.role}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="grid min-w-44 grid-cols-3 gap-2 text-xs">
                      <CountPill label="标的" value={item.owned_seller_targets} />
                      <CountPill label="买家" value={item.owned_buyer_parties} />
                      <CountPill label="意向" value={item.owned_buyer_intents} />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex min-w-48 flex-wrap gap-1.5">
                      {statusEntries(item.seller_target_status_counts).map(([key, value]) => (
                        <span key={key} className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600">
                          {STATUS_LABELS[key] || key} {value}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="min-w-36 text-xs text-gray-600">
                      <div>标的 {item.weekly_new_seller_targets}</div>
                      <div>买家 {item.weekly_new_buyer_parties}</div>
                      <div>意向 {item.weekly_new_buyer_intents}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="min-w-40 text-xs text-gray-600">
                      <div>业务更新 {item.weekly_business_updates}</div>
                      <div>跟进记录 {item.weekly_follow_ups}</div>
                      <div>字段应用 {item.weekly_application_logs}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{formatDateTime(item.latest_activity_at)}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">
                    暂无账号统计。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs text-gray-500">{label}</div>
          <div className="mt-1 text-2xl font-semibold text-gray-900">{value}</div>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-50 text-gray-500">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

function CountPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-gray-50 px-2 py-1">
      <div className="text-gray-400">{label}</div>
      <div className="font-medium text-gray-900">{value}</div>
    </div>
  );
}

function statusEntries(value: Record<string, number>): Array<[string, number]> {
  const entries = Object.entries(value || {}).filter(([, count]) => count > 0);
  return entries.length ? entries : [['unknown', 0]];
}

function formatDateTime(value: string | null): string {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16);
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
