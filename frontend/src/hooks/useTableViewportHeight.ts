import { useLayoutEffect, useRef, useState } from 'react';

/** 表格区下方要留给分页器和页面下边距的高度。 */
const FOOTER_RESERVE_PX = 72;
/** 高度下限，避免小屏或工具栏换行时表格只剩两三行。 */
const MIN_HEIGHT_PX = 320;

/**
 * 让表格区自成一个限高滚动视窗：横向滚动条固定在容器底部，不必下翻整页才够得到；
 * 配合表头 sticky top-0，横向拖动时列名不丢。
 *
 * 高度按容器实际位置动态计算，而不是写死一个偏移量——工具栏在窄屏会换行、
 * 批量操作条会出现/消失，写死偏移会让横向滚动条掉出视口。
 *
 * `deps` 传入会把表格上下推的状态（如是否有勾选、是否加载中），变化时重算。
 */
export function useTableViewportHeight(deps: unknown[] = []) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [maxHeight, setMaxHeight] = useState<number | undefined>(undefined);

  useLayoutEffect(() => {
    const recompute = () => {
      const el = ref.current;
      if (!el) return;
      // 用未滚动时的绝对位置，避免高度随页面滚动来回跳。
      const absoluteTop = el.getBoundingClientRect().top + window.scrollY;
      const next = Math.max(MIN_HEIGHT_PX, Math.round(window.innerHeight - absoluteTop - FOOTER_RESERVE_PX));
      setMaxHeight((prev) => (prev === next ? prev : next));
    };
    recompute();
    window.addEventListener('resize', recompute);

    // 工具栏因筛选标签换行而变高时不会触发 window.resize，但会把表格往下推，
    // 所以同时观察父容器。这里不会死循环：改 maxHeight 会让父容器高度变化并再触发一次
    // 回调，但那次 recompute 读到的 top 没变，next === prev 就不再 setState。
    const parent = ref.current?.parentElement;
    const observer = parent ? new ResizeObserver(recompute) : null;
    if (parent && observer) observer.observe(parent);

    return () => {
      window.removeEventListener('resize', recompute);
      observer?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ref, maxHeight };
}
