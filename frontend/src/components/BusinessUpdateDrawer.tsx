import { ChangeEvent, DragEvent, useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Loader2, Paperclip, Sparkles, Upload, X } from 'lucide-react';
import { attachments, businessUpdates, relations } from '../lib/api';
import type {
  AttachmentUploadPolicy,
  BusinessUpdateProcessingScope,
  BuyerSellerRelation,
  RelationEventType,
  RelationFollowUpDraft,
} from '../types/api';
import { relationStatusLabel } from '../features/relations/relationLabels';
import { updateScopeLabel } from './updateEntryLabels';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess?: (businessUpdateId: string) => void;
  initialScope?: BusinessUpdateProcessingScope;
  defaultRelationId?: string;
  defaultTargetId?: string;
  defaultTargetName?: string;
  defaultBuyerPartyId?: string;
  defaultBuyerPartyName?: string;
  defaultIntentId?: string;
  defaultIntentName?: string;
}

const STATUS_SYSTEM_EVENT_TYPES = new Set([
  'recommended', 'buyer_interested', 'buyer_not_interested', 'due_diligence_started',
  'agreement_discussion', 'deal_closed', 'paused',
]);

const DRAFT_POLL_INTERVAL_MS = 1800;
const DRAFT_POLL_LIMIT = 70;

