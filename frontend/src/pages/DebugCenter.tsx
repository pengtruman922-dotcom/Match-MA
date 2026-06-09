import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  Clock,
  FileText,
  RefreshCw,
  Server,
  Sparkles,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { debugApi } from '../lib/api';
import type {
  DebugCenterBusinessUpdate,
  DebugCenterData,
  DebugCenterJob,
  DebugCenterRecommendationSession,
  DebugCenterTrace,
} from '../types/api';

type DebugTab =
  | 'failed_jobs'
  | 'running_jobs'
  | 'failed_traces'
  | 'recent_traces'
  | 'business_updates'
  | 'recommendations'
  | 'model_tests';

const TABS: Array<{ key: DebugTab; label: string }> = [
  { key: 'failed_jobs', label: '失败任务' },
  { key: 'running_jobs', label: '运行队列' },
  { key: 'failed_traces', label: '失败 Trace' },
  { key: 'recent_traces', label: '最近 Trace' },
  { key: 'business_updates', label: '业务更新' },
  { key: 'recommendations', label: '推荐会话' },
  { key: 'model_tests', label: '模型测试' },
];

export default function DebugCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = normalizeTab(searchParams.get('tab'));
  const [data, setData] = useState<DebugCenterData | null>(null);
  const [activeTab, setActiveTab] = useState<DebugTab>(initialTab);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    debugApi
      .center({ limit: 30 })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Debug Center 加载失败'))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    setActiveTab(normalizeTab(searchParams.get('tab')));
  }, [searchParams]);

  function changeTab(nextTab: DebugTab) {
    setActiveTab(nextTab);
    setSearchParams({ tab: nextTab });
  }

  const overviewCards = useMemo(() => {
    if (!data) return [];
    return [
      {
        label: '系统状态',
        value: healthLabel(data.overview.health_level),
        icon: data.overview.health_level === 'ok' ? CheckCircle2 : AlertTriangle,
        tone: data.overview.health_level === 'ok' ? 'success' : data.overview.health_level === 'warning' ? 'warning' : 'danger',
      },
      { label: '失败任务', value: data.overview.failed_job_count, icon: Bug, tone: data.overview.failed_job_count ? 'danger' : 'normal' },
      { label: '活跃任务', value: data.overview.active_job_count, icon: Server, tone: data.overview.active_job_count ? 'warning' : 'normal' },
      { label: '失败 Trace', value: data.overview.failed_trace_count, icon: AlertTriangle, tone: data.overview.failed_trace_count ? 'danger' : 'normal' },
      { label: '失败业务更新', value: data.overview.failed_business_update_count, icon: FileText, tone: data.overview.failed_business_update_count ? 'danger' : 'normal' },
      { label: '模型测试失败', value: data.overview.failed_model_node_test_count, icon: Sparkles, tone: data.overview.failed_model_node_test_count ? 'danger' : 'normal' },
    ];
  }, [data]);

  if (loading && !data) {
    return <LoadingState />;
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Bug className="w-5 h-5 text-amber-600" />
            <h1 className="text-lg font-semibold text-gray-900">Debug Center</h1>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            面向管理员的任务、Trace、业务更新和模型测试排障入口。普通业务页面默认不展示这些底层细节。
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 text-gray-700 bg-white hover:border-amber-300 hover:text-amber-700"
          disabled={loading}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      {error && <div className="border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-3">
            {overviewCards.map((card) => (
              <MetricCard
                key={card.label}
                label={card.label}
                value={card.value}
                icon={card.icon}
                tone={card.tone as MetricTone}
              />
            ))}
          </div>

          <div className="bg-white border border-gray-200 p-4">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-sm font-semibold text-gray-900">快捷入口</h2>
              <span className="text-xs text-gray-400">生成时间：{formatDateTime(data.overview.generated_at)}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {data.quick_actions.map((action) => (
                <Link
                  key={action.key}
                  to={frontendRoute(action.route)}
                  className="inline-flex items-center gap-2 px-3 py-1.5 text-sm border border-gray-200 text-gray-700 hover:border-brand-300 hover:text-brand-700 hover:bg-brand-50"
                >
                  {action.label}
                  {typeof action.badge_count === 'number' && action.badge_count > 0 && (
                    <span className="text-[11px] bg-red-50 text-red-600 px-1.5 py-0.5">{action.badge_count}</span>
                  )}
                </Link>
              ))}
            </div>
          </div>

          <section className="bg-white border border-gray-200">
            <div className="px-4 border-b border-gray-100 overflow-x-auto">
              <div className="flex items-center gap-1 min-w-max">
                {TABS.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => changeTab(tab.key)}
                    className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === tab.key
                        ? 'border-amber-600 text-amber-700'
                        : 'border-transparent text-gray-500 hover:text-gray-800'
                    }`}
                  >
                    {tab.label}
                    <span className="ml-1.5 text-xs text-gray-400">{tabCount(data, tab.key)}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="p-4">
              {activeTab === 'failed_jobs' && (
                <JobList jobs={data.failed_jobs} emptyLabel="暂无未忽略的失败任务" />
              )}
              {activeTab === 'running_jobs' && (
                <JobList jobs={data.running_jobs} emptyLabel="暂无排队、运行或等待重试的任务" />
              )}
              {activeTab === 'failed_traces' && (
                <TraceList traces={data.failed_traces} emptyLabel="暂无失败 Trace" />
              )}
              {activeTab === 'recent_traces' && (
                <TraceList traces={data.recent_traces} emptyLabel="暂无最近 Trace" />
              )}
              {activeTab === 'business_updates' && (
                <BusinessUpdateList items={data.recent_business_updates} />
              )}
              {activeTab === 'recommendations' && (
                <RecommendationList items={data.recent_recommendation_sessions} />
              )}
              {activeTab === 'model_tests' && (
                <JobList jobs={data.model_node_test_failures} emptyLabel="暂无失败的模型测试任务" showModelNode />
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function JobList({
  jobs,
  emptyLabel,
  showModelNode = false,
}: {
  jobs: DebugCenterJob[];
  emptyLabel: string;
  showModelNode?: boolean;
}) {
  if (jobs.length === 0) return <EmptyState label={emptyLabel} />;
  return (
    <div className="divide-y divide-gray-100">
      {jobs.map((job) => (
        <div key={job.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={job.status || 'unknown'} />
                <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600">{job.queue_name || 'default'}</span>
                {job.error_code && <span className="text-xs px-1.5 py-0.5 bg-red-50 text-red-700">{job.error_code}</span>}
              </div>
              <p className="text-sm font-medium text-gray-900 mt-2">{job.job_type || job.title}</p>
              {showModelNode && (
                <p className="text-xs text-gray-500 mt-1">
                  {job.node_name || '未绑定模型节点'} · {job.provider_name || '-'} / {job.model_name || '-'}
                </p>
              )}
              {job.error_message && <p className="text-xs text-red-700 mt-1 line-clamp-2">{job.error_message}</p>}
              <p className="text-[11px] text-gray-400 font-mono mt-2">
                {job.id} · 更新 {formatDateTime(job.updated_at)}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {job.related_entity_ref && (
                <Link to={job.related_entity_ref.route} className="text-xs text-gray-500 hover:text-brand-700">
                  关联实体
                </Link>
              )}
              <Link to={job.debug_ref.route} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                查看详情
              </Link>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TraceList({ traces, emptyLabel }: { traces: DebugCenterTrace[]; emptyLabel: string }) {
  if (traces.length === 0) return <EmptyState label={emptyLabel} />;
  return (
    <div className="divide-y divide-gray-100">
      {traces.map((trace) => (
        <div key={trace.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={trace.status || 'unknown'} />
                <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600">{trace.trace_type || 'trace'}</span>
                {trace.error_code && <span className="text-xs px-1.5 py-0.5 bg-red-50 text-red-700">{trace.error_code}</span>}
              </div>
              <p className="text-sm font-medium text-gray-900 mt-2">{trace.node_name || trace.title}</p>
              <p className="text-xs text-gray-500 mt-1">
                {trace.provider_name || '-'} / {trace.model_name || '-'} · {trace.latency_ms ?? '-'}ms · Token {trace.total_tokens ?? '-'}
              </p>
              {trace.error_message && <p className="text-xs text-red-700 mt-1 line-clamp-2">{trace.error_message}</p>}
              {trace.raw_output_preview && <p className="text-xs text-gray-500 mt-1 line-clamp-2">{trace.raw_output_preview}</p>}
              <p className="text-[11px] text-gray-400 font-mono mt-2">
                {trace.id} · 开始 {formatDateTime(trace.started_at)}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {trace.related_entity_ref && (
                <Link to={trace.related_entity_ref.route} className="text-xs text-gray-500 hover:text-brand-700">
                  关联实体
                </Link>
              )}
              {trace.debug_ref ? (
                <Link to={trace.debug_ref.route} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                  查看任务
                </Link>
              ) : (
                <span className="text-xs text-gray-300">无任务</span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function BusinessUpdateList({ items }: { items: DebugCenterBusinessUpdate[] }) {
  if (items.length === 0) return <EmptyState label="暂无业务更新" />;
  return (
    <div className="divide-y divide-gray-100">
      {items.map((item) => (
        <div key={item.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={item.processing_status || 'unknown'} />
                <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600">{item.input_type || 'text'}</span>
                {item.failed_job_count > 0 && <span className="text-xs px-1.5 py-0.5 bg-red-50 text-red-700">失败任务 {item.failed_job_count}</span>}
              </div>
              <p className="text-sm font-medium text-gray-900 mt-2 line-clamp-1">{item.title}</p>
              {item.raw_text_preview && <p className="text-xs text-gray-500 mt-1 line-clamp-2">{item.raw_text_preview}</p>}
              <p className="text-[11px] text-gray-400 mt-2">
                动作 {item.action_count} · 待复核 {item.pending_action_count} · 任务 {item.job_count} · Trace {item.trace_count} · {formatDateTime(item.created_at)}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Link to={item.review_route} className="text-xs text-gray-500 hover:text-brand-700">
                复核页
              </Link>
              <Link to={item.debug_ref.route} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                Debug
              </Link>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecommendationList({ items }: { items: DebugCenterRecommendationSession[] }) {
  if (items.length === 0) return <EmptyState label="暂无推荐会话" />;
  return (
    <div className="divide-y divide-gray-100">
      {items.map((item) => (
        <div key={item.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={item.status || 'unknown'} />
                <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600">{modeLabel(item.mode)}</span>
                {item.failed_job_count > 0 && <span className="text-xs px-1.5 py-0.5 bg-red-50 text-red-700">失败任务 {item.failed_job_count}</span>}
              </div>
              <p className="text-sm font-medium text-gray-900 mt-2 line-clamp-1">{item.title}</p>
              <p className="text-[11px] text-gray-400 mt-2">
                已选 {item.selected_count} · 报告 {item.report_count} · 任务 {item.job_count} · Trace {item.trace_count} · {formatDateTime(item.updated_at || item.created_at)}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Link to="/recommendations" className="text-xs text-gray-500 hover:text-brand-700">
                推荐页
              </Link>
              <Link to={item.debug_ref.route} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                Debug
              </Link>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

type MetricTone = 'normal' | 'success' | 'warning' | 'danger';

function MetricCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  tone: MetricTone;
}) {
  const toneClass: Record<MetricTone, string> = {
    normal: 'bg-white text-gray-900 border-gray-200',
    success: 'bg-emerald-50 text-emerald-800 border-emerald-100',
    warning: 'bg-amber-50 text-amber-800 border-amber-100',
    danger: 'bg-red-50 text-red-800 border-red-100',
  };
  return (
    <div className={`border p-4 ${toneClass[tone]}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs opacity-70">{label}</span>
        <Icon className="w-4 h-4 opacity-70" />
      </div>
      <p className="text-xl font-semibold mt-2">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = statusTone(status);
  return <span className={`text-xs px-1.5 py-0.5 font-medium ${tone}`}>{statusLabel(status)}</span>;
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="py-12 text-center">
      <Clock className="w-8 h-8 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-400">{label}</p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-5 h-5 border-2 border-amber-600 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function normalizeTab(value: string | null): DebugTab {
  return TABS.some((tab) => tab.key === value) ? (value as DebugTab) : 'failed_jobs';
}

function tabCount(data: DebugCenterData, tab: DebugTab): number {
  const counts: Record<DebugTab, number> = {
    failed_jobs: data.failed_jobs.length,
    running_jobs: data.running_jobs.length,
    failed_traces: data.failed_traces.length,
    recent_traces: data.recent_traces.length,
    business_updates: data.recent_business_updates.length,
    recommendations: data.recent_recommendation_sessions.length,
    model_tests: data.model_node_test_failures.length,
  };
  return counts[tab];
}

function frontendRoute(route: string): string {
  if (route === '/workbench') return '/';
  return route;
}

function healthLabel(value: string): string {
  if (value === 'ok') return '正常';
  if (value === 'warning') return '关注';
  if (value === 'error') return '异常';
  return value;
}

function modeLabel(value: string | null): string {
  if (value === 'buyer_to_target') return '为买家找标的';
  if (value === 'target_to_buyer') return '为标的找买家';
  return value || '推荐';
}

function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    failed: '失败',
    queued: '排队',
    running: '运行中',
    retry_waiting: '等待重试',
    succeeded: '成功',
    parsed: '已解析',
    completed: '已完成',
    pending_review: '待复核',
  };
  return labels[value] || value;
}

function statusTone(value: string): string {
  if (value === 'failed') return 'bg-red-50 text-red-700';
  if (value === 'running' || value === 'queued' || value === 'retry_waiting') return 'bg-amber-50 text-amber-700';
  if (value === 'succeeded' || value === 'completed' || value === 'parsed') return 'bg-emerald-50 text-emerald-700';
  return 'bg-gray-100 text-gray-600';
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
