import { useEffect, useState } from 'react';
import { Loader2, Upload, X } from 'lucide-react';
import { businessUpdates } from '../lib/api';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess?: (id: string) => void;
  defaultTargetId?: string;
  defaultTargetName?: string;
  defaultIntentId?: string;
  defaultIntentName?: string;
}

export default function BusinessUpdateDrawer({
  open,
  onClose,
  onSuccess,
  defaultTargetId,
  defaultTargetName,
  defaultIntentId,
  defaultIntentName,
}: Props) {
  const [rawText, setRawText] = useState('');
  const [boundTargetIds, setBoundTargetIds] = useState<string[]>([]);
  const [boundIntentIds, setBoundIntentIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setBoundTargetIds(defaultTargetId ? [defaultTargetId] : []);
    setBoundIntentIds(defaultIntentId ? [defaultIntentId] : []);
    setError(null);
  }, [defaultIntentId, defaultTargetId, open]);

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
        bound_buyer_intent_ids: boundIntentIds.length > 0 ? boundIntentIds : undefined,
      });
      await businessUpdates.process(result.id);
      setRawText('');
      setBoundTargetIds([]);
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
            <p className="mt-0.5 text-xs text-gray-500">提交后自动进入 AI 拆解，结果会进入复核工作台。</p>
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
              <ContextRow label="买家/意向" value={defaultIntentName || '未选择'} muted={!defaultIntentName} />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">更新内容</label>
            <textarea
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              placeholder="粘贴聊天记录、会议纪要、截图说明或业务进展。例如：5月28日已推荐给广工，对方希望先看财务资料。"
              rows={9}
              className="w-full px-3 py-2.5 text-sm border border-gray-200 focus:outline-none focus:border-brand-500 placeholder:text-gray-400 resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">附件/截图</label>
            <div className="border border-dashed border-gray-300 px-4 py-6 text-center text-sm text-gray-400">
              <Upload className="w-5 h-5 mx-auto mb-1.5 text-gray-300" />
              附件上传、OCR 和解析任务已预留 Worker，前端入口后续接入。
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

function ContextRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-20 shrink-0 text-gray-500">{label}：</span>
      <span className={muted ? 'text-gray-400' : 'text-gray-900'}>{value}</span>
    </div>
  );
}
