import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, FilePenLine, ListPlus, MessagesSquare } from 'lucide-react';
import type { BusinessUpdateProcessingScope } from '../types/api';

const OPTIONS: Array<{
  scope: BusinessUpdateProcessingScope;
  label: string;
  description: string;
  icon: typeof FilePenLine;
}> = [
  { scope: 'basic_info', label: '更新基本信息', description: '解析材料并更新当前实体字段', icon: FilePenLine },
  { scope: 'follow_up', label: '记录跟进', description: '选择推进关系，AI 整理沟通草稿', icon: MessagesSquare },
  { scope: 'both', label: '基本信息和跟进都更新', description: '同一份材料分别进入两个独立节点', icon: ListPlus },
];

interface Props {
  onSelect: (scope: BusinessUpdateProcessingScope) => void;
  primaryScope?: BusinessUpdateProcessingScope;
  compact?: boolean;
  className?: string;
}

export default function UpdateEntryMenu({ onSelect, primaryScope, compact = false, className = '' }: Props) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const primary = OPTIONS.find((item) => item.scope === primaryScope);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [open]);

  const toggle = () => {
    if (!open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      const width = 300;
      setPosition({
        top: rect.bottom + 6,
        left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)),
      });
    }
    setOpen((value) => !value);
  };

  const choose = (scope: BusinessUpdateProcessingScope) => {
    setOpen(false);
    onSelect(scope);
  };

  return (
    <>
      <div className={`inline-flex ${className}`}>
        {primary ? (
          <button
            type="button"
            onClick={() => choose(primary.scope)}
            className="inline-flex items-center gap-1.5 border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:border-brand-500 hover:text-brand-700"
          >
            <primary.icon className="h-3.5 w-3.5" />
            {primary.label}
          </button>
        ) : null}
        <button
          ref={buttonRef}
          type="button"
          onClick={toggle}
          aria-haspopup="menu"
          aria-expanded={open}
          className={`inline-flex items-center justify-center border border-gray-200 text-brand-700 transition-colors hover:border-brand-500 hover:bg-brand-50 ${
            primary ? '-ml-px px-2' : compact ? 'gap-1 px-2 py-1 text-xs' : 'gap-1.5 px-3 py-1.5 text-sm font-medium'
          }`}
        >
          {!primary ? <FilePenLine className="h-3.5 w-3.5" /> : null}
          {!primary ? '录入' : null}
          <ChevronDown className="h-3.5 w-3.5" />
        </button>
      </div>
      {open
        ? createPortal(
            <>
              <button type="button" aria-label="关闭录入菜单" className="fixed inset-0 z-[80] cursor-default" onClick={() => setOpen(false)} />
              <div
                role="menu"
                className="fixed z-[81] w-[300px] border border-gray-200 bg-white p-1.5 shadow-xl"
                style={{ top: position.top, left: position.left }}
              >
                {OPTIONS.map((option) => (
                  <button
                    key={option.scope}
                    type="button"
                    role="menuitem"
                    onClick={() => choose(option.scope)}
                    className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-brand-50"
                  >
                    <option.icon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                    <span>
                      <span className="block text-sm font-medium text-gray-900">{option.label}</span>
                      <span className="mt-0.5 block text-xs leading-5 text-gray-500">{option.description}</span>
                    </span>
                  </button>
                ))}
              </div>
            </>,
            document.body,
          )
        : null}
    </>
  );
}
