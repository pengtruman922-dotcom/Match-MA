export type SellerTargetStatusType = 'recommendation' | 'information';

export type SellerTargetDisplayStatus =
  | 'parsing'
  | 'parse_failed'
  | 'sold'
  | 'off_market'
  | 'recommendable'
  | 'not_recommendable';

// Mirrors SELLER_TARGET_DISPLAY_STATUS_SQL on the backend: parse lifecycle
// beats deal lifecycle beats recommendability.
export function sellerTargetDisplayStatus(target: {
  information_status: string;
  lifecycle_status: string;
  recommendation_status: string;
}): SellerTargetDisplayStatus {
  if (target.information_status === 'parsing' || target.information_status === 'researching') return 'parsing';
  if (target.information_status === 'parse_failed') return 'parse_failed';
  if (target.lifecycle_status === 'sold') return 'sold';
  if (target.lifecycle_status === 'off_market') return 'off_market';
  return target.recommendation_status === 'recommendable' ? 'recommendable' : 'not_recommendable';
}

const DISPLAY_STATUS_LABELS: Record<SellerTargetDisplayStatus, string> = {
  parsing: '解析中',
  parse_failed: '解析失败',
  sold: '已售出',
  off_market: '已停售',
  recommendable: '可推荐',
  not_recommendable: '暂不可推荐',
};

const DISPLAY_STATUS_CLASSES: Record<SellerTargetDisplayStatus, string> = {
  parsing: 'bg-sky-50 text-sky-700',
  parse_failed: 'bg-red-50 text-red-700',
  sold: 'bg-violet-50 text-violet-700',
  off_market: 'bg-amber-50 text-amber-700',
  recommendable: 'bg-emerald-50 text-emerald-700',
  not_recommendable: 'bg-gray-100 text-gray-600',
};

export function sellerTargetDisplayStatusLabel(status: SellerTargetDisplayStatus): string {
  return DISPLAY_STATUS_LABELS[status];
}

export function sellerTargetDisplayStatusClass(status: SellerTargetDisplayStatus): string {
  return DISPLAY_STATUS_CLASSES[status];
}

export function sellerTargetStatusLabel(status: string, type: SellerTargetStatusType): string {
  if (type === 'recommendation') {
    if (status === 'recommendable') return '可推荐';
    if (status === 'not_recommendable') return '暂不可推荐';
    return status || '-';
  }

  const labels: Record<string, string> = {
    normal: '已更新',
    insufficient: '待补充',
    pending_review: '待复核',
    parsing: '解析中',
    researching: '调研中',
    parse_failed: '解析失败',
  };
  return labels[status] || status || '-';
}

export function sellerTargetStatusClass(status: string, type: SellerTargetStatusType): string {
  if (type === 'recommendation') {
    return status === 'recommendable' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  }

  const classes: Record<string, string> = {
    normal: 'bg-emerald-50 text-emerald-700',
    insufficient: 'bg-amber-50 text-amber-700',
    pending_review: 'bg-amber-50 text-amber-700',
    parsing: 'bg-sky-50 text-sky-700',
    researching: 'bg-indigo-50 text-indigo-700',
    parse_failed: 'bg-red-50 text-red-700',
  };
  return classes[status] || 'bg-gray-100 text-gray-600';
}
