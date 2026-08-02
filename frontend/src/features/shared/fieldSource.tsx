import type { FieldValueSource } from '../../types/api';

/**
 * 「这个值哪来的」——标的信息页和买家需求页共用。
 *
 * 两边的 field_value_source 是同一张表、同一个接口，只是买家侧的来源以附件证据
 * 为主、标的侧多一路 AI 调研。展示口径必须一致，否则同一条来源在两个页面上会
 * 显示成两种说法。
 */

export function fieldSourceLabel(source: FieldValueSource): string {
  if (['direct_api', 'manual', 'manual_edit'].includes(source.source_type || '')) return '手动编辑';
  if (source.source_type === 'research_proposal') return 'AI调研';
  if (['update_log_rollback', 'rollback'].includes(source.source_type || '')) return '更新回滚';
  if (source.evidence_span?.attachment_id) return '文字+附件更新';
  return '文字更新';
}

export function formatSourceTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function sourceDetailText(source: FieldValueSource): string {
  return [
    fieldSourceLabel(source),
    source.created_by_name,
    source.created_at ? formatSourceTime(source.created_at) : null,
  ]
    .filter(Boolean)
    .join(' · ');
}

/** 有原文可看时才是按钮：AI 调研有网页证据，附件解析有正文片段。 */
export function hasReadableEvidence(source: FieldValueSource): boolean {
  return source.source_type === 'research_proposal'
    || Boolean(source.evidence_span?.text_excerpt);
}
