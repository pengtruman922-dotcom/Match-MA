import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Eye,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from 'lucide-react';
import { backgroundJobs, users } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type { AppUserOption, TaskCenterData, TaskCenterJob } from '../types/api';

const PAGE_SIZE = 50;
const DEFAULT_LOOKBACK_HOURS = 720;

const LOOKBACK_OPTIONS = [
  { value: 24, label: '近24小时' },
  { value: 168, label: '近7天' },
  { value: 720, label: '近30天' },
  { value: 2160, label: '近90天' },
] as const;

const STATUS_TABS = [
  { key: 'needs_attention', label: '待处理失败' },
  { key: 'active', label: '运行/排队' },
  { key: 'ignored', label: '已忽略' },
  { key: 'all', label: '全部任务' },
] as const;

export default function TaskCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<TaskCenterData | null>(null);
  const [userOptions, setUserOptions] = useState<AppUserOption[]>([]);
  const [selectedJob, setSelectedJob] = useState<TaskCenterJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [queryDraft, setQueryDraft] = useState(searchParams.get('q') || '');

  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const load = useCallback(() => {
    if (!isAdmin()) return;
    setLoading(true);
    setError(null);
    Promise.all([
      backgroundJobs.taskCenter({
        status_group: filters.statusGroup,
        initiated_by_user_id: filters.initiatedByUserId || undefined,
        queue_name: filters.queueName || undefined,
        q: filters.q || undefined,
        lookback_hours: filters.lookbackHours,
        limit: PAGE_SIZE,
      }),
      users.options(),
    ])
      .then(([taskData, optionData]) => {
        setData(taskData);
        setUserOptions(optionData);
      })
      .catch((err) => setError(err instanceof Error ? err.message : '任务中心加载失败'))
      .finally(() => setLoading(false));
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setQueryDraft(filters.q);
  }, [filters.q]);

  if (!isAdmin()) {
    return <div className="p-8 text-sm text-gray-500">仅管理员可以访问任务中心。</div>;
  }

  function updateFilters(patch: Partial<TaskFilters>) {
    const next = new URLSearchParams(searchParams);
    if ('statusGroup' in patch) setOrDelete(next, 'status', patch.statusGroup);
    if ('initiatedByUserId' in patch) setOrDelete(next, 'user', patch.initiatedByUserId);
    if ('queueName' in patch) setOrDelete(next, 'queue', patch.queueName);
    if ('q' in patch) setOrDelete(next, 'q', patch.q);
    if ('lookbackHours' in patch) {
      const value =
        patch.lookbackHours && patch.lookbackHours !== DEFAULT_LOOKBACK_HOURS ? String(patch.lookbackHours) : undefined;
      setOrDelete(next, 'hours', value);
    }
    setSearchParams(next, { replace: true });
  }

  async function retryJob(job: TaskCenterJob) {
    setBusyJobId(job.id);
    setError(null);
    try {
      const preview = await backgroundJobs.retryPreview(job.id);
      const blockers = preview.warnings.filter((item) => item.severity === 'blocker');
      if (blockers.length > 0) {
        setError(`无法重试：${blockers.map((item) => item.message).join('；')}`);
        return;
      }
      const warnings = preview.warnings.filter((item) => item.severity !== 'info');
      const warningText = warnings.length ? `\n\n需要注意：\n${warnings.map((item) => `- ${item.message}`).join('\n')}` : '';
      const confirmed = window.confirm(
        `确认重试“${job.task_display_name}”？\n\n关联对象：${job.related_object_name}\n发起人：${job.initiated_by_name}${warningText}\n\n重试成功后可能会回填关联对象字段。`,
      );
      if (!confirmed) return;
      await backgroundJobs.retry(job.id);
      setSelectedJob(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重试失败');
    } finally {
      setBusyJobId(null);
    }
  }

  async function ignoreJob(job: TaskCenterJob) {
    const reason = window.prompt('请输入忽略原因（可选）', job.ignore_reason || '');
    if (reason === null) return;
    setBusyJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.ignore(job.id, reason.trim() || undefined);
      setSelectedJob(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '忽略失败');
    } finally {
      setBusyJobId(null);
    }
  }

  async function unignoreJob(job: TaskCenterJob) {
    const confirmed = window.confirm(`确认恢复显示“${job.task_display_name}”？`);
    if (!confirmed) return;
    setBusyJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.unignore(job.id);
      setSelectedJob(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消忽略失败');
    } finally {
      setBusyJobId(null);
    }
  }

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    updateFilters({ q: queryDraft.trim() });
  }

  const totals = data?.totals;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">任务中心</h1>
          <p className="mt-1 text-sm text-gray-500">集中处理 AI、OCR、推荐、索引等后台任务异常，日常只处理重试和忽略。</p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:border-brand-300 hover:text-brand-700 disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="待处理失败" value={totals?.needs_attention_count || 0} tone={(totals?.needs_attention_count || 0) > 0 ? 'danger' : 'normal'} />
        <Metric label="运行/排队" value={totals?.active_count || 0} tone={(totals?.active_count || 0) > 0 ? 'warning' : 'normal'} />
        <Metric label="已忽略" value={totals?.ignored_count || 0} />
        <Metric label={`${lookbackLabel(filters.lookbackHours)}任务`} value={totals?.total_count || 0} />
      </div>

      <section className="border border-gray-200 bg-white">
        <div className="border-b border-gray-100 px-4">
          <div className="flex min-w-max items-center gap-1 overflow-x-auto">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => updateFilters({ statusGroup: tab.key })}
                className={`border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                  filters.statusGroup === tab.key
                    ? 'border-brand-600 text-brand-700'
                    : 'border-transparent text-gray-500 hover:text-gray-800'
                }`}
              >
                {tab.label}
                <span className="ml-1.5 text-xs text-gray-400">{tabCount(totals, tab.key)}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3 border-b border-gray-100 p-4 lg:flex-row lg:items-center">
          <select
            value={filters.initiatedByUserId}
            onChange={(event) => updateFilters({ initiatedByUserId: event.target.value })}
            className="border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-brand-500 focus:outline-none"
          >
            <option value="">全部发起人</option>
            {userOptions.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>

          <select
            value={filters.queueName}
            onChange={(event) => updateFilters({ queueName: event.target.value })}
            className="border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-brand-500 focus:outline-none"
          >
            <option value="">全部队列</option>
            <option value="llm">LLM</option>
            <option value="ocr">OCR</option>
            <option value="embedding">Embedding</option>
            <option value="rerank">Rerank</option>
            <option value="default">Default</option>
          </select>

          <select
            value={filters.lookbackHours}
            onChange={(event) => updateFilters({ lookbackHours: Number(event.target.value) })}
            className="border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-brand-500 focus:outline-none"
          >
            {LOOKBACK_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <form onSubmit={submitSearch} className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={queryDraft}
              onChange={(event) => setQueryDraft(event.target.value)}
              placeholder="搜索任务、对象、发起人或 Job ID"
              className="w-full border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm text-gray-700 placeholder:text-gray-400 focus:border-brand-500 focus:outline-none"
            />
          </form>
        </div>

        {error && <div className="mx-4 mt-4 border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium text-gray-500">
              <tr>
                <th className="w-40 px-4 py-3">时间</th>
                <th className="w-28 px-4 py-3">发起人</th>
                <th className="w-40 px-4 py-3">任务</th>
                <th className="min-w-64 px-4 py-3">关联对象</th>
                <th className="w-24 px-4 py-3">队列</th>
                <th className="w-24 px-4 py-3">状态</th>
                <th className="w-36 px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                    <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin text-brand-600" />
                    正在加载任务
                  </td>
                </tr>
              ) : (data?.tasks || []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                    <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-400" />
                    暂无任务
                  </td>
                </tr>
              ) : (
                data?.tasks.map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-500">{formatMinute(job.updated_at || job.created_at)}</td>
                    <td className="px-4 py-3 text-gray-700">
                      <span className="line-clamp-1" title={job.initiated_by_name}>{job.initiated_by_name}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900">{job.task_display_name}</div>
                      <div className="mt-0.5 text-xs text-gray-400">{job.job_type}</div>
                    </td>
                    <td className="px-4 py-3">
                      {job.related_object_route ? (
                        <Link to={job.related_object_route} className="line-clamp-2 text-gray-800 hover:text-brand-700" title={job.related_object_name}>
                          {job.related_object_name}
                        </Link>
                      ) : (
                        <span className="line-clamp-2 text-gray-800" title={job.related_object_name}>{job.related_object_name}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-600">{job.queue_name || 'default'}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge job={job} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setSelectedJob(job)}
                          className="inline-flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-brand-700"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          详情
                        </button>
                        {job.can_retry && (
                          <button
                            type="button"
                            onClick={() => retryJob(job)}
                            disabled={busyJobId === job.id}
                            className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-800 disabled:opacity-50"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            重试
                          </button>
                        )}
                        {job.ignored ? (
                          <button
                            type="button"
                            onClick={() => unignoreJob(job)}
                            disabled={busyJobId === job.id}
                            className="text-xs font-medium text-gray-500 hover:text-brand-700 disabled:opacity-50"
                          >
                            取消忽略
                          </button>
                        ) : job.status === 'failed' ? (
                          <button
                            type="button"
                            onClick={() => ignoreJob(job)}
                            disabled={busyJobId === job.id}
                            className="text-xs font-medium text-gray-500 hover:text-red-700 disabled:opacity-50"
                          >
                            忽略
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {selectedJob && (
        <TaskDetailDrawer
          job={selectedJob}
          busy={busyJobId === selectedJob.id}
          onClose={() => setSelectedJob(null)}
          onRetry={() => retryJob(selectedJob)}
          onIgnore={() => ignoreJob(selectedJob)}
          onUnignore={() => unignoreJob(selectedJob)}
        />
      )}
    </div>
  );
}

type TaskFilters = {
  statusGroup: string;
  initiatedByUserId: string;
  queueName: string;
  q: string;
  lookbackHours: number;
};

function readFilters(params: URLSearchParams): TaskFilters {
  const statusGroup = params.get('status') || 'needs_attention';
  const rawHours = Number(params.get('hours') || DEFAULT_LOOKBACK_HOURS);
  const lookbackHours = LOOKBACK_OPTIONS.some((option) => option.value === rawHours) ? rawHours : DEFAULT_LOOKBACK_HOURS;
  return {
    statusGroup: STATUS_TABS.some((item) => item.key === statusGroup) ? statusGroup : 'needs_attention',
    initiatedByUserId: params.get('user') || '',
    queueName: params.get('queue') || '',
    q: params.get('q') || '',
    lookbackHours,
  };
}

function setOrDelete(params: URLSearchParams, key: string, value: string | undefined) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function Metric({ label, value, tone = 'normal' }: { label: string; value: number; tone?: 'normal' | 'warning' | 'danger' }) {
  const toneClass = {
    normal: 'border-gray-200 bg-white text-gray-900',
    warning: 'border-amber-100 bg-amber-50 text-amber-900',
    danger: 'border-red-100 bg-red-50 text-red-900',
  }[tone];
  return (
    <div className={`border px-4 py-3 ${toneClass}`}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function StatusBadge({ job }: { job: TaskCenterJob }) {
  const status = job.ignored ? 'ignored' : job.archived ? 'archived' : job.status;
  const labelMap: Record<string, string> = {
    failed: '失败',
    queued: '排队',
    running: '运行中',
    retry_waiting: '等待重试',
    succeeded: '成功',
    cancelled: '已取消',
    ignored: '已忽略',
    archived: '已归档',
  };
  const classMap: Record<string, string> = {
    failed: 'bg-red-50 text-red-700',
    queued: 'bg-blue-50 text-blue-700',
    running: 'bg-amber-50 text-amber-700',
    retry_waiting: 'bg-amber-50 text-amber-700',
    succeeded: 'bg-emerald-50 text-emerald-700',
    cancelled: 'bg-gray-100 text-gray-600',
    ignored: 'bg-gray-100 text-gray-600',
    archived: 'bg-slate-100 text-slate-600',
  };
  return <span className={`px-2 py-1 text-xs font-medium ${classMap[status] || 'bg-gray-100 text-gray-600'}`}>{labelMap[status] || status}</span>;
}

function TaskDetailDrawer({
  job,
  busy,
  onClose,
  onRetry,
  onIgnore,
  onUnignore,
}: {
  job: TaskCenterJob;
  busy: boolean;
  onClose: () => void;
  onRetry: () => void;
  onIgnore: () => void;
  onUnignore: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[100] flex justify-end">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <aside className="relative h-full w-full max-w-2xl overflow-y-auto bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-gray-100 bg-white px-6 py-5">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{job.task_display_name}</h2>
            <p className="mt-1 font-mono text-xs text-gray-400">{job.id}</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 px-6 py-5">
          <section className="grid grid-cols-2 gap-3">
            <Info label="状态" value={job.ignored ? '已忽略' : statusLabel(job.status)} />
            <Info label="队列" value={job.queue_name || 'default'} />
            <Info label="发起人" value={job.initiated_by_name} />
            <Info label="尝试次数" value={`${job.attempt_count ?? 0}/${job.max_attempts ?? '-'}`} />
            <Info label="更新时间" value={formatSecond(job.updated_at)} />
            <Info label="创建时间" value={formatSecond(job.created_at)} />
          </section>

          <section className="border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900">关联对象</h3>
            <div className="mt-3 text-sm text-gray-700">
              {job.related_object_route ? (
                <Link to={job.related_object_route} className="font-medium text-brand-700 hover:text-brand-800">
                  {job.related_object_name}
                </Link>
              ) : (
                <span>{job.related_object_name}</span>
              )}
            </div>
          </section>

          {job.status === 'failed' && (
            <section className="border border-red-100 bg-red-50 p-4">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-600" />
                <h3 className="text-sm font-semibold text-red-900">失败信息</h3>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <Info label="错误类型" value={failureCategoryLabel(job.failure_category)} />
                <Info label="错误码" value={job.error_code || '-'} />
              </div>
              <p className="mt-3 text-sm text-red-800">{job.failure_summary}</p>
              <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-words border border-red-100 bg-white p-3 text-xs text-gray-700">
                {job.error_message || '没有原始报错信息'}
              </pre>
            </section>
          )}

          {(job.ignored || job.ignore_reason || job.ignored_at) && (
            <section className="border border-gray-200 bg-gray-50 p-4">
              <h3 className="text-sm font-semibold text-gray-900">忽略记录</h3>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <Info label="忽略时间" value={formatSecond(job.ignored_at)} />
                <Info label="当前状态" value={job.ignored ? '已忽略' : '未忽略'} />
              </div>
              <p className="mt-3 whitespace-pre-wrap break-words text-sm text-gray-700">
                {job.ignore_reason || '未填写原因'}
              </p>
            </section>
          )}

          <section className="border border-gray-200 p-4">
            <div className="flex items-center gap-2">
              <Clock3 className="h-4 w-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900">时间线</h3>
            </div>
            <div className="mt-3 space-y-2 text-sm text-gray-600">
              <TimelineRow label="创建" value={formatSecond(job.created_at)} />
              <TimelineRow label="开始" value={formatSecond(job.started_at)} />
              <TimelineRow label="完成/失败" value={formatSecond(job.finished_at)} />
              <TimelineRow label="最近更新" value={formatSecond(job.updated_at)} />
            </div>
          </section>

          <section className="flex flex-wrap items-center gap-2 border-t border-gray-100 pt-5">
            {job.can_retry && (
              <button
                type="button"
                onClick={onRetry}
                disabled={busy}
                className="inline-flex items-center gap-1.5 bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                <RotateCcw className="h-4 w-4" />
                重试
              </button>
            )}
            {job.ignored ? (
              <button
                type="button"
                onClick={onUnignore}
                disabled={busy}
                className="border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:border-brand-300 hover:text-brand-700 disabled:opacity-50"
              >
                取消忽略
              </button>
            ) : job.status === 'failed' ? (
              <button
                type="button"
                onClick={onIgnore}
                disabled={busy}
                className="border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:border-red-200 hover:text-red-700 disabled:opacity-50"
              >
                忽略
              </button>
            ) : null}
            <Link
              to={job.debug_ref.route}
              className="border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:border-amber-300 hover:text-amber-700"
            >
              技术详情
            </Link>
          </section>
        </div>
      </aside>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-gray-100 bg-gray-50 px-3 py-2">
      <div className="text-[11px] text-gray-400">{label}</div>
      <div className="mt-1 break-words text-sm font-medium text-gray-800">{value}</div>
    </div>
  );
}

function TimelineRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-gray-500">{label}</span>
      <span className="font-mono text-xs text-gray-600">{value}</span>
    </div>
  );
}

function tabCount(totals: TaskCenterData['totals'] | undefined, key: string): number {
  if (!totals) return 0;
  if (key === 'needs_attention') return totals.needs_attention_count || 0;
  if (key === 'active') return totals.active_count || 0;
  if (key === 'ignored') return totals.ignored_count || 0;
  return totals.total_count || 0;
}

function lookbackLabel(hours: number): string {
  return LOOKBACK_OPTIONS.find((option) => option.value === hours)?.label || `近${hours}小时`;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    failed: '失败',
    queued: '排队',
    running: '运行中',
    retry_waiting: '等待重试',
    succeeded: '成功',
    cancelled: '已取消',
  };
  return labels[status] || status;
}

function failureCategoryLabel(value: string): string {
  const labels: Record<string, string> = {
    db_constraint: '数据约束',
    code_error: '系统异常',
    schema_validation: '结构校验',
    provider_auth: '模型认证',
    provider_or_llm: '模型服务',
    unknown: '未分类',
  };
  return labels[value] || value;
}

function formatMinute(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${d} ${hh}:${mm}`;
}

function formatSecond(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
}
