import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const PAGE_ITEM_HEIGHT = 32;
const PAGE_LIST_HEIGHT = 240;

export default function PaginationFooter({
  page,
  pageCount,
  pageSize,
  loading,
  onPageChange,
  pageSizeOptions,
  onPageSizeChange,
}: {
  page: number;
  pageCount: number;
  pageSize: number;
  loading: boolean;
  onPageChange: (page: number) => void;
  /** 传入后才渲染每页条数下拉；不传保持纯文本。 */
  pageSizeOptions?: number[];
  onPageSizeChange?: (pageSize: number) => void;
}) {
  const showPageSizeSelect = Boolean(pageSizeOptions?.length && onPageSizeChange);
  return (
    <div className="flex items-center justify-between gap-3 border border-gray-200 border-t-0 bg-white px-4 py-3 text-sm text-gray-500">
      <span className="flex items-center gap-1">
        <PagePicker page={page} pageCount={pageCount} loading={loading} onPageChange={onPageChange} />
        <span>·</span>
        <span>每页</span>
        {showPageSizeSelect ? (
          <select
            value={pageSize}
            disabled={loading}
            onChange={(event) => onPageSizeChange?.(Number(event.target.value))}
            className="border border-gray-200 bg-white px-1.5 py-0.5 text-sm text-gray-700 disabled:opacity-40"
            aria-label="每页条数"
          >
            {pageSizeOptions?.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
        ) : (
          <span>{pageSize}</span>
        )}
        <span>条</span>
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1 || loading}
          className="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-700"
        >
          上一页
        </button>
        <button
          onClick={() => onPageChange(Math.min(pageCount, page + 1))}
          disabled={page >= pageCount || loading}
          className="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-700"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

/** 点击「第 X / Y 页」弹出全部页码，当前页居中高亮，也可直接输入页码。 */
function PagePicker({
  page,
  pageCount,
  loading,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ bottom: 0, left: 0, width: 0 });
  const [jumpValue, setJumpValue] = useState('');
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    // 页面滚动会让弹层错位，需要关闭；但弹层内部页码列表自身的滚动不算——
    // 打开时把当前页滚到居中同样会触发 scroll，不排除就会自己把自己关掉。
    const onScroll = (event: Event) => {
      const target = event.target;
      if (menuRef.current && target instanceof Node && menuRef.current.contains(target)) return;
      close();
    };
    window.addEventListener('resize', close);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [open]);

  // 打开后把当前页滚到列表中间。
  useLayoutEffect(() => {
    if (!open || !listRef.current) return;
    listRef.current.scrollTop = (page - 1) * PAGE_ITEM_HEIGHT - PAGE_LIST_HEIGHT / 2 + PAGE_ITEM_HEIGHT / 2;
  }, [open, page]);

  const toggle = () => {
    if (!open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      // 向上弹出：分页器在表格底部，向下会出屏。宽度对齐触发按钮。
      setPosition({ bottom: window.innerHeight - rect.top + 6, left: rect.left, width: rect.width });
    }
    setJumpValue('');
    setOpen((value) => !value);
  };

  const goTo = (next: number) => {
    setOpen(false);
    onPageChange(Math.min(pageCount, Math.max(1, next)));
  };

  const submitJump = () => {
    const parsed = Number(jumpValue.trim());
    if (!Number.isFinite(parsed) || parsed < 1) return;
    goTo(Math.floor(parsed));
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        disabled={loading || pageCount <= 1}
        aria-haspopup="menu"
        aria-expanded={open}
        className="whitespace-nowrap px-1 text-gray-600 underline decoration-dotted underline-offset-4 transition-colors hover:text-brand-600 disabled:cursor-default disabled:text-gray-500 disabled:no-underline"
      >
        第 {page} / {pageCount} 页
      </button>
      {open
        ? createPortal(
            <>
              <button type="button" aria-label="关闭页码选择" className="fixed inset-0 z-[80] cursor-default" onClick={() => setOpen(false)} />
              <div
                ref={menuRef}
                role="menu"
                className="fixed z-[81] border border-gray-200 bg-white shadow-xl"
                style={{ bottom: position.bottom, left: position.left, width: position.width }}
              >
                {/* 弹层宽度对齐触发按钮，容不下独立的「跳至」标签，用 placeholder 代替。 */}
                <div className="border-b border-gray-100 p-1">
                  <input
                    autoFocus
                    value={jumpValue}
                    inputMode="numeric"
                    placeholder="跳至"
                    onChange={(event) => setJumpValue(event.target.value.replace(/\D/g, ''))}
                    onKeyDown={(event) => { if (event.key === 'Enter') submitJump(); }}
                    className="block w-full min-w-0 border border-gray-200 px-1.5 py-0.5 text-center text-xs text-gray-700 placeholder:text-gray-400 focus:border-brand-500 focus:outline-none"
                    aria-label={`跳至页码，共 ${pageCount} 页`}
                  />
                </div>
                <div ref={listRef} className="overflow-y-auto" style={{ maxHeight: PAGE_LIST_HEIGHT }}>
                  {Array.from({ length: pageCount }, (_, index) => index + 1).map((value) => (
                    <button
                      key={value}
                      type="button"
                      role="menuitem"
                      onClick={() => goTo(value)}
                      style={{ height: PAGE_ITEM_HEIGHT }}
                      className={`flex w-full items-center justify-center text-xs transition-colors ${
                        value === page ? 'bg-brand-50 font-semibold text-brand-700' : 'text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      {value}
                    </button>
                  ))}
                </div>
              </div>
            </>,
            document.body,
          )
        : null}
    </>
  );
}
