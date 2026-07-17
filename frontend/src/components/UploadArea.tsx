import { AlertCircle, FileText, Image, Loader2, Paperclip } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AttachmentUploadPolicy } from '../types/api';
import { formatBytes } from '../lib/format';

export function UploadPolicyCard({
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

  if (error) return <InlineWarning message={error} />;
  if (!policy) return <p className="mt-3 text-xs text-gray-400">上传规则暂不可用。</p>;

  const image = policy.image_policy.constraints;
  const pdf = policy.pdf_policy.text_detection;
  const doc2xStatus = policy.pdf_policy.scanned_pdf.doc2x_configured ? '已配置' : '未配置';

  return (
    <div className="mt-3 space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <PolicyStat label="单文件上限" value={`${policy.max_upload_mb} MB`} />
        <PolicyStat label="附件数量" value={`${policy.max_files_per_business_update} 个/次`} />
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
    </div>
  );
}

export function SelectedFiles({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  if (!files.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {files.map((file, index) => (
        <div key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center justify-between gap-3 bg-white border border-gray-200 px-3 py-2">
          <div className="min-w-0 flex items-center gap-2">
            <Paperclip className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-gray-800">{file.name}</p>
              <p className="text-[11px] text-gray-400">{formatBytes(file.size)}</p>
            </div>
          </div>
          <button type="button" onClick={() => onRemove(index)} className="shrink-0 text-xs text-gray-400 hover:text-red-600">
            移除
          </button>
        </div>
      ))}
    </div>
  );
}

export function InlineWarning({ message }: { message: string }) {
  return (
    <div className="mt-3 flex items-start gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <span>{message}</span>
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

function PolicyLine({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) {
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
