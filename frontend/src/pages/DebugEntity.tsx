import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Bug, Database, FileJson, RefreshCw } from 'lucide-react';
import { debugApi } from '../lib/api';
import type { DebugEntity } from '../types/api';

const SECRET_KEY_PATTERN = /(key|token|password|secret|authorization|credential)/i;

export default function DebugEntityPage() {
  const { entityType, entityId } = useParams<{ entityType: string; entityId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<DebugEntity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!entityType || !entityId) return;
    setLoading(true);
    setError(null);
    debugApi
      .entity(entityType, entityId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : '异常详情加载失败'))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, [entityType, entityId]);

  const sections = useMemo(() => buildSections(data?.payload || {}), [data]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-amber-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <button type="button" onClick={() => navigate(-1)} className="p-1.5 text-gray-400 hover:text-gray-700">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <Bug className="w-5 h-5 text-amber-600" />
              <h1 className="text-lg font-semibold text-gray-900">{summaryTitle(data)}</h1>
            </div>
            <p className="text-xs text-gray-400 font-mono mt-1">
              {entityType || '-'} / {entityId || '-'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/debug" className="px-3 py-1.5 text-sm border border-gray-200 text-gray-700 bg-white hover:border-amber-300 hover:text-amber-700">
            Debug Center
          </Link>
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
      </div>

      {error && <div className="border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {data && (
        <>
          <SummaryPanel data={data} />

          {businessRoute(data) && (
            <div className="bg-brand-50 border border-brand-100 px-4 py-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-brand-900">关联业务页面</p>
                <p className="text-xs text-brand-700 mt-0.5">可回到业务复核页或推荐页查看用户视角。</p>
              </div>
              <Link to={businessRoute(data) || '/'} className="px-3 py-1.5 text-sm bg-brand-600 text-white hover:bg-brand-700">
                打开业务页
              </Link>
            </div>
          )}

          <div className="grid grid-cols-12 gap-5">
            <div className="col-span-12 xl:col-span-8 space-y-5">
              {sections.length === 0 ? (
                <EmptyState label="该对象暂无结构化排障明细" />
              ) : (
                sections.map((section) => (
                  <Section key={section.key} title={section.title} count={section.count}>
                    {section.node}
                  </Section>
                ))
              )}
            </div>
            <div className="col-span-12 xl:col-span-4">
              <Section title="完整 Payload">
                <JsonBlock value={data.payload} />
              </Section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SummaryPanel({ data }: { data: DebugEntity }) {
  const summaryEntries = Object.entries(data.summary || {}).filter(([, value]) => value !== null && value !== undefined);
  return (
    <div className="bg-white border border-gray-200 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Database className="w-4 h-4 text-gray-400" />
        <h2 className="text-sm font-semibold text-gray-900">摘要</h2>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {summaryEntries.map(([key, value]) => (
          <InfoBox key={key} label={summaryLabel(key)} value={formatValue(value)} tone={key === 'status' ? statusTone(String(value)) : 'normal'} />
        ))}
      </div>
    </div>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="bg-white border border-gray-200">
      <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileJson className="w-4 h-4 text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        </div>
        {typeof count === 'number' && <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5">{count}</span>}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function RecordCard({ item }: { item: Record<string, unknown> }) {
  const title = pickTitle(item);
  const subtitle = pickSubtitle(item);
  const entries = Object.entries(item)
    .filter(([key, value]) => value !== null && value !== undefined && !isComplex(value) && key !== 'id')
    .slice(0, 8);

  return (
    <div className="border border-gray-100 bg-gray-50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 line-clamp-1">{title}</p>
          {subtitle && <p className="text-xs text-gray-500 mt-1 line-clamp-2">{subtitle}</p>}
        </div>
        {typeof item.status === 'string' && <StatusBadge status={item.status} />}
      </div>
      {typeof item.id === 'string' && <p className="text-[11px] text-gray-400 font-mono mt-2">{item.id}</p>}
      {entries.length > 0 && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-3">
          {entries.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <span className="text-[11px] text-gray-400">{summaryLabel(key)}：</span>
              <span className="text-xs text-gray-700 break-words">{formatFieldValue(key, value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words bg-slate-950 text-slate-100 p-4 text-xs leading-relaxed">
      {JSON.stringify(maskSecrets(value), null, 2)}
    </pre>
  );
}

function InfoBox({
  label,
  value,
  tone = 'normal',
}: {
  label: string;
  value: string;
  tone?: 'normal' | 'success' | 'warning' | 'danger';
}) {
  const toneClass = {
    normal: 'bg-gray-50 text-gray-800 border-gray-100',
    success: 'bg-emerald-50 text-emerald-800 border-emerald-100',
    warning: 'bg-amber-50 text-amber-800 border-amber-100',
    danger: 'bg-red-50 text-red-800 border-red-100',
  }[tone];
  return (
    <div className={`border px-3 py-2 ${toneClass}`}>
      <p className="text-[11px] opacity-70">{label}</p>
      <p className="text-sm font-medium mt-1 break-words">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`text-xs px-1.5 py-0.5 font-medium ${statusClass(status)}`}>{statusLabel(status)}</span>;
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="bg-white border border-gray-200 py-12 text-center">
      <Bug className="w-8 h-8 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-400">{label}</p>
    </div>
  );
}

function buildSections(payload: Record<string, unknown>) {
  const sections: Array<{ key: string; title: string; count?: number; node: ReactNode }> = [];
  const singleRecordKeys = [
    ['job', '任务详情'],
    ['business_update', '业务更新'],
    ['entity', '业务对象'],
    ['session', '推荐会话'],
    ['attachment', '附件'],
    ['node', '模型节点'],
    ['report', '推荐报告'],
    ['search_doc', '搜索文档'],
    ['debug', 'Debug 统计'],
  ] as const;
  const arrayKeys = [
    ['traces', 'AI Trace'],
    ['jobs', '关联任务'],
    ['related_jobs', '相关任务'],
    ['actions', '拆解动作'],
    ['application_logs', '应用日志'],
    ['field_sources', '字段来源'],
    ['relations', '推荐/跟进关系'],
    ['relation_events', '跟进事件'],
    ['messages', '推荐消息'],
    ['selected_items', '已选推荐项'],
    ['reports', '推荐报告'],
    ['links', '附件关联'],
    ['parsed_documents', '解析文档'],
    ['evidence_spans', '证据片段'],
  ] as const;

  for (const [key, title] of singleRecordKeys) {
    const record = asRecord(payload[key]);
    if (!record) continue;
    sections.push({
      key,
      title,
      node: key === 'debug' ? <JsonBlock value={record} /> : <RecordCard item={record} />,
    });
  }

  for (const [key, title] of arrayKeys) {
    const records = asRecordArray(payload[key]);
    if (!records || records.length === 0) continue;
    sections.push({
      key,
      title,
      count: records.length,
      node: (
        <div className="space-y-3">
          {records.map((item, index) => (
            <RecordCard key={String(item.id || index)} item={item} />
          ))}
        </div>
      ),
    });
  }

  return sections;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asRecordArray(value: unknown): Record<string, unknown>[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item));
}

function pickTitle(item: Record<string, unknown>): string {
  for (const key of ['title', 'name', 'target_name', 'buyer_name', 'intent_name', 'job_type', 'node_name', 'file_name', 'report_type']) {
    if (typeof item[key] === 'string' && item[key]) return item[key];
  }
  return typeof item.id === 'string' ? item.id : '未命名记录';
}

function pickSubtitle(item: Record<string, unknown>): string | null {
  for (const key of ['error_message', 'failure_summary', 'raw_text', 'raw_output_text', 'content', 'text_excerpt', 'business_summary']) {
    if (typeof item[key] === 'string' && item[key]) return item[key];
  }
  return null;
}

function summaryTitle(data: DebugEntity | null): string {
  const title = data?.summary?.title;
  return typeof title === 'string' && title ? title : '异常详情';
}

function businessRoute(data: DebugEntity): string | null {
  if (data.entity_type === 'business_update') return `/updates/${data.entity_id}`;
  if (data.entity_type === 'seller_target') return `/targets/${data.entity_id}`;
  if (data.entity_type === 'buyer_party') return `/buyers/${data.entity_id}`;
  if (data.entity_type === 'buyer_intent') return `/buyer-intents/${data.entity_id}`;
  if (data.entity_type === 'recommendation_session') return '/recommendations';
  if (data.entity_type === 'background_job') {
    const job = asRecord(data.payload.job);
    const type = job?.entity_type;
    const id = job?.entity_id;
    if (type === 'business_update' && typeof id === 'string') return `/updates/${id}`;
    if (type === 'seller_target' && typeof id === 'string') return `/targets/${id}`;
    if (type === 'buyer_party' && typeof id === 'string') return `/buyers/${id}`;
    if (type === 'buyer_intent' && typeof id === 'string') return `/buyer-intents/${id}`;
  }
  return null;
}

function maskSecrets(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(maskSecrets);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, item]) => [
      key,
      SECRET_KEY_PATTERN.test(key) ? '[masked]' : maskSecrets(item),
    ]),
  );
}

function isComplex(value: unknown): boolean {
  return Boolean(value) && typeof value === 'object';
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string') return value.length > 120 ? `${value.slice(0, 119)}…` : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(maskSecrets(value));
}

function formatFieldValue(key: string, value: unknown): string {
  if (SECRET_KEY_PATTERN.test(key)) return '[masked]';
  return formatValue(value);
}

function summaryLabel(key: string): string {
  const labels: Record<string, string> = {
    title: '标题',
    status: '状态',
    queue_name: '队列',
    node_type: '节点类型',
    job_count: '任务数',
    trace_count: 'Trace 数',
    action_count: '动作数',
    message_count: '消息数',
    update_log_count: '更新日志',
    field_source_count: '字段来源',
    parsed_document_count: '解析文档',
    evidence_count: '证据数',
    job_type: '任务类型',
    error_code: '错误码',
    attempt_count: '尝试次数',
    max_attempts: '最大次数',
    created_at: '创建时间',
    updated_at: '更新时间',
    started_at: '开始时间',
    finished_at: '结束时间',
  };
  return labels[key] || key;
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
    active: '启用',
    inactive: '停用',
  };
  return labels[value] || value;
}

function statusClass(value: string): string {
  if (value === 'failed') return 'bg-red-50 text-red-700';
  if (value === 'running' || value === 'queued' || value === 'retry_waiting') return 'bg-amber-50 text-amber-700';
  if (value === 'succeeded' || value === 'completed' || value === 'parsed' || value === 'active') return 'bg-emerald-50 text-emerald-700';
  return 'bg-gray-100 text-gray-600';
}

function statusTone(value: string): 'normal' | 'success' | 'warning' | 'danger' {
  if (value === 'failed') return 'danger';
  if (value === 'running' || value === 'queued' || value === 'retry_waiting') return 'warning';
  if (value === 'succeeded' || value === 'completed' || value === 'parsed' || value === 'active') return 'success';
  return 'normal';
}
