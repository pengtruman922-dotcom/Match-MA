export function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

export function formatMonthDayTime(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hour}:${minute}`;
}

export function formatCompactMoney(value: number): string {
  if (!Number.isFinite(value)) return '-';
  if (Math.abs(value) < 10000) return `${value.toFixed(0)}元`;
  if (Math.abs(value) < 100000000) return `${(value / 10000).toFixed(0)}万`;
  return `${(value / 100000000).toFixed(1)}亿`;
}

export function formatYuan(val: string | number): string {
  const num = Number(val);
  if (!Number.isFinite(num)) return '-';
  const sign = num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${sign}${Math.round(abs / 10000)}万`;
  if (Number.isInteger(num)) return String(num);
  return String(Number(num.toFixed(2)));
}

export function formatPercent(val: string | null): string {
  if (!val) return '-';
  const raw = Number(val);
  if (!Number.isFinite(raw)) return '-';
  const percentage = raw > 0 && raw <= 1 ? raw * 100 : raw;
  return `${Number(percentage.toFixed(1))}%`;
}
