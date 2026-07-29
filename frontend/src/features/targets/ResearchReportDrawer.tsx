import { useMemo, useState } from 'react';
import { Check, Clipboard, ExternalLink, X } from 'lucide-react';
import type { ResearchReport } from '../../types/api';

function rawAgentOutput(report: ResearchReport): string {
  const raw = report.raw_output_text?.trim();
  if (raw) {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }
  if (report.agent_output_json) return JSON.stringify(report.agent_output_json, null, 2);
  return '本次调研任务没有保存可展示的 Agent 原始输出。';
}

export default function ResearchReportDrawer({
  report,
  onClose,
}: {
  report: ResearchReport;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<'output' | 'trace'>('output');
  const [copied, setCopied] = useState(false);
  const output = useMemo(() => rawAgentOutput(report), [report]);
  const trace = report.execution_trace || {};
  const observations = trace.search_observations || [];
  const createdAt = report.finished_at || report.created_at;

  const copyOutput = async () => {
    await navigator.clipboard.writeText(output);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20" onMouseDown={onClose}>
      <aside
        className="flex h-full w-full max-w-3xl flex-col bg-white shadow-xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-gray-900">调研报告</h3>
            <p className="mt-1 text-xs text-gray-400">
              {createdAt ? new Date(createdAt).toLocaleString('zh-CN') : '时间未知'}
              {report.prompt_version ? ` · Prompt ${report.prompt_version}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700" aria-label="关闭调研报告">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex items-center gap-1 border-b border-gray-100 px-5">
          <button
            type="button"
            onClick={() => setTab('output')}
            className={`border-b-2 px-3 py-2.5 text-sm ${tab === 'output' ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500'}`}
          >
            Agent 原始输出
          </button>
          <button
            type="button"
            onClick={() => setTab('trace')}
            className={`border-b-2 px-3 py-2.5 text-sm ${tab === 'trace' ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500'}`}
          >
            执行轨迹
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {tab === 'output' ? (
            <section>
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-xs leading-5 text-gray-500">
                  以下内容是主调研 Agent 交给结果规范化节点前的原始输出，仅做 JSON 缩进，不增删或改写内容。
                </p>
                <button type="button" onClick={() => void copyOutput()} className="inline-flex shrink-0 items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:bg-gray-50">
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Clipboard className="h-3.5 w-3.5" />}
                  {copied ? '已复制' : '复制'}
                </button>
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-words bg-gray-950 px-4 py-3 font-mono text-xs leading-6 text-gray-100">{output}</pre>
            </section>
          ) : (
            <section className="space-y-5 text-sm text-gray-700">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <TraceMetric label="LLM 调用" value={trace.llm_calls ?? '-'} />
                <TraceMetric label="检索次数" value={trace.searched_queries?.length ?? 0} />
                <TraceMetric label="抓取正文" value={trace.fetched_urls?.length ?? 0} />
                <TraceMetric label="Mapper 状态" value={report.mapper_status || '-'} />
              </div>

              {trace.early_stop_reason ? (
                <div className="border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                  提前停止：{trace.early_stop_reason}
                </div>
              ) : null}

              {observations.length > 0 ? (
                <div>
                  <h4 className="text-xs font-medium text-gray-700">检索与主体匹配</h4>
                  <div className="mt-2 space-y-3">
                    {observations.map((item, index) => (
                      <div key={`${item.query}-${index}`} className="border border-gray-200 px-3 py-2">
                        <p className="text-xs font-medium text-gray-800">{item.query}</p>
                        <p className="mt-1 text-[11px] text-gray-500">
                          返回 {item.returned_count} 条 · 主体匹配 {item.matched_result_count} 条
                          {item.error ? ` · ${item.error}` : ''}
                        </p>
                        {item.candidates?.length ? (
                          <div className="mt-2 space-y-1">
                            {item.candidates.map((candidate) => (
                              <a key={candidate.url} href={candidate.url} target="_blank" rel="noreferrer" className="flex min-w-0 items-center gap-1 text-xs text-brand-600 hover:underline">
                                <ExternalLink className="h-3 w-3 shrink-0" />
                                <span className="truncate">{candidate.title || candidate.url}</span>
                                <span className={`shrink-0 text-[10px] ${candidate.subject_match ? 'text-emerald-600' : 'text-gray-400'}`}>
                                  {candidate.subject_match ? '主体匹配' : '未匹配'}
                                </span>
                              </a>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : trace.searched_queries?.length ? (
                <div>
                  <h4 className="text-xs font-medium text-gray-700">检索词</h4>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-gray-600">
                    {trace.searched_queries.map((query) => <li key={query}>{query}</li>)}
                  </ul>
                  <p className="mt-2 text-[11px] text-gray-400">历史任务未记录候选结果明细，只能展示当时保存的检索词。</p>
                </div>
              ) : (
                <p className="text-xs text-gray-400">本次任务没有保存可展示的执行轨迹。</p>
              )}

              {trace.fetched_urls?.length ? (
                <div>
                  <h4 className="text-xs font-medium text-gray-700">已抓取正文的页面</h4>
                  <div className="mt-2 space-y-1">
                    {trace.fetched_urls.map((url) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-brand-600 hover:underline">
                        <ExternalLink className="h-3 w-3 shrink-0" />
                        <span className="truncate">{url}</span>
                      </a>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}

function TraceMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-gray-50 px-3 py-2">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="mt-1 text-sm font-medium text-gray-800">{value}</p>
    </div>
  );
}