export default function BusinessUpdateDrawer({
  open,
  onClose,
  onSuccess,
  initialScope = 'basic_info',
  defaultRelationId,
  defaultTargetId,
  defaultTargetName,
  defaultBuyerPartyId,
  defaultBuyerPartyName,
  defaultIntentId,
  defaultIntentName,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollGenerationRef = useRef(0);
  const [scope, setScope] = useState<BusinessUpdateProcessingScope>(initialScope);
  const [rawText, setRawText] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [relationItems, setRelationItems] = useState<BuyerSellerRelation[]>([]);
  const [relationLoading, setRelationLoading] = useState(false);
  const [relationError, setRelationError] = useState<string | null>(null);
  const [selectedRelationId, setSelectedRelationId] = useState('');
  const [eventTypes, setEventTypes] = useState<RelationEventType[]>([]);
  const [eventType, setEventType] = useState('meeting');
  const [businessUpdateId, setBusinessUpdateId] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<'input' | 'waiting' | 'timeout' | 'failed' | 'ready'>('input');
  const [draftContent, setDraftContent] = useState('');
  const [draftNextStep, setDraftNextStep] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsFollowUp = scope === 'follow_up' || scope === 'both';
  const selectedRelation = relationItems.find((item) => item.id === selectedRelationId) || null;
  const manualEventTypes = eventTypes.filter((item) => !STATUS_SYSTEM_EVENT_TYPES.has(item.value));

  const reset = useCallback(() => {
    pollGenerationRef.current += 1;
    setScope(initialScope);
    setRawText('');
    setSelectedFiles([]);
    setFileError(null);
    setRelationItems([]);
    setRelationError(null);
    setSelectedRelationId(defaultRelationId || '');
    setBusinessUpdateId(null);
    setDraftStatus('input');
    setDraftContent('');
    setDraftNextStep('');
    setSubmitting(false);
    setRecording(false);
    setError(null);
  }, [defaultRelationId, initialScope]);

  useEffect(() => {
    if (!open) return;
    reset();
  }, [open, reset]);

  useEffect(() => {
    if (!open || uploadPolicy) return;
    attachments.uploadPolicy().then(setUploadPolicy).catch((err) => {
      setPolicyError(err instanceof Error ? err.message : '读取上传规则失败');
    });
  }, [open, uploadPolicy]);

  useEffect(() => {
    if (!open || !needsFollowUp) return;
    let cancelled = false;
    setRelationLoading(true);
    setRelationError(null);
    const params = defaultTargetId
      ? { seller_target_id: defaultTargetId, limit: 100 }
      : defaultIntentId
        ? { buyer_intent_id: defaultIntentId, limit: 100 }
        : null;
    if (!params) {
      setRelationLoading(false);
      setRelationError('记录跟进必须从标的或买家意向进入。');
      return;
    }
    Promise.all([relations.list(params), relations.meta()])
      .then(([items, meta]) => {
        if (cancelled) return;
        setRelationItems(items);
        setEventTypes(meta.event_types);
        const manual = meta.event_types.filter((item) => !STATUS_SYSTEM_EVENT_TYPES.has(item.value));
        setEventType(manual.some((item) => item.value === 'meeting') ? 'meeting' : manual[0]?.value || '');
        const preferred = defaultRelationId && items.some((item) => item.id === defaultRelationId)
          ? defaultRelationId
          : items.length === 1
            ? items[0].id
            : '';
        setSelectedRelationId(preferred);
      })
      .catch((err) => {
        if (!cancelled) setRelationError(err instanceof Error ? err.message : '读取推进关系失败');
      })
      .finally(() => {
        if (!cancelled) setRelationLoading(false);
      });
    return () => { cancelled = true; };
  }, [defaultIntentId, defaultRelationId, defaultTargetId, needsFollowUp, open]);

  if (!open) return null;

  const requestClose = () => {
    if (submitting || recording || draftStatus === 'waiting') return;
    if (draftStatus === 'ready' && !window.confirm('AI 草稿尚未记录为推进动态，确认关闭？')) return;
    pollGenerationRef.current += 1;
    onClose();
  };

  const addFiles = (incoming: File[]) => {
    const next = [...selectedFiles];
    const maxFiles = uploadPolicy?.max_files_per_business_update || 10;
    const maxBytes = uploadPolicy?.max_upload_bytes || 25 * 1024 * 1024;
    for (const file of incoming) {
      if (next.length >= maxFiles) {
        setFileError(`单次最多上传 ${maxFiles} 个附件。`);
        break;
      }
      if (file.size > maxBytes) {
        setFileError(`${file.name} 超过 ${formatBytes(maxBytes)}。`);
        continue;
      }
      if (!next.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) {
        next.push(file);
      }
    }
    setSelectedFiles(next);
  };

  const pollDraft = async (id: string) => {
    const generation = pollGenerationRef.current + 1;
    pollGenerationRef.current = generation;
    setDraftStatus('waiting');
    setError(null);
    for (let attempt = 0; attempt < DRAFT_POLL_LIMIT; attempt += 1) {
      if (attempt > 0) await delay(DRAFT_POLL_INTERVAL_MS);
      if (pollGenerationRef.current !== generation) return;
      try {
        const update = await businessUpdates.get(id);
        const metadata = update.metadata_json || {};
        const status = typeof metadata.followup_draft_status === 'string' ? metadata.followup_draft_status : 'pending';
        if (status === 'succeeded') {
          const draft = relationDraft(metadata.followup_draft);
          if (!draft) throw new Error('AI 已返回结果，但草稿格式无效。');
          setDraftContent(draft.content);
          setDraftNextStep(draft.next_step || '');
          setDraftStatus('ready');
          return;
        }
        if (status === 'failed') {
          setDraftStatus('failed');
          setError(typeof metadata.followup_draft_error === 'string' ? metadata.followup_draft_error : 'AI 整理失败，请重试。');
          return;
        }
      } catch (err) {
        setDraftStatus('timeout');
        setError(err instanceof Error ? `暂时无法读取 AI 草稿：${err.message}` : '暂时无法读取 AI 草稿。');
        return;
      }
    }
    setDraftStatus('timeout');
    setError('AI 整理等待超时，后台任务可能仍在运行。请继续等待，不要重复启动任务。');
  };

  const continueWaiting = async () => {
    if (!businessUpdateId) return;
    await pollDraft(businessUpdateId);
  };

  const submit = async () => {
    if (!rawText.trim() && selectedFiles.length === 0) return;
    if (needsFollowUp && !selectedRelationId) {
      setError('请先选择一条推进关系。');
      return;
    }
    if (needsFollowUp && !eventType) {
      setError('请选择动态类型。');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const submittedText = rawText.trim() || (needsFollowUp
        ? '请根据本次上传的附件整理沟通内容和下一步。'
        : '请根据本次上传的附件提取并更新基本信息。');
      let id: string;
      if (selectedFiles.length > 0) {
        const formData = new FormData();
        formData.set('raw_text', submittedText);
        formData.set('input_type', 'mixed');
        formData.set('auto_process', 'true');
        formData.set('process_after_ocr', 'true');
        formData.set('include_attachment_text', 'true');
        formData.set('processing_scope', scope);
        if (selectedRelationId) formData.set('bound_relation_id', selectedRelationId);
        if (defaultTargetId) formData.set('bound_seller_target_ids', JSON.stringify([defaultTargetId]));
        if (defaultBuyerPartyId) formData.set('bound_buyer_party_ids', JSON.stringify([defaultBuyerPartyId]));
        if (defaultIntentId) formData.set('bound_buyer_intent_ids', JSON.stringify([defaultIntentId]));
        formData.set('metadata_json', JSON.stringify({ source: 'frontend_unified_update_drawer' }));
        selectedFiles.forEach((file) => formData.append('files', file));
        const result = await businessUpdates.upload(formData);
        id = result.business_update.id;
      } else {
        const result = await businessUpdates.create({
          raw_text: submittedText,
          input_type: 'text',
          bound_seller_target_ids: defaultTargetId ? [defaultTargetId] : undefined,
          bound_buyer_party_ids: defaultBuyerPartyId ? [defaultBuyerPartyId] : undefined,
          bound_buyer_intent_ids: defaultIntentId ? [defaultIntentId] : undefined,
          processing_scope: scope,
          bound_relation_id: selectedRelationId || undefined,
          metadata_json: { source: 'frontend_unified_update_drawer' },
        });
        await businessUpdates.process(result.id);
        id = result.id;
      }
      setBusinessUpdateId(id);
      onSuccess?.(id);
      if (needsFollowUp) {
        await pollDraft(id);
      } else {
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const retryDraft = async () => {
    if (!businessUpdateId) return;
    setSubmitting(true);
    setError(null);
    try {
      await businessUpdates.process(businessUpdateId, { branch: 'follow_up' });
      await pollDraft(businessUpdateId);
    } catch (err) {
      setDraftStatus('failed');
      setError(err instanceof Error ? err.message : '重试失败');
    } finally {
      setSubmitting(false);
    }
  };

  const recordDraft = async () => {
    if (!businessUpdateId || !selectedRelationId || !eventType || !draftContent.trim()) return;
    setRecording(true);
    setError(null);
    try {
      await relations.createEvent(selectedRelationId, {
        event_type: eventType,
        content: draftContent.trim(),
        next_step: draftNextStep.trim() || null,
      });
      onSuccess?.(businessUpdateId);
      pollGenerationRef.current += 1;
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '记录推进动态失败');
    } finally {
      setRecording(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-[90] bg-black/30" onClick={requestClose} />
      <div className="fixed inset-y-0 right-0 z-[91] flex w-full max-w-[600px] flex-col bg-white shadow-xl">
        <header className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-gray-900">{updateScopeLabel(scope)}</h2>
              <span className="bg-brand-50 px-2 py-0.5 text-[11px] text-brand-700">{scope === 'both' ? '双节点独立处理' : '固定处理路径'}</span>
            </div>
            <p className="mt-1 text-xs text-gray-500">AI 只整理草稿；关系、状态和动态类型由你决定。</p>
          </div>
          <button type="button" onClick={requestClose} disabled={submitting || recording || draftStatus === 'waiting'} className="p-1 text-gray-400 hover:text-gray-700 disabled:opacity-40"><X className="h-5 w-5" /></button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <section>
            <label className="mb-2 block text-sm font-medium text-gray-700">当前对象</label>
            <div className="space-y-1 border border-gray-100 bg-gray-50 px-3 py-2.5 text-sm">
              {defaultTargetName ? <ContextRow label="标的" value={defaultTargetName} /> : null}
              {defaultIntentName ? <ContextRow label="买家意向" value={defaultIntentName} /> : null}
              {!defaultIntentName && defaultBuyerPartyName ? <ContextRow label="买家" value={defaultBuyerPartyName} /> : null}
            </div>
          </section>

          {needsFollowUp ? (
            <section className="space-y-4 border border-brand-100 bg-brand-50/30 p-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">推进关系 *</label>
                {relationLoading ? <LoadingText text="正在读取推进关系" /> : relationError ? <ErrorText text={relationError} /> : relationItems.length === 0 ? (
                  <ErrorText text="当前对象还没有推进关系。请先在「推进」页关联对手方，再记录跟进。" />
                ) : (
                  <select value={selectedRelationId} onChange={(event) => setSelectedRelationId(event.target.value)} disabled={draftStatus !== 'input'} className="w-full border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 outline-none focus:border-brand-500 disabled:bg-gray-100">
                    <option value="">请选择推进关系</option>
                    {relationItems.map((item) => <option key={item.id} value={item.id}>{relationLabel(item, Boolean(defaultTargetId))}</option>)}
                  </select>
                )}
                {selectedRelation ? <p className="mt-1.5 text-xs text-gray-500">当前状态：{relationStatusLabel(selectedRelation.status)}；AI 不会修改状态。</p> : null}
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">动态类型 *</label>
                <select value={eventType} onChange={(event) => setEventType(event.target.value)} disabled={draftStatus !== 'input'} className="w-full border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 outline-none focus:border-brand-500 disabled:bg-gray-100">
                  {manualEventTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </div>
            </section>
          ) : null}

          {draftStatus === 'input' ? (
            <>
              <section>
                <label className="mb-2 block text-sm font-medium text-gray-700">原始材料</label>
                <textarea value={rawText} onChange={(event) => setRawText(event.target.value)} rows={8} placeholder={needsFollowUp ? '粘贴聊天记录、会议速记或沟通纪要。AI 将只整理“沟通内容”和“下一步”。' : '粘贴企业资料、需求变化或补充事实。基础信息节点不会再解析沟通过程。'} className="w-full resize-y border border-gray-200 px-3 py-2.5 text-sm text-gray-800 outline-none placeholder:text-gray-400 focus:border-brand-500" />
              </section>
              <section>
                <label className="mb-2 block text-sm font-medium text-gray-700">附件 / 截图</label>
                <div onDragOver={(event) => event.preventDefault()} onDrop={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); addFiles(Array.from(event.dataTransfer.files || [])); }} className="border border-dashed border-gray-300 bg-gray-50 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="flex items-center gap-2 text-sm text-gray-600"><Upload className="h-4 w-4 text-brand-600" />拖拽文件，或选择聊天截图、PDF、Office、文本附件</p>
                    <button type="button" onClick={() => fileInputRef.current?.click()} className="shrink-0 border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 hover:border-brand-400">选择文件</button>
                  </div>
                  <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(event: ChangeEvent<HTMLInputElement>) => { addFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
                  <p className="mt-2 text-xs text-gray-400">{uploadPolicy ? `单文件 ${uploadPolicy.max_upload_mb} MB，单次最多 ${uploadPolicy.max_files_per_business_update} 个` : policyError || '正在读取上传规则...'}</p>
                  <SelectedFiles files={selectedFiles} onRemove={(index) => setSelectedFiles((items) => items.filter((_, itemIndex) => itemIndex !== index))} />
                  {fileError ? <ErrorText text={fileError} /> : null}
                </div>
              </section>
            </>
          ) : null}

          {draftStatus === 'waiting' ? (
            <div className="border border-blue-200 bg-blue-50 px-4 py-5 text-sm text-blue-800"><p className="flex items-center gap-2 font-medium"><Loader2 className="h-4 w-4 animate-spin" />AI 正在整理跟进草稿</p><p className="mt-1 text-xs leading-5">{scope === 'both' ? '基础信息分支已独立启动；跟进分支失败不会回滚基础信息。' : '草稿不会自动写入时间线。'}</p></div>
          ) : null}

          {draftStatus === 'timeout' ? (
            <div className="border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-800"><p className="font-medium">暂未取得 AI 草稿</p><p className="mt-1 text-xs leading-5">这不等于任务失败；继续等待只读取现有任务，不会重复解析基础信息或跟进内容。</p></div>
          ) : null}

          {draftStatus === 'ready' ? (
            <section className="space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium text-emerald-700"><CheckCircle2 className="h-4 w-4" />AI 草稿已生成，请确认后记录</div>
              <label className="block"><span className="mb-1.5 block text-sm font-medium text-gray-700">沟通内容 *</span><textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} maxLength={4000} rows={8} className="w-full resize-y border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-brand-500" /><span className="mt-1 block text-right text-[11px] text-gray-400">{draftContent.length}/4000</span></label>
              <label className="block"><span className="mb-1.5 block text-sm font-medium text-gray-700">下一步</span><textarea value={draftNextStep} onChange={(event) => setDraftNextStep(event.target.value)} maxLength={1000} rows={3} className="w-full resize-y border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-brand-500" /><span className="mt-1 block text-right text-[11px] text-gray-400">{draftNextStep.length}/1000</span></label>
            </section>
          ) : null}

          {error ? <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{error}</div> : null}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-gray-200 px-6 py-4">
          <p className="text-xs text-gray-400">{scope === 'both' ? '一份材料，两条独立任务' : needsFollowUp ? 'AI 回填草稿后由你确认' : '只更新基本信息'}</p>
          <div className="flex items-center gap-3">
            <button type="button" onClick={requestClose} disabled={submitting || recording || draftStatus === 'waiting'} className="px-3 py-2 text-sm text-gray-600 disabled:opacity-40">取消</button>
            {draftStatus === 'timeout' ? <button type="button" onClick={() => void continueWaiting()} className="inline-flex items-center gap-1.5 border border-brand-500 px-4 py-2 text-sm font-medium text-brand-700"><Loader2 className="h-4 w-4" />继续等待</button> : null}
            {draftStatus === 'failed' ? <button type="button" onClick={() => void retryDraft()} disabled={submitting} className="inline-flex items-center gap-1.5 border border-brand-500 px-4 py-2 text-sm font-medium text-brand-700 disabled:opacity-50">{submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}仅重试跟进整理</button> : null}
            {draftStatus === 'input' ? <button type="button" onClick={() => void submit()} disabled={submitting || (!rawText.trim() && selectedFiles.length === 0) || (needsFollowUp && (!selectedRelationId || !eventType))} className="inline-flex items-center gap-1.5 bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">{submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{submitting ? '提交中...' : needsFollowUp ? '提交并 AI 整理' : '提交并解析'}</button> : null}
            {draftStatus === 'ready' ? <button type="button" onClick={() => void recordDraft()} disabled={recording || !draftContent.trim()} className="inline-flex items-center gap-1.5 bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">{recording ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{recording ? '记录中...' : '确认记录动态'}</button> : null}
          </div>
        </footer>
      </div>
    </>
  );
}

function relationLabel(item: BuyerSellerRelation, targetSide: boolean): string {
  const counterpart = targetSide
    ? [item.buyer_name, item.buyer_intent_name].filter(Boolean).join(' · ') || '未命名买家意向'
    : item.seller_target_name || '未命名标的';
  return `${counterpart}（${relationStatusLabel(item.status)}）`;
}

function relationDraft(value: unknown): RelationFollowUpDraft | null {
  if (!value || typeof value !== 'object') return null;
  const draft = value as Record<string, unknown>;
  if (typeof draft.content !== 'string' || !draft.content.trim()) return null;
  if (draft.next_step !== null && draft.next_step !== undefined && typeof draft.next_step !== 'string') return null;
  return { content: draft.content, next_step: typeof draft.next_step === 'string' ? draft.next_step : null };
}

function ContextRow({ label, value }: { label: string; value: string }) {
  return <div className="flex gap-2"><span className="w-20 shrink-0 text-gray-500">{label}：</span><span className="min-w-0 text-gray-900">{value}</span></div>;
}

function SelectedFiles({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  if (!files.length) return null;
  return <div className="mt-3 space-y-2">{files.map((file, index) => <div key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center justify-between border border-gray-200 bg-white px-3 py-2"><span className="flex min-w-0 items-center gap-2"><Paperclip className="h-3.5 w-3.5 shrink-0 text-gray-400" /><span className="truncate text-xs text-gray-700">{file.name} · {formatBytes(file.size)}</span></span><button type="button" onClick={() => onRemove(index)} className="text-xs text-gray-400 hover:text-red-600">移除</button></div>)}</div>;
}

function ErrorText({ text }: { text: string }) { return <p className="mt-2 flex items-start gap-1.5 text-xs leading-5 text-amber-700"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{text}</p>; }
function LoadingText({ text }: { text: string }) { return <p className="flex items-center gap-2 py-2 text-xs text-gray-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />{text}</p>; }
function delay(ms: number) { return new Promise((resolve) => window.setTimeout(resolve, ms)); }
function formatBytes(value: number) { if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`; return `${value} B`; }
