import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import type { SellerTarget } from '../../types/api';
import { gradeClass, targetGrade, targetGradeLabel } from '../../lib/entityGrade';
import {
  AI_PROCESSING_CLASSES,
  AI_PROCESSING_LABELS,
  aiProcessingDetail,
  aiProcessingState,
  isAiProcessingActive,
} from './aiProcessing';

/** 标的级别，也是推荐初筛的唯一闸门：E 不参与筛选，A-D 都参与。 */
export function TargetStatusBadge({ item }: { item: SellerTarget }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium ${gradeClass(targetGrade(item))}`}>
      {targetGradeLabel(item)}
    </span>
  );
}

/** AI 处理进度：解析与调研两条流水线合成一列。 */
export function TargetAiProcessingBadge({ item }: { item: SellerTarget }) {
  const state = aiProcessingState(item);
  const active = isAiProcessingActive(state);
  const pendingCount = item.pending_research_conflict_count || 0;
  const content = (
    <span
      title={aiProcessingDetail(item)}
      className={`inline-flex items-center justify-center gap-1 whitespace-nowrap px-2 py-0.5 text-xs font-medium ${AI_PROCESSING_CLASSES[state]}`}
    >
      {active ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
      {AI_PROCESSING_LABELS[state]}
    </span>
  );
  const status = state === 'parse_failed'
    ? <Link to={`/targets/${item.id}?tab=history`}>{content}</Link>
    : state === 'research_failed'
      ? <Link to={`/targets/${item.id}`}>{content}</Link>
      : content;
  return (
    <span className="inline-flex flex-wrap items-center justify-center gap-1">
      {status}
      {pendingCount > 0 && (
        <Link
          to={`/targets/${item.id}`}
          className="whitespace-nowrap bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700"
        >
          {pendingCount}项待确认
        </Link>
      )}
    </span>
  );
}

export function YesNoBadge({ value }: { value: string | null }) {
  const normalized = value || 'unknown';
  const labelMap: Record<string, string> = {
    yes: '是',
    likely: '可能',
    no: '否',
    unknown: '未知',
  };
  const colorMap: Record<string, string> = {
    yes: 'bg-emerald-50 text-emerald-700',
    likely: 'bg-blue-50 text-blue-700',
    no: 'bg-gray-100 text-gray-600',
    unknown: 'bg-gray-100 text-gray-500',
  };
  return <span className={`text-xs px-2 py-0.5 font-medium ${colorMap[normalized] || colorMap.unknown}`}>{labelMap[normalized] || normalized}</span>;
}

export function formatTargetType(type: string | null): string {
  const map: Record<string, string> = {
    company: '公司',
    equity_package: '股权包',
    business_unit: '业务单元',
    asset_package: '资产包',
    project: '项目',
    other: '其他',
  };
  return type ? map[type] || type : '-';
}

export function formatListedStatus(status: string | null): string {
  if (status === 'listed') return '已上市';
  if (status === 'unlisted' || status === 'pre_ipo') return '未上市';
  return '未知';
}

export function getSubjectDisplay(item: SellerTarget): string {
  const subject = item.target_subject_name?.trim();
  return subject || '-';
}

export function getPreferredPrice(item: SellerTarget): { kind: 'asking' | 'valuation'; value: string; date: string | null } | null {
  if (item.asking_price_yuan) return { kind: 'asking', value: item.asking_price_yuan, date: item.asking_price_date };
  if (item.valuation_yuan) return { kind: 'valuation', value: item.valuation_yuan, date: item.valuation_date };
  return null;
}

export function formatTransferRatio(item: SellerTarget): string {
  if (item.transfer_ratio_text) return item.transfer_ratio_text;
  if (item.transfer_ratio_min && item.transfer_ratio_max) return `${formatRatio(item.transfer_ratio_min)}-${formatRatio(item.transfer_ratio_max)}`;
  if (item.transfer_ratio_min) return `>=${formatRatio(item.transfer_ratio_min)}`;
  if (item.transfer_ratio_max) return `<=${formatRatio(item.transfer_ratio_max)}`;
  return '-';
}

export function formatRatio(value: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return `${Number(num.toFixed(1))}%`;
}
