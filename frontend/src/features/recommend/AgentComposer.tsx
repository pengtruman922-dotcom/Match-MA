import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, ClipboardEvent, DragEvent } from 'react';
import { FileText, Image as ImageIcon, Loader2, Paperclip, Send, Square, X } from 'lucide-react';

export type RecommendMode = 'buyer_to_target' | 'target_to_buyer';

export const AGENT_INPUT_MAX_CHARS = 20000;

export interface ComposerAttachment {
  key: string;
  name: string;
  /** 文档读成正文进输入框；图片没有正文可读，原图交给多模态模型。 */
  kind: 'document' | 'image';
  status: 'reading' | 'ready' | 'failed';
  error?: string;
}

function AttachmentChip({ item, onRemove }: { item: ComposerAttachment; onRemove: () => void }) {
  const tone =
    item.status === 'failed'
      ? 'border-red-200 bg-red-50 text-red-700'
      : 'border-gray-200 bg-gray-50 text-gray-600';
  return (
    <span className={`inline-flex max-w-full items-center gap-1.5 border px-2 py-1 text-xs ${tone}`}>
      {item.status === 'reading' ? (
        <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
      ) : item.kind === 'image' ? (
        <ImageIcon className="h-3 w-3 shrink-0" />
      ) : (
        <FileText className="h-3 w-3 shrink-0" />
      )}
      <span className="truncate">{item.name}</span>
      {item.status === 'reading' && <span className="shrink-0 text-gray-400">读取中</span>}
      {item.status === 'failed' && <span className="shrink-0">{item.error || '读取失败'}</span>}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`移除 ${item.name}`}
        className="shrink-0 text-gray-400 hover:text-red-600"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

/**
 * The whole entry point: one box.
 *
 * The direction sits on top of the box rather than in a page toolbar because
 * it is a property of the conversation, not of the page — and once the first
 * message is sent it locks, since the two directions are different SQL and a
 * different agent. Changing it means a new conversation.
 */
export default function AgentComposer({
  mode,
  onModeChange,
  locked,
  busy,
  autoFocus,
  placeholder,
  onSubmit,
  onStop,
  stopping,
  onPickFile,
  attachments,
  onRemoveAttachment,
  accept,
  policyHint,
  onNewConversation,
  prefill,
}: {
  mode: RecommendMode;
  onModeChange: (mode: RecommendMode) => void;
  locked: boolean;
  busy: boolean;
  autoFocus?: boolean;
  placeholder: string;
  onSubmit: (message: string) => void;
  onStop: () => void;
  /** 停止请求已发出、还没落地。按钮此时不可再点。 */
  stopping: boolean;
  onPickFile: (file: File) => void;
  attachments: ComposerAttachment[];
  onRemoveAttachment: (key: string) => void;
  /** 由上传策略算出来，不在这里写死 —— 规则只有一份真源。 */
  accept: string;
  policyHint: string | null;
  onNewConversation: () => void;
  /** 从买家需求列表点进来时带的原文。只填一次，之后用户完全接管这个框。 */
  prefill?: string | null;
}) {
  const [value, setValue] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const prefilledRef = useRef<string | null>(null);

  // 每换一个需求就重填一次；同一个值不重复覆盖用户已经改过的内容。
  useEffect(() => {
    if (!prefill || prefill === prefilledRef.current) return;
    prefilledRef.current = prefill;
    setValue(prefill.slice(0, AGENT_INPUT_MAX_CHARS));
  }, [prefill]);

  const submit = () => {
    const message = value.trim();
    if (!message || busy) return;
    setValue('');
    onSubmit(message);
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    files.forEach(onPickFile);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    Array.from(event.dataTransfer.files || []).forEach(onPickFile);
  };

  /**
   * A pasted screenshot arrives as a file with no name, which would show up as
   * a blank chip — give it one so the user can tell two pastes apart.
   */
  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData?.files || []);
    if (!files.length) return;
    event.preventDefault();
    files.forEach((file, index) => {
      const named = file.name
        ? file
        : new File([file], `粘贴的图片${index + 1}.png`, { type: file.type || 'image/png' });
      onPickFile(named);
    });
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`border bg-white focus-within:border-brand-500 ${
        dragging ? 'border-brand-500 bg-brand-50/40' : 'border-gray-200'
      }`}
    >
      <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-3 py-1.5">
        {locked ? (
          <>
            <span className="text-xs text-gray-500" data-testid="mode-locked">
              {mode === 'buyer_to_target' ? '为买家找标的' : '为标的找买家'} · 已锁定
            </span>
            <button
              type="button"
              onClick={onNewConversation}
              className="text-xs text-brand-600 hover:underline"
            >
              换方向 › 新对话
            </button>
          </>
        ) : (
          <div className="flex items-center gap-4" role="radiogroup" aria-label="推荐方向">
            <ModeRadio
              checked={mode === 'buyer_to_target'}
              label="为买家找标的"
              onSelect={() => onModeChange('buyer_to_target')}
            />
            <ModeRadio
              checked={false}
              disabled
              label="为标的找买家"
              hint="下一轮支持"
              onSelect={() => undefined}
            />
          </div>
        )}
      </div>

      <textarea
        value={value}
        autoFocus={autoFocus}
        onChange={(event) => setValue(event.target.value.slice(0, AGENT_INPUT_MAX_CHARS))}
        onPaste={handlePaste}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        rows={3}
        placeholder={placeholder}
        className="w-full resize-y px-3 py-2.5 text-sm outline-none placeholder:text-gray-400"
        data-testid="agent-input"
      />

      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pb-2" data-testid="agent-attachments">
          {attachments.map((item) => (
            <AttachmentChip key={item.key} item={item} onRemove={() => onRemoveAttachment(item.key)} />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 px-3 pb-2">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title={policyHint || undefined}
            className="inline-flex items-center gap-1 border border-gray-200 px-2 py-1 hover:border-brand-500 hover:text-brand-600"
          >
            <Paperclip className="h-3 w-3" />
            需求文件
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFile}
            accept={accept}
          />
          <span className="hidden sm:inline">可拖入或直接粘贴</span>
          {value.length > AGENT_INPUT_MAX_CHARS - 2000 && (
            <span className="text-amber-600">{value.length} / {AGENT_INPUT_MAX_CHARS} 字</span>
          )}
        </div>
        {busy || stopping ? (
          <button
            type="button"
            onClick={onStop}
            disabled={stopping}
            className="inline-flex items-center gap-1.5 border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:border-gray-400 disabled:opacity-40"
            data-testid="agent-stop"
          >
            {stopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
            {stopping ? '正在停止' : '停止'}
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!value.trim()}
            className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-40"
            data-testid="agent-send"
          >
            <Send className="h-3.5 w-3.5" />
            发送
          </button>
        )}
      </div>
    </div>
  );
}

function ModeRadio({
  checked,
  label,
  hint,
  disabled,
  onSelect,
}: {
  checked: boolean;
  label: string;
  hint?: string;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      disabled={disabled}
      onClick={onSelect}
      title={hint}
      className={`inline-flex items-center gap-1.5 text-xs transition-colors ${
        disabled ? 'cursor-not-allowed text-gray-300' : checked ? 'text-brand-700' : 'text-gray-500 hover:text-brand-600'
      }`}
    >
      <span
        className={`inline-block h-3 w-3 rounded-full border ${
          checked ? 'border-[4px] border-brand-600' : 'border-gray-300'
        }`}
      />
      {label}
      {hint && <span className="text-gray-300">（{hint}）</span>}
    </button>
  );
}
