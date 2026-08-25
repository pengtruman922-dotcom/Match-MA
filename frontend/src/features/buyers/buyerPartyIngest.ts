import type { BuyerPartyIngestState, BuyerPartyIngestStage } from '../../types/api';

/**
 * 「AI 补全买家信息」的一条进度。
 *
 * 三段（解析 / 调研 / 规范化）在后端是三个 job，共用一个 correlation_id；
 * 状态由后端从 job 表派生，前端只渲染 —— 和标的侧一样，界面不许自己推断
 * 「跑完没有」，否则列表和详情页会各说一套。
 */
export const INGEST_STAGE_LABELS: Record<BuyerPartyIngestStage, string> = {
  attachment_extraction: '正在读取附件',
  parsing: '解析材料中',
  researching: '联网调研中',
  normalizing: '整理结果中',
  completed: '处理完成',
};

export const INGEST_STATUS_CLASSES: Record<BuyerPartyIngestState['overall_status'], string> = {
  not_started: 'bg-gray-100 text-gray-500',
  processing: 'bg-indigo-50 text-indigo-700',
  succeeded: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-red-50 text-red-700',
};

export function isIngestActive(state: BuyerPartyIngestState | null): boolean {
  return state?.overall_status === 'processing';
}

/** 进度条上显示的一行字。调研那一段要说清它可能很久，否则会被当成卡死。 */
export function ingestProgressText(state: BuyerPartyIngestState): string {
  const stage = state.current_stage ? INGEST_STAGE_LABELS[state.current_stage] : null;
  if (state.overall_status !== 'processing') return state.stage_label || state.status_label;
  if (state.current_stage === 'researching') return `${stage}（约 5–10 分钟，可以先去做别的）`;
  return stage || state.status_label;
}

/**
 * 材料装配时被丢掉的东西。**必须显示**：顾问拍 20 页年报只有 5 页进上下文，
 * 而且系统不会报错 —— 不说出来就是骗人。
 */
export function ingestTruncationWarning(state: BuyerPartyIngestState): string | null {
  const parts: string[] = [];
  const countLimited = state.skipped_images.filter((item) => item.reason === 'image_count_limit_exceeded');
  if (countLimited.length) {
    parts.push(`有 ${countLimited.length} 张图片超出单次 5 张的上限，没有进入本次解析`);
  }
  const tooLarge = state.skipped_images.filter((item) => item.reason === 'image_too_large');
  if (tooLarge.length) parts.push(`有 ${tooLarge.length} 张图片超过单张上限`);
  const unreadable = state.skipped_images.filter((item) => item.reason === 'image_read_failed');
  if (unreadable.length) parts.push(`有 ${unreadable.length} 张图片读取失败`);
  if (state.material_text_truncated) parts.push('材料文本过长，尾部已被截断');
  return parts.length ? `${parts.join('；')}。` : null;
}

export const REFRESH_FIELD_LABELS: Record<string, string> = {
  market_cap_yuan: '市值',
  current_revenue_yuan: '营收',
  current_operating_cash_flow_yuan: '经营现金流',
};

export function staleFieldsText(state: BuyerPartyIngestState | null): string | null {
  if (!state?.stale_financial_fields.length) return null;
  return state.stale_financial_fields.map((field) => REFRESH_FIELD_LABELS[field] || field).join('、');
}
