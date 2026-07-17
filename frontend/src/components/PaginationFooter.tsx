export default function PaginationFooter({
  page,
  pageCount,
  pageSize,
  loading,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  pageSize: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border border-gray-200 border-t-0 bg-white px-4 py-3 text-sm text-gray-500">
      <span>第 {page} / {pageCount} 页 · 每页 {pageSize} 条</span>
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
