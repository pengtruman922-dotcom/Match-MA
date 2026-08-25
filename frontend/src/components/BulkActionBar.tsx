import { Loader2, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { isAdmin } from '../lib/auth';
import type { AppUserOption } from '../types/api';

export default function BulkActionBar({
  count,
  label,
  deleting,
  onClear,
  onDelete,
  assignOptions,
  assignValue,
  onAssignValueChange,
  onAssign,
  assigning,
  extraActions,
}: {
  count: number;
  label: string;
  deleting: boolean;
  onClear: () => void;
  onDelete: () => void;
  assignOptions?: AppUserOption[];
  assignValue?: string;
  onAssignValueChange?: (value: string) => void;
  onAssign?: () => void;
  assigning?: boolean;
  /** 列表特有的批量动作（如买家侧的「AI 补全信息」），放在指派与删除之前。 */
  extraActions?: ReactNode;
}) {
  const admin = isAdmin();
  return (
    <div className="flex items-center justify-between gap-3 border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
      <span className="text-amber-800">已选择 {count} 个{label}</span>
      <div className="flex items-center gap-2">
        <button onClick={onClear} className="px-3 py-1.5 text-xs text-amber-700 hover:text-amber-900">取消选择</button>
        {extraActions}
        {admin && assignOptions && onAssign && (
          <>
            <select
              value={assignValue || ''}
              onChange={(event) => onAssignValueChange?.(event.target.value)}
              className="border border-amber-300 bg-white px-2 py-1.5 text-xs text-gray-700"
            >
              <option value="">选择负责人...</option>
              {assignOptions
                .filter((option) => option.status === 'active')
                .map((option) => (
                  <option key={option.id} value={option.id}>{option.name}</option>
                ))}
            </select>
            <button
              onClick={onAssign}
              disabled={assigning || !assignValue}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {assigning && <Loader2 className="w-3 h-3 animate-spin" />}
              批量指派
            </button>
          </>
        )}
        <button onClick={onDelete} disabled={deleting} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">
          {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
          批量删除
        </button>
      </div>
    </div>
  );
}
