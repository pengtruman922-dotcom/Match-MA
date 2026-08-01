import { CheckCircle2, Loader2, Save, X } from 'lucide-react';

export function Editor({
  title,
  subtitle,
  onClose,
  footer,
  children,
  wide = false,
}: {
  title: string;
  subtitle?: React.ReactNode;
  onClose: () => void;
  footer: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
      <div className={`flex h-full w-full ${wide ? 'max-w-5xl' : 'max-w-2xl'} flex-col bg-white shadow-xl`}>
        <div className="flex items-start justify-between gap-3 border-b border-gray-200 px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-gray-900">{title}</h2>
            {subtitle ? <div className="mt-0.5 text-xs text-gray-500">{subtitle}</div> : null}
          </div>
          <button type="button" onClick={onClose} className="icon-button shrink-0" title="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-5">{children}</div>
        <div className="flex justify-end border-t border-gray-200 px-5 py-4">{footer}</div>
      </div>
    </div>
  );
}

export function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium ${active ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500'}`}
    >
      {icon}
      {children}
    </button>
  );
}

export function SegmentButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={`px-3 py-1.5 text-xs ${active ? 'bg-gray-900 text-white' : 'text-gray-600'}`}>
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      {children}
      {hint ? <p className="mt-1 text-xs text-gray-400">{hint}</p> : null}
    </label>
  );
}

export function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>;
}

export function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 font-medium">{children}</th>;
}

export function Td({ children, clamp = false }: { children: React.ReactNode; clamp?: boolean }) {
  return (
    <td className="px-4 py-3 align-top text-gray-700">
      <div className={clamp ? 'max-w-xs truncate' : ''}>{children}</div>
    </td>
  );
}

export function Status({ active }: { active: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${active ? 'text-emerald-700' : 'text-gray-400'}`}>
      {active ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
      {active ? '启用' : '停用'}
    </span>
  );
}

export function Loading() {
  return (
    <div className="flex items-center justify-center py-12 text-sm text-gray-400">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      正在加载
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void | Promise<void> }) {
  return (
    <div className="border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
      <p>{message}</p>
      <button type="button" onClick={() => void onRetry()} className="mt-2 text-xs underline">
        重新加载
      </button>
    </div>
  );
}

export function SaveButton({
  saving,
  onClick,
  label = '保存',
  disabled = false,
}: {
  saving: boolean;
  onClick: () => void | Promise<void>;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => void onClick()}
      disabled={saving || disabled}
      className="inline-flex items-center gap-1.5 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50"
    >
      {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
      {label}
    </button>
  );
}

export function asNumber(value: number | string | null): number | null {
  if (value === null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * 「3 分钟前」这类相对时间；节点列表和抽屉都用它显示最近调用。
 *
 * 后端给的是 Postgres 的 `timestamptz::text`，形如 `2026-08-01 09:30:00.12+00`。
 * 直接 Date.parse 会得到 NaN —— 时区偏移必须补成 `+00:00`，空格必须换成 T。
 */
export function relativeTime(value: string | null | undefined): string {
  if (!value) return '';
  const normalized = value
    .replace(' ', 'T')
    .replace(/([+-]\d{2})$/, '$1:00');
  const parsed = Date.parse(normalized);
  if (!Number.isFinite(parsed)) return '';
  const minutes = Math.floor((Date.now() - parsed) / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return days < 30 ? `${days} 天前` : `${Math.floor(days / 30)} 个月前`;
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}
