export type SellerTargetDisplayStatus = 'active' | 'sold' | 'off_market';

// Mirrors SELLER_TARGET_DISPLAY_STATUS_SQL on the backend. Since 0727 the
// list's 「状态」 column is the trade lifecycle and nothing else — AI progress
// has its own column (features/targets/aiProcessing.ts). Mixing the two is
// what let a fully parsed target read as "未解析" while being excluded from
// recommendation screening.
export function sellerTargetDisplayStatus(target: {
  lifecycle_status: string;
}): SellerTargetDisplayStatus {
  if (target.lifecycle_status === 'sold') return 'sold';
  if (target.lifecycle_status === 'off_market') return 'off_market';
  return 'active';
}

const DISPLAY_STATUS_LABELS: Record<SellerTargetDisplayStatus, string> = {
  active: '在售中',
  sold: '已售出',
  off_market: '已停售',
};

const DISPLAY_STATUS_CLASSES: Record<SellerTargetDisplayStatus, string> = {
  active: 'bg-emerald-50 text-emerald-700',
  sold: 'bg-violet-50 text-violet-700',
  off_market: 'bg-amber-50 text-amber-700',
};

export function sellerTargetDisplayStatusLabel(status: SellerTargetDisplayStatus): string {
  return DISPLAY_STATUS_LABELS[status];
}

export function sellerTargetDisplayStatusClass(status: SellerTargetDisplayStatus): string {
  return DISPLAY_STATUS_CLASSES[status];
}
