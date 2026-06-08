import { useEffect, useState } from 'react';
import { AlertCircle, FileText, Image, Loader2, Upload, X } from 'lucide-react';
import { attachments, businessUpdates } from '../lib/api';
import type { AttachmentUploadPolicy } from '../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess?: (id: string) => void;
  defaultTargetId?: string;
  defaultTargetName?: string;
  defaultBuyerPartyId?: string;
  defaultBuyerPartyName?: string;
  defaultIntentId?: string;
  defaultIntentName?: string;
}

export default function BusinessUpdateDrawer({
  open,
  onClose,
  onSuccess,
  defaultTargetId,
  defaultTargetName,
  defaultBuyerPartyId,
  defaultBuyerPartyName,
  defaultIntentId,
  defaultIntentName,
}: Props) {
  const [rawText, setRawText] = useState('');
  const [boundTargetIds, setBoundTargetIds] = useState<string[]>([]);
  const [boundBuyerPartyIds, setBoundBuyerPartyIds] = useState<string[]>([]);
  const [boundIntentIds, setBoundIntentIds] = useState<string[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setRawText('');
    setBoundTargetIds(defaultTargetId ? [defaultTargetId] : []);
    setBoundBuyerPartyIds(defaultBuyerPartyId ? [defaultBuyerPartyId] : []);
    setBoundIntentIds(defaultIntentId ? [defaultIntentId] : []);
    setError(null);
  }, [defaultBuyerPartyId, defaultIntentId, defaultTargetId, open]);

  useEffect(() => {
    if (!open || uploadPolicy) return;
    let cancelled = false;
    setPolicyLoading(true);
    setPolicyError(null);
    attachments
      .uploadPolicy()
      .then((policy) => {
        if (!cancelled) setUploadPolicy(policy);
      })
      .catch((err) => {
        if (!cancelled) setPolicyError(err instanceof Error ? err.message : '读取上传规则失败');
      })
      .finally(() => {
        if (!cancelled) setPolicyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, uploadPolicy]);

  if (!open) return null;

  async function handleSubmit() {
    if (!rawText.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await businessUpdates.create({
        raw_text: rawText.trim(),
        input_type: 'text',
        bound_seller_target_ids: boundTargetIds.length > 0 ? boundTargetIds : undefined,
        bound_buyer_party_ids: boundBuyerPartyIds.length > 0 ? boundBuyerPartyIds : undefined,
        bound_buyer_intent_ids: boundIntentIds.length > 0 ? boundIntentIds : undefined,
      });
      await businessUpdates.process(result.id);
      setRawText('');
      setBoundTargetIds([]);
      setBoundBuyerPartyIds([]);
      setBoundIntentIds([]);
      onSuccess?.(result.id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 bottom-0 w-full max-w-[520px] bg-white z-50 shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-base font-semibold text-gray-900">录入业务更新</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              提交后自动进入 AI 拆解，结果会进入复核工作台。
            </p>
          </div>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">上下文</label>
            <div className="space-y-2 border border-gray-100 bg-gray-50 px-3 py-2.5">
              <ContextRow label="标的" value={defaultTargetName || '未选择'} muted={!defaultTargetName} />
              <ContextRow
                label="买方"
                value={defaultBuyerPartyName || '未选择'}
                muted={!defaultBuyerPartyName}
              />
              <ContextRow label="意向" value={defaultIntentName || '未选择'} muted={!defaultIntentName} />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">更新内容</label>
            <textarea
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              placeholder="粘贴聊天记录、会议纪要、截图说明或业务进展。例如：5月28日已推荐给广州，对方希望先看财务资料。"
              rows={9}
              className="w-full px-3 py-2.5 text-sm border border-gray-200 focus:outline-none focus:border-brand-500 placeholder:text-gray-400 resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">附件/截图</label>
            <div className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-600">
              <div className="flex items-center gap-2 text-gray-800 font-medium">
                <Upload className="w-4 h-4 text-brand-600" />
                文件上传入口即将接入，当前先展示后端支持策略
              </div>
              <UploadPolicyCard policy={uploadPolicy} loading={policyLoading} error={policyError} />
            </div>
          </div>

          {error && (
            <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={!rawText.trim() || submitting}
            className="px-4 py-2 text-sm font-medium bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {submitting ? '提交并解析中...' : '提交并自动解析'}
          </button>
        </div>
      </div>
    </>
  );
}

function UploadPolicyCard({
  policy,
  loading,
  error,
}: {
  policy: AttachmentUploadPolicy | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        正在读取上传规则...
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-3 flex items-start gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
        <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>{error}</span>
      </div>
    );
  }

  if (!policy) {
    return <p className="mt-3 text-xs text-gray-400">上传规则暂不可用。</p>;
  }

  const image = policy.image_policy.constraints;
  const pdf = policy.pdf_policy.text_detection;
  const doc2xStatus = policy.pdf_policy.scanned_pdf.doc2x_configured ? '已配置' : '未配置';

  return (
    <div className="mt-3 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <PolicyStat label="单文件上限" value={`${policy.max_upload_mb} MB`} />
        <PolicyStat label="图片数量" value={`${image.max_count_per_business_update} 张/次`} />
      </div>

      <div className="grid grid-cols-1 gap-2 text-xs">
        <PolicyLine
          icon={Image}
          title="截图 / 图片"
          body={`支持 ${image.supported_types.join('、')}；不走 OCR，直接交给多模态模型；会压缩到最长边 ${image.model_preprocess_max_side_px}px。`}
        />
        <PolicyLine
          icon={FileText}
          title="PDF"
          body={`前 ${pdf.sample_page_limit} 页累计文本不少于 ${pdf.min_total_chars_for_text_pdf} 字按文本 PDF 本地解析；扫描件走 Doc2X 异步 OCR（${doc2xStatus}）。`}
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {policy.supported_uploads.text_extensions.slice(0, 8).map((item) => (
          <span key={item} className="bg-white border border-gray-200 px-1.5 py-0.5 text-[11px] text-gray-500">
            {item}
          </span>
        ))}
        <span className="bg-white border border-gray-200 px-1.5 py-0.5 text-[11px] text-gray-500">pdf</span>
        <span className="bg-white border border-gray-200 px-1.5 py-0.5 text-[11px] text-gray-500">docx/xlsx/pptx</span>
      </div>
    </div>
  );
}

function PolicyStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border border-gray-200 px-3 py-2">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function PolicyLine({
  icon: Icon,
  title,
  body,
}: {
  icon: typeof Image;
  title: string;
  body: string;
}) {
  return (
    <div className="flex gap-2 bg-white border border-gray-200 px-3 py-2">
      <Icon className="w-3.5 h-3.5 text-brand-600 mt-0.5 shrink-0" />
      <div>
        <p className="font-medium text-gray-800">{title}</p>
        <p className="mt-0.5 text-gray-500 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}

function ContextRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-20 shrink-0 text-gray-500">{label}：</span>
      <span className={muted ? 'text-gray-400' : 'text-gray-900'}>{value}</span>
    </div>
  );
}
