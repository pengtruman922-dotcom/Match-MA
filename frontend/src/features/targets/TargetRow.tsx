import { Loader2, Trash2 } from 'lucide-react';
import { canManageOwnedEntity } from '../../lib/auth';
import type { SellerTarget } from '../../types/api';
import { ClampedLink, ClampedText } from '../../components/Clamped';
import { formatMonthDayTime, formatPercent, formatYuan } from '../../lib/format';
import { isParsingTarget } from './filters';
import UpdateEntryMenu from '../../components/UpdateEntryMenu';
import type { BusinessUpdateProcessingScope } from '../../types/api';
import {
  formatListedStatus,
  formatTargetType,
  formatTransferRatio,
  getPreferredPrice,
  getSubjectDisplay,
  TargetAiProcessingBadge,
  TargetStatusBadge,
  YesNoBadge,
} from './presentation';

export default function TargetRow({
  item,
  selected,
  onSelectedChange,
  onOpenUpdateDrawer,
  onDelete,
  deleting,
}: {
  item: SellerTarget;
  selected: boolean;
  onSelectedChange: (checked: boolean) => void;
  onOpenUpdateDrawer: (scope: BusinessUpdateProcessingScope) => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const subject = getSubjectDisplay(item);
  const industry = [item.industry_l1, item.industry_l2].filter(Boolean).join(' / ') || '-';
  const region = [item.location_province, item.location_city, item.location_district].filter(Boolean).join(' ') || '-';
  const price = getPreferredPrice(item);
  const priceDisplay = price ? `${formatYuan(price.value)}${price.kind === 'asking' ? '*' : ''}` : '-';
  const priceTitle = price
    ? `${price.kind === 'asking' ? '报价' : '估值'}：${formatYuan(price.value)}${price.kind === 'asking' ? '（明确报价）' : ''}`
    : '';
  const ratioText = formatTransferRatio(item);
  const canDelete = canManageOwnedEntity(item.owner_user_id);

  return (
    <tr className="group hover:bg-brand-50/30 transition-colors">
      <td className="sticky left-0 z-20 bg-white px-4 py-3 group-hover:bg-brand-50">
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelectedChange(event.target.checked)}
          aria-label={`选择${item.target_name}`}
          className="h-4 w-4 border-gray-300 text-brand-600 focus:ring-brand-600"
        />
      </td>
      <td className="sticky left-12 z-20 bg-white px-4 py-3 group-hover:bg-brand-50">
        <ClampedLink to={`/targets/${item.id}`} value={item.target_name} className="font-medium text-gray-900 hover:text-brand-600 transition-colors" />
        {isParsingTarget(item) ? (
          <p className="mt-1 text-xs italic text-sky-500">摘要生成中...</p>
        ) : (
          item.business_summary && <ClampedText value={item.business_summary} className="mt-1 text-xs text-gray-400" />
        )}
      </td>
      <td className="w-20 max-w-20 px-3 py-3 text-gray-600"><ClampedText value={subject} /></td>
      <td className="px-4 py-3 text-center"><TargetStatusBadge item={item} /></td>
      <td className="px-4 py-3 text-center"><TargetAiProcessingBadge item={item} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={formatTargetType(item.target_type)} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={formatListedStatus(item.listed_status)} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={industry} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={region} /></td>
      <td className="px-4 py-3 text-right text-gray-700 font-mono" title={priceTitle}>{priceDisplay}</td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={price?.date || '-'} /></td>
      <td className="px-4 py-3 text-right text-gray-600 font-mono">
        {item.current_net_profit_yuan ? formatYuan(item.current_net_profit_yuan) : '-'}
      </td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={item.financial_period_label || '-'} /></td>
      <td className="px-4 py-3 text-right text-gray-600 font-mono">{formatPercent(item.current_debt_ratio)}</td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={ratioText} /></td>
      <td className="px-4 py-3 text-center"><YesNoBadge value={item.can_control} /></td>
      <td className="px-4 py-3 text-center"><YesNoBadge value={item.can_consolidate} /></td>
      <td className="px-4 py-3 text-gray-600">
        {item.owner_name ? <ClampedText value={item.owner_name} /> : <span className="text-gray-300">未指派</span>}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-gray-500">{formatMonthDayTime(item.updated_at)}</td>
      <td className="sticky right-0 z-20 bg-white px-4 py-3 group-hover:bg-brand-50">
        <div className="flex items-center gap-1 whitespace-nowrap">
          <UpdateEntryMenu compact onSelect={onOpenUpdateDrawer} />
          {/* 「推荐买家」入口随反向方向一起下线：推荐页本轮只做「为买家找标的」，
              留一个点进去做不了事的链接比暂时没有这个入口更糟。反向 Agent 化后恢复。 */}
          {canDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
              删除
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
