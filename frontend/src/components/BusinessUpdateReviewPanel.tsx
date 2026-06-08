import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Bot, FileText, Loader2, RefreshCw, RotateCcw } from 'lucide-react';
import { businessUpdates } from '../lib/api';
import type { BusinessUpdateReviewPage } from '../types/api';

interface Props {
  businessUpdateId: string;
  onProcessed?: () => void;
}

export default function BusinessUpdateReviewPanel({ businessUpdateId, onProcessed }: Props) {
  const [data, setData] = useState<BusinessUpdateReviewPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    businessUpdates
      .reviewPage(businessUpdateId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : '读取复核页失败'))
      .finally(() => setLoading(false));
  }, [businessUpdateId]);

  useEffect(() => {
    load();
  }, [load]);

  async function rerunExtraction() {
    setProcessing(true);
    setError(null);
    try {
      await businessUpdates.process(businessUpdateId);
      onProcessed?.();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新解析失败');
    } finally {
      setProcessing(false);
    }
  }

  if (loading) {
    return (
      <div className="bg-white border border-gray-200 p-5 flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin" />
        正在加载复核详情...
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white border border-red-100 p-5 text-sm text-red-700">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {error}
        </div>
        <button onClick={load} className="mt-3 text-xs text-red-700 underline">
          重试
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-4">
      <div className="bg-white border border-gray-200 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">复核与处理进度</h3>
            <p className="mt-0.5 text-xs text-gray-500">附件、OCR、LLM 和动作拆解的统一状态。</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="inline-flex items-center gap-1.5 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-gray-300"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              刷新
            </button>
            <button
              onClick={rerunExtraction}
              disabled={processing}
              className="inline-flex items-center gap-1.5 border border-brand-200 bg-brand-50 px-2.5 py-1.5 text-xs text-brand-700 hover:bg-brand-100 disabled:opacity-50"
            >
              {processing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
              重新解析
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2">
          <Metric label="动作" value={numberValue(data.overview.action_count)} />
          <Metric label="待复核" value={numberValue(data.overview.pending_review_count)} tone="amber" />
          <Metric label="运行任务" value={numberValue(data.overview.running_job_count)} tone="blue" />
          <Metric label="失败" value={numberValue(data.overview.failed_job_count) + numberValue(data.overview.failed_trace_count)} tone="red" />
        </div>
      </div>

      <AttachmentSection attachments={data.attachments} />
      <ActionGroupSection groups={data.action_groups} />
      <JobTraceSection jobs={data.jobs} traces={data.traces} />
    </div>
  );
}

function AttachmentSection({ attachments }: { attachments: Array<Record<string, unknown>> }) {
  return (
    <div className="bg-white border border-gray-200">
      <SectionHeader icon={FileText} title={`附件与证据 (${attachments.length})`} />
      {attachments.length === 0 ? (
        <EmptyLine text="暂无附件" />
      ) : (
        <div className="divide-y divide-gray-100">
          {attachments.map((item) => (
            <div key={stringValue(item.id)} className="px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-gray-900">{stringValue(item.file_name) || '未命名附件'}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {stringValue(item.file_type) || stringValue(item.mime_type) || 'unknown'} · {formatBytes(numberValue(item.file_size))}
                  </p>
                </div>
                <StatusBadge status={stringValue(item.parse_status)} />
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500">
                {Boolean(item.parse_readiness) && (
                  <span>readiness: {stringValue(recordValue(item.parse_readiness).readiness_status)}</span>
                )}
                {Boolean(item.latest_job) && <span>job: {stringValue(recordValue(item.latest_job).status)}</span>}
                {numberValue(item.parsed_text_length) > 0 && <span>文本 {numberValue(item.parsed_text_length)} 字</span>}
                {item.multimodal_image_supported === true && <span>多模态图片</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ActionGroupSection({ groups }: { groups: Array<Record<string, unknown>> }) {
  return (
    <div className="bg-white border border-gray-200">
      <SectionHeader icon={Bot} title="拆解动作分组" />
      {groups.length === 0 ? (
        <EmptyLine text="暂无拆解动作" />
      ) : (
        <div className="divide-y divide-gray-100">
          {groups.map((group) => (
            <div key={stringValue(group.key)} className="px-4 py-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-gray-900">{stringValue(group.label) || stringValue(group.key)}</p>
                <span className="text-xs text-gray-500">{numberValue(group.count)} 个</span>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                待复核 {numberValue(group.pending_count)} · 自动应用 {numberValue(group.auto_applied_count)} · 高优先级{' '}
                {numberValue(group.high_priority_count)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function JobTraceSection({
  jobs,
  traces,
}: {
  jobs: Array<Record<string, unknown>>;
  traces: Array<Record<string, unknown>>;
}) {
  const recentJobs = jobs.slice(0, 5);
  const recentTraces = traces.slice(0, 5);
  return (
    <div className="bg-white border border-gray-200">
      <SectionHeader icon={RefreshCw} title={`后台任务 / AI Trace (${jobs.length}/${traces.length})`} />
      {recentJobs.length === 0 && recentTraces.length === 0 ? (
        <EmptyLine text="暂无任务或 Trace" />
      ) : (
        <div className="divide-y divide-gray-100">
          {recentJobs.map((job) => (
            <CompactRow
              key={`job-${stringValue(job.id)}`}
              title={`${stringValue(job.job_type)} · ${stringValue(job.queue_name)}`}
              subtitle={stringValue(job.error_message) || stringValue(job.created_at)}
              status={stringValue(job.status)}
            />
          ))}
          {recentTraces.map((trace) => (
            <CompactRow
              key={`trace-${stringValue(trace.id)}`}
              title={`${stringValue(trace.node_name)} · ${stringValue(trace.model_name)}`}
              subtitle={stringValue(trace.error_message) || `${numberValue(trace.latency_ms)} ms`}
              status={stringValue(trace.status)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CompactRow({ title, subtitle, status }: { title: string; subtitle: string; status: string }) {
  return (
    <div className="px-4 py-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate text-sm text-gray-800">{title}</p>
        {subtitle && <p className="mt-0.5 truncate text-xs text-gray-400">{subtitle}</p>}
      </div>
      <StatusBadge status={status} />
    </div>
  );
}

function SectionHeader({ icon: Icon, title }: { icon: typeof FileText; title: string }) {
  return (
    <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
      <Icon className="w-4 h-4 text-brand-600" />
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="px-4 py-6 text-center text-sm text-gray-400">{text}</p>;
}

function Metric({ label, value, tone = 'gray' }: { label: string; value: number; tone?: 'gray' | 'amber' | 'blue' | 'red' }) {
  const colors = {
    gray: 'bg-gray-50 text-gray-900',
    amber: 'bg-amber-50 text-amber-700',
    blue: 'bg-blue-50 text-blue-700',
    red: 'bg-red-50 text-red-700',
  };
  return (
    <div className={`px-3 py-2 ${colors[tone]}`}>
      <p className="text-[11px] opacity-70">{label}</p>
      <p className="mt-0.5 text-lg font-semibold">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-50 text-amber-700',
    queued: 'bg-amber-50 text-amber-700',
    retry_waiting: 'bg-amber-50 text-amber-700',
    processing: 'bg-blue-50 text-blue-700',
    parsing: 'bg-blue-50 text-blue-700',
    running: 'bg-blue-50 text-blue-700',
    parsed: 'bg-emerald-50 text-emerald-700',
    succeeded: 'bg-emerald-50 text-emerald-700',
    applied: 'bg-emerald-50 text-emerald-700',
    skipped: 'bg-gray-100 text-gray-600',
    failed: 'bg-red-50 text-red-700',
  };
  return <span className={`shrink-0 px-1.5 py-0.5 text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-600'}`}>{status || 'unknown'}</span>;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function stringValue(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

function numberValue(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value > 0) return `${value} B`;
  return '未知大小';
}
