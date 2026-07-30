import { barWidth } from './distribution';

export interface CountBarItem {
  label: string;
  count: number;
}

interface Props {
  items: CountBarItem[];
  /** 条形颜色，Tailwind 类名。默认品牌红。 */
  barClassName?: string;
  /** 底部小字，通常用来交代未填数与口径。 */
  footnote?: string;
  emptyText?: string;
  /** 标签列宽，按最长标签调。 */
  labelClassName?: string;
}

/**
 * 通用横向计数条。
 *
 * 条长按**本组最大值**归一而不是按总数——按总数归一时长尾全是看不见的细线，
 * 而这些图要读的是「哪几档占大头」，不是「占总体百分之几」。真实数字始终写在
 * 右侧，所以归一方式不会让人读错量级。
 */
export default function CountBars({
  items,
  barClassName = 'bg-brand-600',
  footnote,
  emptyText = '暂无数据',
  labelClassName = 'w-24',
}: Props) {
  const max = items.reduce((current, item) => Math.max(current, item.count), 0);

  if (items.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-400">{emptyText}</p>;
  }

  return (
    <div className="space-y-2.5">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-3">
          <span
            className={`${labelClassName} shrink-0 truncate text-xs text-gray-600`}
            title={item.label}
          >
            {item.label}
          </span>
          <span className="h-4 min-w-0 flex-1 bg-gray-50">
            {/* 计数为 0 的档位保留空槽：画成 0 宽比不画更能说明「这一档确实没有」 */}
            {item.count > 0 ? (
              <span
                className={`block h-full ${barClassName}`}
                style={{ width: barWidth(item.count, max) }}
              />
            ) : null}
          </span>
          <span className="w-8 shrink-0 text-right font-mono text-xs text-gray-700">
            {item.count}
          </span>
        </div>
      ))}
      {footnote ? <p className="pt-1 text-[11px] text-gray-400">{footnote}</p> : null}
    </div>
  );
}
