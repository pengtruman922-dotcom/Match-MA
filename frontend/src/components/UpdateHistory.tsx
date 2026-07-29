import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  Loader2,
  RotateCcw,
  X,
} from 'lucide-react';
import { attachments, research, updateLogs } from '../lib/api';
import type { FieldValueSource, ResearchReport, UpdateBatch, UpdateBatchChange } from '../types/api';
import { fieldLabel, sourceTypeLabel, valueLabel } from '../lib/fieldLabels';
import ResearchEvidenceDrawer from '../features/targets/ResearchEvidenceDrawer';
import ResearchReportDrawer from '../features/targets/ResearchReportDrawer';

type EntityType = 'seller_target' | 'buyer_intent';

interface Props {
  entityType: EntityType;
  entityId: string;
  refreshKey?: number;
  onRolledBack?: () => void | Promise<void>;
  onProcessingSettled?: () => void | Promise<void>;
}

const POLL_INTERVAL_MS = 4000;

export default function UpdateHistory({
  entityType,
  entityId,
  refreshKey = 0,
  onRolledBack,
  onProcessingSettled,
}: Props) {
  const [items, setItems] = useState<UpdateBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());
  const [rollbackBatch, setRollbackBatch] = useState<UpdateBatch | null>(null);
  const [rollbackLoading, setRollbackLoading] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [researchReport, setResearchReport] = useState<ResearchReport | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<FieldValueSource | null>(null);
  const wasParsingRef = useRef(false);
  const processingSettledRef = useRef(onProcessingSettled);

  useEffect(() => {
    processingSettledRef.current = onProcessingSettled;
  }, [onProcessingSettled]);

  const load = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const response = await updateLogs.batches({ entity_type: entityType, entity_id: entityId, limit: 50 });
      const nextHasParsing = response.items.some((item) => ['parsing', 'queued', 'researching', 'mapping'].includes(item.status));
      if (wasParsingRef.current && !nextHasParsing) {
        await processingSettledRef.current?.();
      }
      wasParsingRef.current = nextHasParsing;
      setItems(response.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新记录加载失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [entityId, entityType]);

  useEffect(() => {
    void load(true);
  }, [load, refreshKey]);

  const hasParsing = useMemo(
    () => items.some((item) => ['parsing', 'queued', 'researching', 'mapping'].includes(item.status)),
    [items],
  );
  useEffect(() => {
    if (!hasParsing) return;
    const timer = window.setInterval(() => void load(false), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [hasParsing, load]);

  const toggleExpanded = (batchKey: string) => {
    setExpandedKeys((current) => {
      const next = new Set(current);
      if (next.has(batchKey)) next.delete(batchKey);
      else next.add(batchKey);
      return next;
    });
  };

  const handleDownload = async (batch: UpdateBatch, attachmentId: string, fileName: string) => {
    setDownloadingId(attachmentId);
    try {
      const response = await attachments.download(attachmentId);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = fileName || 'attachment';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : `下载${batch.source_type}附件失败`);
    } finally {
      setDownloadingId(null);
    }
  };

  const handleRollback = async () => {
    if (!rollbackBatch) return;
    setRollbackLoading(true);
    try {
      await updateLogs.rollbackBatch(rollbackBatch.batch_key, {
        entity_type: entityType,
        entity_id: entityId,
        reason: '用户从实体更新记录撤回最近一次更新',
      });
      setRollbackBatch(null);
      await Promise.all([load(false), Promise.resolve(onRolledBack?.())]);
    } catch (err) {
      alert(err instanceof Error ? err.message : '撤回更新失败');
      await load(false);
    } finally {
      setRollbackLoading(false);
    }
  };

  const openResearchReport = async (jobId: string) => {
    try {
      setSelectedEvidence(null);
      setResearchReport(await research.report(jobId));
    } catch (err) {
      alert(err instanceof Error ? err.message : '读取调研报告失败');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-gray-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在读取更新记录
      </div>
    );
  }

  if (error && items.length === 0) {
    return (
      <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (items.length === 0) {
    return <div className="py-12 text-center text-sm text-gray-400">暂无更新记录</div>;
  }

  return (
    <>
      <div className="divide-y divide-gray-100">
        {items.map((item) => {
          const expanded = expandedKeys.has(item.batch_key);
          return (
            <article key={item.batch_key} className="px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-gray-500">{formatDateTime(item.submitted_at)}</span>
                    <span className="text-sm font-medium text-gray-900">{item.operator_name}</span>
                    <BatchStatusBadge status={item.status} sourceType={item.source_type} />
                    {item.batch_category === 'management_operation' ? (
                      <span className="bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-700">管理操作</span>
                    ) : null}
                    {item.is_latest_effective_batch ? (
                      <span className="bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500">最近一次有效更新</span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-gray-500">
                    来源：{batchSourceLabel(item)}
                    {item.changed_field_count > 0
                      ? ` · 最终写入 ${item.changed_field_count} 个字段`
                      : item.source_type === 'research_proposal' && item.status === 'applied'
                        ? ' · 未写入字段'
                        : ''}
                  </p>
                  {item.input_summary ? (
                    <p className="mt-2 line-clamp-2 text-sm leading-6 text-gray-700" title={item.raw_input || item.input_summary}>
                      录入：{item.input_summary}
                    </p>
                  ) : null}
                  {item.attachments.length > 0 ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <span className="text-xs text-gray-500">附件：</span>
                      {item.attachments.map((attachment) => (
                        <button
                          key={attachment.id}
                          type="button"
                          onClick={() => void handleDownload(item, attachment.id, attachment.file_name)}
                          disabled={downloadingId === attachment.id}
                          className="inline-flex max-w-[280px] items-center gap-1 text-xs text-brand-700 hover:text-brand-900 disabled:opacity-50"
                          title={`下载 ${attachment.file_name}`}
                        >
                          {downloadingId === attachment.id ? (
                            <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                          ) : (
                            <Download className="h-3 w-3 shrink-0" />
                          )}
                          <span className="truncate">{attachment.file_name}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {item.status === 'failed' ? (
                    <div className="mt-2 flex items-start gap-1.5 text-xs text-red-700">
                      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      {item.source_type === 'research_proposal'
                        ? '本次调研失败，未写入字段。请在任务中心查看错误后重试。'
                        : '本次解析失败，未写入字段。请重新录入更新，或联系管理员在任务中心处理。'}
                    </div>
                  ) : null}
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  {item.source_type === 'research_proposal' && item.source_id && item.report_available ? (
                    <button
                      type="button"
                      onClick={() => void openResearchReport(item.source_id as string)}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-700 hover:bg-brand-50"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      查看调研报告
                    </button>
                  ) : null}
                  {(item.raw_input || item.attachments.length > 0 || item.changes.length > 0) ? (
                    <button
                      type="button"
                      onClick={() => toggleExpanded(item.batch_key)}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                    >
                      {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      {expanded ? '收起' : '查看详情'}
                    </button>
                  ) : null}
                  {item.can_rollback ? (
                    <button
                      type="button"
                      onClick={() => setRollbackBatch(item)}
                      className="inline-flex items-center gap-1 border border-red-200 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      撤回本次更新
                    </button>
                  ) : item.is_latest_effective_batch && item.batch_category === 'business_update' ? (
                    <button
                      type="button"
                      disabled
                      title={item.rollback_block_reason || '当前不可撤回'}
                      className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-400"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      撤回本次更新
                    </button>
                  ) : item.rollback_block_reason ? (
                    <span className="max-w-48 text-right text-[11px] leading-4 text-gray-400" title={item.rollback_block_reason}>
                      {item.rollback_block_reason}
                    </span>
                  ) : null}
                </div>
              </div>

              {expanded ? <BatchDetails item={item} onOpenEvidence={(change) => setSelectedEvidence(evidenceSource(item, change))} /> : null}
            </article>
          );
        })}
      </div>

      {rollbackBatch ? (
        <RollbackDialog
          batch={rollbackBatch}
          loading={rollbackLoading}
          onCancel={() => setRollbackBatch(null)}
          onConfirm={() => void handleRollback()}
        />
      ) : null}
      {researchReport ? <ResearchReportDrawer report={researchReport} onClose={() => setResearchReport(null)} /> : null}
      {selectedEvidence ? (
        <ResearchEvidenceDrawer
          source={selectedEvidence}
          onClose={() => setSelectedEvidence(null)}
          onOpenReport={(jobId) => void openResearchReport(jobId)}
        />
      ) : null}
    </>
  );
}

function BatchDetails({ item, onOpenEvidence }: { item: UpdateBatch; onOpenEvidence: (change: UpdateBatchChange) => void }) {
  return (
    <div className="mt-4 border-t border-gray-100 pt-4">
      {item.raw_input ? (
        <div>
          <p className="text-xs font-medium text-gray-600">本次录入</p>
          <p className="mt-1 max-h-52 overflow-y-auto whitespace-pre-wrap bg-gray-50 px-3 py-2 text-sm leading-6 text-gray-700">
            {item.raw_input}
          </p>
        </div>
      ) : null}

      {item.changes.length > 0 ? (
        <div className={item.raw_input ? 'mt-4' : ''}>
          <p className="text-xs font-medium text-gray-600">本次最终写入</p>
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs text-gray-500">
                  <th className="w-40 px-3 py-2 font-medium">字段</th>
                  <th className="px-3 py-2 font-medium">原值</th>
                  <th className="px-3 py-2 font-medium">新值</th>
                  <th className="w-24 px-3 py-2 font-medium">来源</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {item.changes.map((change) => (
                  <tr key={change.log_id}>
                    <td className="px-3 py-2 text-gray-600">{fieldLabel(item.entity_type, change.field_path)}</td>
                    <td className="max-w-[320px] px-3 py-2 text-gray-500">{valueLabel(change.field_path, change.old_value)}</td>
                    <td className="max-w-[320px] px-3 py-2 text-gray-900">{valueLabel(change.field_path, change.new_value)}</td>
                    <td className="px-3 py-2">
                      {change.research_evidence ? (
                        <button
                          type="button"
                          onClick={() => onOpenEvidence(change)}
                          className="text-xs text-brand-700 hover:underline"
                        >
                          查看证据
                        </button>
                      ) : (
                        <span className="text-xs text-gray-300">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <FileText className="h-3.5 w-3.5" />
          本次没有结构化字段变化
        </div>
      )}
    </div>
  );
}

function evidenceSource(batch: UpdateBatch, change: UpdateBatchChange): FieldValueSource {
  return {
    id: change.log_id,
    entity_type: batch.entity_type,
    entity_id: batch.entity_id,
    field_path: change.field_path,
    value_snapshot_json: { value: change.new_value },
    source_type: 'research_proposal',
    source_label: change.research_evidence?.source_title || '公开调研',
    review_status: 'accepted',
    created_at: change.applied_at,
    created_by: null,
    created_by_name: null,
    research_evidence: change.research_evidence || null,
  };
}

function RollbackDialog({
  batch,
  loading,
  onCancel,
  onConfirm,
}: {
  batch: UpdateBatch;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const fieldNames = batch.changes.map((change) => fieldLabel(batch.entity_type, change.field_path));
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4">
      <div className="w-full max-w-lg border border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="text-base font-semibold text-gray-900">撤回最近一次更新</h2>
          <button type="button" onClick={onCancel} disabled={loading} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4 text-sm text-gray-700">
          <p>
            将撤回 {formatDateTime(batch.submitted_at)} 由“{batch.operator_name}”录入的更新。
          </p>
          <div className="bg-gray-50 px-3 py-2">
            <p className="text-xs text-gray-500">以下 {fieldNames.length} 个字段将恢复到更新前：</p>
            <p className="mt-1 leading-6 text-gray-800">{fieldNames.join('、')}</p>
          </div>
          <p className="text-xs leading-5 text-gray-500">
            原始录入内容和附件会继续保留在更新记录中。撤回不会删除实体或附件。
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4">
          <button type="button" onClick={onCancel} disabled={loading} className="border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            取消
          </button>
          <button type="button" onClick={onConfirm} disabled={loading} className="inline-flex items-center gap-1.5 bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            确认撤回
          </button>
        </div>
      </div>
    </div>
  );
}

function BatchStatusBadge({ status, sourceType }: { status: string; sourceType: string }) {
  const config: Record<string, { label: string; className: string; spinning?: boolean }> = {
    parsing: { label: '解析中', className: 'bg-blue-50 text-blue-700', spinning: true },
    queued: { label: '排队中', className: 'bg-sky-50 text-sky-700', spinning: true },
    researching: { label: '调研中', className: 'bg-indigo-50 text-indigo-700', spinning: true },
    mapping: { label: '整理结果中', className: 'bg-violet-50 text-violet-700', spinning: true },
    failed: { label: '解析失败', className: 'bg-red-50 text-red-700' },
    applied: { label: '已写入', className: 'bg-emerald-50 text-emerald-700' },
    rolled_back: { label: '已撤回', className: 'bg-gray-100 text-gray-600' },
  };
  const item = sourceType === 'research_proposal' && status === 'applied'
    ? { label: '调研完成', className: 'bg-emerald-50 text-emerald-700' }
    : sourceType === 'research_proposal' && status === 'failed'
      ? { label: '调研失败', className: 'bg-red-50 text-red-700' }
      : config[status] || { label: status, className: 'bg-gray-100 text-gray-600' };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium ${item.className}`}>
      {item.spinning ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
      {item.label}
    </span>
  );
}

function batchSourceLabel(batch: UpdateBatch): string {
  if (batch.source_type === 'business_update') {
    if (batch.attachments.length > 0 && batch.raw_input) return '文字 + 附件';
    if (batch.attachments.length > 0) return '附件更新';
    return '文字更新';
  }
  return sourceTypeLabel(batch.source_type);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}
