import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Archive, Eye, FlaskConical, RefreshCw, RotateCcw, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { backgroundJobs } from '../lib/api';
import type { BackgroundJobFailure, BackgroundJobRetryPreview, FailureSummary } from '../types/api';

const DEFAULT_LOOKBACK_HOURS = 720;

export default function BackgroundJobFailurePanel() {
  const [summary, setSummary] = useState<FailureSummary | null>(null);
  const [includeIgnored, setIncludeIgnored] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [includeTestData, setIncludeTestData] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<BackgroundJobRetryPreview | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null);
  const [operatingJobId, setOperatingJobId] = useState<string | null>(null);

  const loadSummary = useCallback(() => {
    setLoading(true);
    setError(null);
    backgroundJobs
      .summaryFailures({
        lookback_hours: DEFAULT_LOOKBACK_HOURS,
        limit: 10,
        include_ignored: includeIgnored,
        include_archived: includeArchived,
        include_test_data: includeTestData,
      })
      .then(setSummary)
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoading(false));
  }, [includeArchived, includeIgnored, includeTestData]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  async function openRetryPreview(job: BackgroundJobFailure) {
    setPreviewLoadingId(job.id);
    setError(null);
    try {
      setPreview(await backgroundJobs.retryPreview(job.id));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  async function retryJob(job: BackgroundJobFailure) {
    setOperatingJobId(job.id);
    setError(null);
    try {
      const retryPreview = await backgroundJobs.retryPreview(job.id);
      setPreview(retryPreview);
      const blockers = retryPreview.warnings.filter((item) => item.severity === 'blocker');
      if (blockers.length > 0) {
        setError(`无法重试：${blockers.map((item) => item.message).join('；')}`);
        return;
      }
      const warningText = retryPreview.warnings.length
        ? `\n\n预警：\n${retryPreview.warnings.map((item) => `- ${item.message}`).join('\n')}`
        : '';
      const confirmed = window.confirm(
        `确认重试任务 ${job.job_type}？\n\nJob ID: ${job.id}${warningText}\n\n重试会清空当前错误并把任务重新放回 ${job.queue_name || 'default'} 队列。`,
      );
      if (!confirmed) return;
      await backgroundJobs.retry(job.id);
      setPreview(null);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function retryFromPreview(currentPreview: BackgroundJobRetryPreview) {
    setOperatingJobId(currentPreview.job.id);
    setError(null);
    try {
      await backgroundJobs.retry(currentPreview.job.id);
      setPreview(null);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function ignoreJob(job: BackgroundJobFailure) {
    const reason = window.prompt('请输入忽略原因（例如：历史测试数据 / 已由新版本修复 / 无需处理）', job.ignore_reason || '');
    if (reason === null) return;
    setOperatingJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.ignore(job.id, reason.trim() || undefined);
      setPreview(null);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function unignoreJob(job: BackgroundJobFailure) {
    const confirmed = window.confirm(`确认恢复显示失败任务？\n\nJob ID: ${job.id}`);
    if (!confirmed) return;
    setOperatingJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.unignore(job.id);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function archiveJob(job: BackgroundJobFailure) {
    const reason = window.prompt('请输入归档原因（例如：历史失败，保留审计但不再处理）', job.archive_reason || '');
    if (reason === null) return;
    setOperatingJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.archive(job.id, reason.trim() || undefined);
      setPreview(null);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function unarchiveJob(job: BackgroundJobFailure) {
    const confirmed = window.confirm(`确认取消归档失败任务？\n\nJob ID: ${job.id}`);
    if (!confirmed) return;
    setOperatingJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.unarchive(job.id);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function markTestData(job: BackgroundJobFailure) {
    const label = window.prompt('请输入测试数据标签（例如：demo / sample / 历史压测）', job.test_data_label || '');
    if (label === null) return;
    const reason = window.prompt('请输入标记为测试数据的原因', job.test_data_reason || '');
    if (reason === null) return;
    setOperatingJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.markTestData(job.id, {
        label: label.trim() || undefined,
        reason: reason.trim() || undefined,
      });
      setPreview(null);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  async function unmarkTestData(job: BackgroundJobFailure) {
    const confirmed = window.confirm(`确认取消测试数据标记？\n\nJob ID: ${job.id}`);
    if (!confirmed) return;
    setOperatingJobId(job.id);
    setError(null);
    try {
      await backgroundJobs.unmarkTestData(job.id);
      loadSummary();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOperatingJobId(null);
    }
  }

  const failures = summary?.recent_failures || [];
  const failedCount = summary?.totals.failed_job_count || 0;

  return (
    <div className="bg-white border border-gray-200 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-500" />
            后台任务失败
          </h2>
          <p className="text-xs text-gray-400 mt-1">近 {DEFAULT_LOOKBACK_HOURS} 小时，默认隐藏已忽略失败</p>
        </div>
        <button
          onClick={loadSummary}
          className="text-xs text-gray-500 hover:text-brand-600 inline-flex items-center gap-1"
          disabled={loading}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <Metric label="失败任务" value={failedCount} tone={failedCount > 0 ? 'danger' : 'normal'} />
        <Metric label="失败队列" value={summary?.totals.failed_queue_count || 0} />
        <Metric label="任务类型" value={summary?.totals.failed_job_type_count || 0} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <FilterCheckbox checked={includeIgnored} onChange={setIncludeIgnored} label="包含已忽略" />
        <FilterCheckbox checked={includeArchived} onChange={setIncludeArchived} label="包含已归档" />
        <FilterCheckbox checked={includeTestData} onChange={setIncludeTestData} label="包含测试数据" />
      </div>

      {error && (
        <div className="mt-3 border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : failures.length === 0 ? (
        <p className="text-sm text-gray-400 py-6 text-center">暂无需要处理的失败任务</p>
      ) : (
        <div className="mt-3 space-y-2">
          {failures.map((job) => (
            <FailureItem
              key={job.id}
              job={job}
              busy={operatingJobId === job.id || previewLoadingId === job.id}
              onPreview={() => openRetryPreview(job)}
              onRetry={() => retryJob(job)}
              onIgnore={() => ignoreJob(job)}
              onUnignore={() => unignoreJob(job)}
              onArchive={() => archiveJob(job)}
              onUnarchive={() => unarchiveJob(job)}
              onMarkTestData={() => markTestData(job)}
              onUnmarkTestData={() => unmarkTestData(job)}
            />
          ))}
        </div>
      )}

      {preview && (
        <RetryPreviewModal
          preview={preview}
          onClose={() => setPreview(null)}
          onRetry={() => retryFromPreview(preview)}
          retrying={operatingJobId === preview.job.id}
        />
      )}
    </div>
  );
}

function FailureItem({
  job,
  busy,
  onPreview,
  onRetry,
  onIgnore,
  onUnignore,
  onArchive,
  onUnarchive,
  onMarkTestData,
  onUnmarkTestData,
}: {
  job: BackgroundJobFailure;
  busy: boolean;
  onPreview: () => void;
  onRetry: () => void;
  onIgnore: () => void;
  onUnignore: () => void;
  onArchive: () => void;
  onUnarchive: () => void;
  onMarkTestData: () => void;
  onUnmarkTestData: () => void;
}) {
  return (
    <div className={`border p-3 ${job.ignored || job.archived || job.is_test_data ? 'border-gray-100 bg-gray-50' : 'border-red-100 bg-red-50/30'}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs px-1.5 py-0.5 bg-white border border-gray-200 text-gray-700 font-medium">
              {job.queue_name || 'default'}
            </span>
            <span className="text-xs px-1.5 py-0.5 bg-amber-50 text-amber-700 font-medium">
              {failureCategoryLabel(job.failure_category)}
            </span>
            {job.ignored && (
              <span className="text-xs px-1.5 py-0.5 bg-gray-200 text-gray-600 font-medium">已忽略</span>
            )}
            {job.archived && (
              <span className="text-xs px-1.5 py-0.5 bg-slate-200 text-slate-600 font-medium">已归档</span>
            )}
            {job.is_test_data && (
              <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 font-medium">
                测试数据{job.test_data_label ? ` · ${job.test_data_label}` : ''}
              </span>
            )}
          </div>
          <p className="text-sm font-medium text-gray-900 mt-2 truncate">{job.job_type}</p>
          <p className="text-xs text-gray-600 mt-1 line-clamp-2">{job.failure_summary}</p>
          {job.error_message && (
            <p className="text-xs text-gray-400 mt-1 line-clamp-2">{job.error_message}</p>
          )}
          <p className="text-[11px] text-gray-400 mt-2 font-mono">
            {job.id} · {formatDateTime(job.updated_at)}
          </p>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <SmallButton onClick={onPreview} disabled={busy || !job.can_retry} icon={Eye}>
          预览
        </SmallButton>
        <SmallButton onClick={onRetry} disabled={busy || !job.can_retry} icon={RotateCcw} tone="brand">
          重试
        </SmallButton>
        {job.ignored ? (
          <SmallButton onClick={onUnignore} disabled={busy} icon={Archive}>
            取消忽略
          </SmallButton>
        ) : (
          <SmallButton onClick={onIgnore} disabled={busy} icon={Archive}>
            忽略
          </SmallButton>
        )}
        {job.archived ? (
          <SmallButton onClick={onUnarchive} disabled={busy} icon={Archive}>
            取消归档
          </SmallButton>
        ) : (
          <SmallButton onClick={onArchive} disabled={busy} icon={Archive}>
            归档
          </SmallButton>
        )}
        {job.is_test_data ? (
          <SmallButton onClick={onUnmarkTestData} disabled={busy} icon={FlaskConical}>
            取消测试标记
          </SmallButton>
        ) : (
          <SmallButton onClick={onMarkTestData} disabled={busy} icon={FlaskConical}>
            标记测试数据
          </SmallButton>
        )}
      </div>
    </div>
  );
}

function RetryPreviewModal({
  preview,
  onClose,
  onRetry,
  retrying,
}: {
  preview: BackgroundJobRetryPreview;
  onClose: () => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  const blockers = preview.warnings.filter((item) => item.severity === 'blocker');
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white border border-gray-200 shadow-xl w-full max-w-2xl mx-4 max-h-[86vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h3 className="text-base font-semibold text-gray-900">重试预览</h3>
            <p className="text-xs text-gray-400 mt-0.5 font-mono">{preview.job.id}</p>
          </div>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <InfoBox label="队列" value={preview.retry.queue_name || '-'} />
            <InfoBox label="可重试" value={preview.retry.eligible ? '是' : '否'} />
            <InfoBox label="Trace 数" value={String(preview.related.trace_count)} />
            <InfoBox label="同实体活跃任务" value={String(preview.related.active_same_entity_job_count)} />
          </div>

          {preview.warnings.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-gray-700">预警</h4>
              {preview.warnings.map((warning) => (
                <div
                  key={warning.key}
                  className={`px-3 py-2 text-xs border ${
                    warning.severity === 'blocker'
                      ? 'bg-red-50 border-red-100 text-red-700'
                      : warning.severity === 'warning'
                        ? 'bg-amber-50 border-amber-100 text-amber-700'
                        : 'bg-blue-50 border-blue-100 text-blue-700'
                  }`}
                >
                  {warning.message}
                </div>
              ))}
            </div>
          )}

          <div>
            <h4 className="text-xs font-semibold text-gray-700 mb-2">重试影响</h4>
            <div className="space-y-2">
              {preview.effects.map((effect) => (
                <div key={effect.key} className="border border-gray-100 bg-gray-50 px-3 py-2">
                  <p className="text-xs font-medium text-gray-800">{effect.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{effect.description}</p>
                </div>
              ))}
            </div>
          </div>

          {preview.related.business_update && (
            <div>
              <h4 className="text-xs font-semibold text-gray-700 mb-2">关联业务更新</h4>
              <div className="border border-gray-100 bg-gray-50 p-3 text-xs text-gray-600 space-y-1">
                <p>状态：{preview.related.business_update.processing_status}</p>
                <p>拆分动作数：{preview.related.business_update.action_count}</p>
                <p>应用日志数：{preview.related.business_update.application_log_count}</p>
              </div>
            </div>
          )}

          <div>
            <h4 className="text-xs font-semibold text-gray-700 mb-2">错误摘要</h4>
            <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words border border-gray-100 bg-gray-50 p-3 text-xs text-gray-600">
              {preview.job.error_message || preview.job.failure_summary || '无错误信息'}
            </pre>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">
              关闭
            </button>
            <button
              onClick={onRetry}
              disabled={!preview.retry.eligible || blockers.length > 0 || retrying}
              className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {retrying ? '重试中...' : '确认重试'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = 'normal' }: { label: string; value: number; tone?: 'normal' | 'danger' }) {
  return (
    <div className="border border-gray-100 bg-gray-50 px-3 py-2">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className={`text-lg font-semibold font-mono ${tone === 'danger' ? 'text-red-600' : 'text-gray-900'}`}>
        {value}
      </p>
    </div>
  );
}

function FilterCheckbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-3.5 w-3.5 accent-brand-600"
      />
      {label}
    </label>
  );
}

function InfoBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-gray-100 bg-gray-50 px-3 py-2">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="text-xs font-medium text-gray-800 mt-1">{value}</p>
    </div>
  );
}

function SmallButton({
  children,
  onClick,
  disabled,
  icon: Icon,
  tone = 'default',
}: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  icon: LucideIcon;
  tone?: 'default' | 'brand';
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs border disabled:opacity-50 ${
        tone === 'brand'
          ? 'bg-brand-600 text-white border-brand-600 hover:bg-brand-700'
          : 'bg-white text-gray-600 border-gray-200 hover:text-brand-600 hover:border-brand-200'
      }`}
    >
      <Icon className="w-3 h-3" />
      {children}
    </button>
  );
}

function failureCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    db_constraint: 'DB 约束',
    code_error: '代码错误',
    schema_validation: 'Schema 校验',
    provider_or_llm: '模型调用',
    unknown: '未知',
  };
  return labels[category] || category;
}

function formatDateTime(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
