import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Loader2, Paperclip, Send } from 'lucide-react';

export type RecommendMode = 'buyer_to_target' | 'target_to_buyer';

export const AGENT_INPUT_MAX_CHARS = 20000;

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
  onPickFile,
  fileBusy,
  fileName,
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
  onPickFile: (file: File) => void;
  fileBusy: boolean;
  fileName: string | null;
  onNewConversation: () => void;
  /** 从买家需求列表点进来时带的原文。只填一次，之后用户完全接管这个框。 */
  prefill?: string | null;
}) {
  const [value, setValue] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const prefilledRef = useRef(false);

  useEffect(() => {
    if (!prefill || prefilledRef.current) return;
    prefilledRef.current = true;
    setValue(prefill.slice(0, AGENT_INPUT_MAX_CHARS));
  }, [prefill]);

  const submit = () => {
    const message = value.trim();
    if (!message || busy) return;
    setValue('');
    onSubmit(message);
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) onPickFile(file);
  };

  return (
    <div className="border border-gray-200 bg-white focus-within:border-brand-500">
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

      <div className="flex items-center justify-between gap-2 px-3 pb-2">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={fileBusy}
            className="inline-flex items-center gap-1 border border-gray-200 px-2 py-1 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40"
          >
            {fileBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Paperclip className="h-3 w-3" />}
            需求文件
          </button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={handleFile}
            accept=".pdf,.doc,.docx,.txt,.md,.png,.jpg,.jpeg,.xlsx,.xls"
          />
          {fileBusy && <span>正在读取文件正文…</span>}
          {!fileBusy && fileName && <span>已读取 {fileName}</span>}
          {value.length > AGENT_INPUT_MAX_CHARS - 2000 && (
            <span className="text-amber-600">{value.length} / {AGENT_INPUT_MAX_CHARS} 字</span>
          )}
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={!value.trim() || busy}
          className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-40"
          data-testid="agent-send"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          发送
        </button>
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
