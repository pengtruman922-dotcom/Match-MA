import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, Paperclip, X } from 'lucide-react';
import { attachments, buyerParties } from '../../lib/api';
import type { AttachmentUploadPolicy, BuyerParty, BuyerPartyIngestStatus } from '../../types/api';
import { SelectedFiles } from '../../components/UploadArea';

/**
 * 「AI 补全买家信息」的触发弹窗。
 *
 * 两条刻意的行为：
 * 1. **勾选框默认不勾**（用户 0825 决定）—— 联网调研要 5–10 分钟且要花钱。
 *    但没有材料时它默认勾上且不可取消：否则这次点击必然什么都产不出。
 * 2. 点「开始」**立即关闭返回**。调研可能跑十分钟，不能让人干等。
 */
export default function BuyerPartyIngestDialog({
  party,
  status,
  onClose,
  onStarted,
}: {
  party: BuyerParty;
  status: BuyerPartyIngestStatus | null;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [rawText, setRawText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [enableResearch, setEnableResearch] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    attachments.uploadPolicy().then(setPolicy).catch(() => {});
  }, []);

  const hasMaterial = rawText.trim().length > 0 || files.length > 0;
  // 没有材料时联网是唯一的信息来源，所以锁上勾选框而不是让人提交一个空跑。
  const researchForced = !hasMaterial;
  const researchChecked = researchForced || enableResearch;
  const imageLimit = policy?.image_policy.constraints.max_count_per_business_update ?? 5;
  const nodesReady = status?.nodes_ready;
  const missingNodes = nodesReady
    ? [
        !nodesReady.parser && hasMaterial ? '买家主体解析' : null,
        !nodesReady.researcher && researchChecked ? '买家主体 AI 调研' : null,
        // 归一节点只在「材料 + 联网」两个来源都有时才被调用（它的活是调和冲突）。
        !nodesReady.normalizer && hasMaterial && researchChecked ? '买家主体信息规范化' : null,
      ].filter(Boolean)
    : [];
  const searchMissing = researchChecked && status ? !status.search_provider_ready : false;

  const addFiles = (incoming: File[]) => {
    if (!incoming.length) return;
    const maxFiles = policy?.max_files_per_business_update || 10;
    const maxBytes = policy?.max_upload_bytes || 25 * 1024 * 1024;
    const tooLarge = incoming.find((file) => file.size > maxBytes);
    if (tooLarge) {
      setFileError(`「${tooLarge.name}」超过单文件上限。`);
      return;
    }
    const next = [...files, ...incoming].slice(0, maxFiles);
    if (next.length < files.length + incoming.length) setFileError(`一次最多上传 ${maxFiles} 个文件。`);
    else setFileError(null);
    setFiles(next);
  };

  const submit = async () => {
    if (!hasMaterial && !researchChecked) {
      setError('请粘贴材料、上传附件，或勾选「联网补全」。');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      let attachmentIds: string[] = [];
      if (files.length) {
        attachmentIds = (await buyerParties.uploadMaterials(party.id, files)).attachment_ids;
      }
      await buyerParties.parse(party.id, {
        raw_text: rawText.trim() || null,
        attachment_ids: attachmentIds,
        enable_research: researchChecked,
        mode: 'fill',
      });
      // 立即返回：后面的事在后台跑，进度显示在信息页上。
      onStarted();
      onClose();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '发起失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4">
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto border border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">AI 补全买家信息</h2>
            <p className="mt-1 text-xs text-gray-500">补全的是「{party.buyer_name}」这家买家自己的资料，不是它的收购需求。</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">粘贴材料（年报节选、跟进记录、公开报道…）</span>
            <textarea
              className="input min-h-40 resize-y"
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              placeholder="材料里如果带着「解析要求：……」这类历史模板文字，直接一起粘进来就行，系统会当噪音忽略。"
            />
          </label>

          <div
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              addFiles(Array.from(event.dataTransfer.files || []));
            }}
            className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-center"
          >
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="inline-flex items-center gap-1.5 border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700"
            >
              <Paperclip className="h-3.5 w-3.5" />
              选择文件
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              onChange={(event) => addFiles(Array.from(event.target.files || []))}
            />
            <p className="mt-2 text-xs text-gray-500">也可以直接拖进来：PDF / Word / Excel / 图片</p>
            {/* 静默截断是这条链最容易骗人的地方，所以上限写在点击之前。 */}
            <p className="mt-1 text-xs text-amber-700">
              扫描版 PDF 会自动 OCR；但<strong>拍照的图片单次最多 {imageLimit} 张</strong>，超出的不会进入解析，
              而且不会报错。年报这类多页材料请传 PDF。
            </p>
            {fileError ? <p className="mt-2 text-xs text-red-600">{fileError}</p> : null}
            <SelectedFiles files={files} onRemove={(index) => setFiles(files.filter((_, item) => item !== index))} />
          </div>

          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              checked={researchChecked}
              disabled={researchForced}
              onChange={(event) => setEnableResearch(event.target.checked)}
            />
            <span>
              联网补全材料里没有的信息（约需 5–10 分钟）
              {researchForced ? (
                <span className="ml-1 text-xs text-amber-700">没有材料时这是唯一的信息来源，已自动勾选。</span>
              ) : null}
            </span>
          </label>

          {missingNodes.length ? (
            <p className="flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              还没有配置这些 AI 节点：{missingNodes.join('、')}。请先在设置页创建对应的 Prompt。
            </p>
          ) : null}
          {searchMissing ? (
            <p className="flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              还没有配置联网搜索供应商，勾选联网补全会被拒绝。
            </p>
          ) : null}
          {error ? <p className="text-xs text-red-600">{error}</p> : null}
        </div>

        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4">
          <button type="button" onClick={onClose} className="border border-gray-200 px-4 py-2 text-sm text-gray-700">
            取消
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting}
            className="inline-flex items-center gap-2 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            开始
          </button>
        </div>
      </div>
    </div>
  );
}
