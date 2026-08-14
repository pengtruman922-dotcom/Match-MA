/**
 * 标的级别与需求级别（A-E）的展示口径。
 *
 * E 不进推荐，A-D 进。原来的交易状态 / 推荐状态没删，降级成「E 的细分原因」，
 * 所以徽标要拼成 `E（已售出）` 这种复合标签 —— 顾问要一眼看出这条为什么退出了
 * 推荐。A-D 只显示字母：它们之间的差别不影响召回也不影响排序，不值得占颜色。
 *
 * 后端契约见 backend/app/services/entity_grade.py，两列由 DB check 绑定，
 * 前端不需要（也不该）自己判断组合是否合法。
 */

export const GRADES = ['A', 'B', 'C', 'D', 'E'] as const;
export type Grade = (typeof GRADES)[number];

export const BLOCKED_GRADE: Grade = 'E';

const TARGET_REASON_LABELS: Record<string, string> = {
  sold: '已售出',
  off_market: '已停售',
};

const INTENT_REASON_LABELS: Record<string, string> = {
  paused: '暂停推荐',
  closed: '结束推荐',
};

function normalize(grade: string | null | undefined): Grade {
  const value = (grade || '').trim().toUpperCase();
  return (GRADES as readonly string[]).includes(value) ? (value as Grade) : 'C';
}

function label(grade: Grade, reason: string | null | undefined, reasons: Record<string, string>): string {
  if (grade !== BLOCKED_GRADE) return grade;
  const suffix = reasons[(reason || '').trim()];
  return suffix ? `E（${suffix}）` : 'E';
}

export function targetGrade(target: { target_grade?: string | null }): Grade {
  return normalize(target.target_grade);
}

export function targetGradeLabel(target: {
  target_grade?: string | null;
  lifecycle_status?: string | null;
}): string {
  return label(normalize(target.target_grade), target.lifecycle_status, TARGET_REASON_LABELS);
}

export function intentGrade(intent: { intent_grade?: string | null }): Grade {
  return normalize(intent.intent_grade);
}

export function intentGradeLabel(intent: {
  intent_grade?: string | null;
  status?: string | null;
}): string {
  return label(normalize(intent.intent_grade), intent.status, INTENT_REASON_LABELS);
}

/** A-D 一种色，E 灰掉。列表页要一眼看出的是「还在不在推」。 */
export function gradeClass(grade: Grade): string {
  return grade === BLOCKED_GRADE ? 'bg-gray-100 text-gray-500' : 'bg-emerald-50 text-emerald-700';
}

/** 详情页下拉：A-D 四项 + E 的两个细分原因，一个控件选完，不做两步。 */
export type GradeOption = { value: string; label: string; grade: Grade; reason: string | null };

function options(reasons: Record<string, string>): GradeOption[] {
  const plain = GRADES.filter((grade) => grade !== BLOCKED_GRADE).map((grade) => ({
    value: grade as string,
    label: grade as string,
    grade,
    reason: null,
  }));
  const blocked = Object.entries(reasons).map(([reason, text]) => ({
    value: `E:${reason}`,
    label: `E（${text}）`,
    grade: BLOCKED_GRADE,
    reason,
  }));
  return [...plain, ...blocked];
}

export const TARGET_GRADE_OPTIONS = options(TARGET_REASON_LABELS);
export const INTENT_GRADE_OPTIONS = options(INTENT_REASON_LABELS);

/** 下拉当前选中项的 value：E 要带上原因，否则两个 E 选项都不高亮。 */
export function gradeOptionValue(grade: Grade, reason: string | null | undefined): string {
  return grade === BLOCKED_GRADE ? `E:${(reason || '').trim()}` : grade;
}

/**
 * 把下拉的 value 还原成要 PATCH 的两列。
 *
 * A-D 只发级别，原因列由后端补成 active；E 两列都发，因为「为什么退出推荐」
 * 是用户在这个下拉里做的选择，后端猜不出来（裸 E 只会落到默认的已停售/暂停推荐）。
 */
export function gradeOptionPatch(
  value: string,
  gradeColumn: 'target_grade' | 'intent_grade',
  reasonColumn: 'lifecycle_status' | 'status',
): Record<string, string> {
  const [grade, reason] = value.split(':');
  const patch: Record<string, string> = { [gradeColumn]: grade };
  if (reason) patch[reasonColumn] = reason;
  return patch;
}
