import { useRef, useState } from 'react';
import type { ChangeEvent, ClipboardEvent, DragEvent, ReactNode } from 'react';
import {
  ClipboardList,
  FileText,
  Image as ImageIcon,
  Loader2,
  Paperclip,
  Send,
  Square,
  X,
} from 'lucide-react';

export type RecommendMode = 'buyer_to_target' | 'target_to_buyer';

export const AGENT_INPUT_MAX_CHARS = 20000;

export interface ComposerAttachment {
  key: string;
  name: string;
  /**
   * 文档读成正文、图片交给多模态模型、requirement 是带进来的已有买家需求。
   * 三者都不占用输入框 —— 那里只放用户自己要说的话。
   */
  kind: 'document' | 'image' | 'requirement';
  status: 'reading' | 'ready' | 'failed';
  error?: string;
  /** 有值时胶囊可点开只读预览：要发出去的东西，用户发之前得看得见。 */
  preview?: string;
}

const CHIP_ICONS = {
  image: ImageIcon,
  requirement: ClipboardList,
  document: FileText,
} as const;

function AttachmentChip({ item, onRemove }: { item: ComposerAttachment; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  const failed = item.status === 'failed';
  const Icon = CHIP_ICONS[item.kind];
  const expandable = Boolean(item.preview) && !failed;

  return (
    <span className="relative inline-flex max-w-full">
      <span
        className={`inline-flex max-w-full items-center gap-1.5 border px-2 py-1 text-xs ${
          failed ? 'border-red-200 bg-red-50 text-red-700' : 'border-gray-200 bg-gray-50 text-gray-600'
        }`}
      >
        {item.status === 'reading' ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
        ) : (
          <Icon className="h-3 w-3 shrink-0" />
        )}
        {expandable ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="truncate hover:text-brand-600 hover:underline"
            title="点开看要发出去的内容"
          >
            {item.name}
          </button>
        ) : (
          <span className="truncate">{item.name}</span>
        )}
        {item.status === 'reading' && <span className="shrink-0 text-gray-400">读取中</span>}
        {failed && <span className="shrink-0">{item.error || '读取失败'}</span>}
        <button
          type="button"
          onClick={onRemove}
          aria-label={`移除 ${item.name}`}
          className="shrink-0 text-gray-400 hover:text-red-600"
        >
          <X className="h-3 w-3" />
        </button>
      </span>
      {open && expandable && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute bottom-[calc(100%+6px)] left-0 z-40 w-[420px] max-w-[80vw] border border-gray-200 bg-white p-3 shadow-lg">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="truncate text-xs font-medium text-gray-700">{item.name}</span>
              <span className="shrink-0 text-[11px] text-gray-400">发送时随消息一起带上</span>
            </div>
            <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-600">
              {item.preview}
            </pre>
          </div>
        </>
      )}
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
  sourcePicker,
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
  /** 「从已有买家需求带入」入口，由页面按当前方向决定给谁。 */
  sourcePicker?: ReactNode;
}) {
  const [value, setValue] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 带了需求或附件时，光按发送也成立 —— 内容不在输入框里，但确实有东西要发。
  const hasPayload = attachments.some((item) => item.status === 'ready');
  const canSubmit = Boolean(value.trim() || hasPayload);

  const submit = () => {
    if (!canSubmit || busy) return;
    const message = value.trim();
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
          <span className="text-xs text-gray-500" data-testid="mode-locked">
            {mode === 'buyer_to_target' ? '为买家找标的' : '为标的找买家'} · 已锁定
          </span>
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
        {/* 带入入口跟着方向走，对话中途也在 —— 顾问随时可能想起来「就是那个买家」。 */}
        <div className="flex shrink-0 items-center gap-3">
          {sourcePicker}
          {locked && (
            <button
              type="button"
              onClick={onNewConversation}
              className="text-xs text-brand-600 hover:underline"
            >
              换方向 › 新对话
            </button>
          )}
        </div>
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
            disabled={!canSubmit}
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
