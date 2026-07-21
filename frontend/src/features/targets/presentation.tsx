import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import type { SellerTarget } from '../../types/api';
import { isParsingTarget } from './filters';

export function RecommendationStatusBadge({ item }: { item: SellerTarget }) {
  let label = '暂不可推荐';
  let color = 'bg-gray-100 text-gray-600';
  if (item.lifecycle_status === 'sold') {
    label = '已售出';
    color = 'bg-violet-50 text-violet-700';
  } else if (item.lifecycle_status === 'off_market') {
    label = '已停售';
    color = 'bg-amber-50 text-amber-700';
  } else if (item.recommendation_status === 'recommendable') {
    label = '可推荐';
    color = 'bg-emerald-50 text-emerald-700';
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}

export function TargetParseStatusBadge({ item }: { item: SellerTarget }) {
  const parsing = isParsingTarget(item);
  const failed = item.information_status === 'parse_failed';
  const pendingReview = item.information_status === 'pending_review';
  const parsed = item.recommendation_status === 'recommendable';
  const label = parsing
    ? '解析中'
    : failed
      ? '解析失败'
      : pendingReview
        ? '待复核'
        : parsed
          ? '已解析'
          : '未解析';
  const color = parsing
    ? 'bg-blue-50 text-blue-700'
    : failed
      ? 'bg-red-50 text-red-700'
      : pendingReview
        ? 'bg-amber-50 text-amber-700'
        : parsed
          ? 'bg-emerald-50 text-emerald-700'
          : 'bg-gray-100 text-gray-600';
  const content = (
    <span className={`inline-flex items-center justify-center gap-1 whitespace-nowrap px-2 py-0.5 text-xs font-medium ${color}`}>
      {parsing ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
      {label}
    </span>
  );
  return failed || pendingReview ? <Link to={`/targets/${item.id}?tab=history`}>{content}</Link> : content;
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
