import type { SellerTarget } from '../../types/api';

/**
 * The single "AI 处理" state shown in the target list.
 *
 * It answers one question — 我刚才发起的那个操作跑完没有 — across the two
 * asynchronous pipelines a consultant can trigger: 解析 (information_status)
 * and 调研 (last_research_at / research_last_outcome). One column is enough
 * because only one of them is ever in flight for a target at a time.
 *
 * The backend owns the decision table (including which of parse/research ran
 * most recently).  The frontend only renders the returned state so the list
 * and detail page cannot drift from API semantics.
 */
export type AiProcessingState =
  | 'parsing'
  | 'research_queued'
  | 'researching'
  | 'research_mapping'
  | 'parse_failed'
  | 'research_failed'
  | 'completed'
  | 'never';

export function aiProcessingState(target: SellerTarget): AiProcessingState {
  return target.ai_processing_state;
}

export const AI_PROCESSING_LABELS: Record<AiProcessingState, string> = {
  parsing: '解析中',
  research_queued: '排队中',
  researching: '调研中',
  research_mapping: '整理结果中',
  parse_failed: '解析失败',
  research_failed: '调研失败',
  completed: '已完成',
  never: '未处理',
};

export const AI_PROCESSING_CLASSES: Record<AiProcessingState, string> = {
  parsing: 'bg-blue-50 text-blue-700',
  research_queued: 'bg-sky-50 text-sky-700',
  researching: 'bg-indigo-50 text-indigo-700',
  research_mapping: 'bg-violet-50 text-violet-700',
  parse_failed: 'bg-red-50 text-red-700',
  research_failed: 'bg-red-50 text-red-700',
  completed: 'bg-emerald-50 text-emerald-700',
  never: 'bg-gray-100 text-gray-500',
};

export function isAiProcessingActive(state: AiProcessingState): boolean {
  return ['parsing', 'research_queued', 'researching', 'research_mapping'].includes(state);
}

/** Hover text: which pipeline ran, when, and how it ended. */
export function aiProcessingDetail(target: SellerTarget): string {
  return target.ai_processing_detail;
}
