import { ExternalLink, FileSearch, X } from 'lucide-react';
import { valueLabel } from '../../lib/fieldLabels';
import type { FieldValueSource } from '../../types/api';

function domain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function sourceGrade(sourceType: string | null | undefined): string {
  if (['regulatory_disclosure', 'government', 'company_website'].includes(sourceType || '')) return 'A级';
  return 'B级';
}

export default function ResearchEvidenceDrawer({
  source,
  onClose,
  onOpenReport,
}: {
  source: FieldValueSource;
  onClose: () => void;
  onOpenReport: (jobId: string) => void;
}) {
  const evidence = source.research_evidence;
  const url = evidence?.source_url || '';
  const title = evidence?.source_title || (url ? domain(url) : source.source_label) || '公开调研';
  const snapshot = source.value_snapshot_json?.value;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onMouseDown={onClose}>
      <aside className="h-full w-full max-w-md bg-white shadow-xl" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-gray-900">字段证据</h3>
            <p className="mt-1 text-xs text-gray-400">只展示支撑当前字段值的主证据</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700" aria-label="关闭字段证据">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-5 px-5 py-4 text-sm">
          <section>
            <p className="text-xs font-medium text-gray-500">当前值</p>
            <p className="mt-1 text-gray-900">{valueLabel(source.field_path, snapshot)}</p>
            {(evidence?.period_label || evidence?.as_of_date) && (
              <p className="mt-1 text-xs text-gray-400">期间：{evidence.period_label || evidence.as_of_date}</p>
            )}
          </section>
          <section>
            <p className="text-xs font-medium text-gray-500">主来源</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">{title} · {sourceGrade(evidence?.source_type)}</span>
            </div>
            {url && (
              <a href={url} target="_blank" rel="noreferrer" className="mt-2 flex items-center gap-1 text-xs text-brand-600 hover:underline">
                <ExternalLink className="h-3.5 w-3.5" />打开原始来源
              </a>
            )}
          </section>
          <section>
            <p className="text-xs font-medium text-gray-500">原文摘录</p>
            {evidence?.source_excerpt ? (
              <blockquote className="mt-2 border-l-2 border-brand-200 bg-gray-50 px-3 py-2 text-sm leading-6 text-gray-700">
                {evidence.source_excerpt}
              </blockquote>
            ) : (
              <p className="mt-2 text-xs leading-5 text-gray-400">本条历史来源未保存字段级原文；新调研会从 Agent 输出中保留摘录。</p>
            )}
          </section>
          {evidence?.job_id && (
            <button
              type="button"
              onClick={() => onOpenReport(evidence.job_id as string)}
              className="inline-flex items-center gap-1.5 border border-brand-200 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-50"
            >
              <FileSearch className="h-3.5 w-3.5" />
              查看本次完整调研报告
            </button>
          )}
        </div>
      </aside>
    </div>
  );
}
