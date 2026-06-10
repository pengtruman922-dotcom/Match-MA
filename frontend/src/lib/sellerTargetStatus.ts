export type SellerTargetStatusType = 'recommendation' | 'information';

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
