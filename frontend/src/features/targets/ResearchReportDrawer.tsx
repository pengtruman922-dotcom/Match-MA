import { ExternalLink, X } from 'lucide-react';
import type { BackgroundJob } from '../../types/api';

type ReportJob = Pick<BackgroundJob, 'id' | 'result_json' | 'created_at' | 'finished_at'>;

const SECTION_LABELS: Record<string, string> = {
  identity: '主体身份',
  business_product: '业务与产品',
  chain_position: '产业链位置',
  tech_team: '技术与团队',
  ops_quality: '经营质量',
  deal_terms: '交易属性',
  sell_intent_risk: '出售意愿与风险',
};

function readableAgentOutput(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null;
  const payload = value as Record<string, unknown>;
  const sections = Array.isArray(payload.profile_sections) ? payload.profile_sections : [];
  const facts = Array.isArray(payload.structured_facts) ? payload.structured_facts : [];
  if (sections.length === 0 && facts.length === 0) return null;

  const blocks: string[] = [];
  for (const item of sections) {
    if (!item || typeof item !== 'object') continue;
    const section = item as Record<string, unknown>;
    const code = String(section.section_code || '其他');
    const content = String(section.content_text || '').trim();
    if (!content) continue;
    const period = section.period_label || section.as_of_date;
    const sources = Array.isArray(section.sources) ? section.sources.map(String) : [];
    blocks.push([
      `【${SECTION_LABELS[code] || code}】${period ? `（${String(period)}）` : ''}`,
      content,
      sources.length > 0 ? `来源：\n${sources.map((url) => `- ${url}`).join('\n')}` : '',
    ].filter(Boolean).join('\n'));
  }
  if (facts.length > 0) {
    const rows = facts.flatMap((item) => {
      if (!item || typeof item !== 'object') return [];
      const fact = item as Record<string, unknown>;
      const raw = fact.value;
      const rendered = raw && typeof raw === 'object'
        ? `${String((raw as Record<string, unknown>).value ?? '')}${String((raw as Record<string, unknown>).unit ?? '')}`
        : String(raw ?? '');
      const period = fact.period_label || fact.as_of_date;
      return [`- ${String(fact.field_path || '字段')}：${rendered}${period ? `（${String(period)}）` : ''}`];
    });
    blocks.push(`【结构化指标】\n${rows.join('\n')}`);
  }
  return blocks.join('\n\n');
}

function researchReportText(job: ReportJob): string {
  const result = job.result_json || {};
  const agentOutput = result.agent_output_json;
  const directCandidates = [
    result.report_markdown,
    result.report,
    agentOutput && typeof agentOutput === 'object' ? (agentOutput as Record<string, unknown>).report_markdown : null,
    agentOutput && typeof agentOutput === 'object' ? (agentOutput as Record<string, unknown>).report_text : null,
    agentOutput && typeof agentOutput === 'object' ? (agentOutput as Record<string, unknown>).research_report : null,
    agentOutput && typeof agentOutput === 'object' ? (agentOutput as Record<string, unknown>).summary : null,
  ];
  const direct = directCandidates.find((value) => typeof value === 'string' && value.trim());
  if (typeof direct === 'string') return direct.trim();

  const readable = readableAgentOutput(agentOutput);
  if (readable) return readable;

  const raw = result.report_text;
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      return readableAgentOutput(parsed) || JSON.stringify(parsed, null, 2);
    } catch {
      return raw.trim();
    }
  }
  if (agentOutput && typeof agentOutput === 'object') return JSON.stringify(agentOutput, null, 2);
  return '本次调研没有保存可展示的完整报告正文。';
}

export default function ResearchReportDrawer({ job, onClose }: { job: ReportJob; onClose: () => void }) {
  const createdAt = job.finished_at || job.created_at;
  const result = job.result_json || {};
  const queries = Array.isArray(result.searched_queries) ? result.searched_queries as string[] : [];
  const urls = Array.isArray(result.fetched_urls) ? result.fetched_urls as string[] : [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20" onMouseDown={onClose}>
      <aside
        className="flex h-full w-full max-w-2xl flex-col bg-white shadow-xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-gray-900">本次完整调研报告</h3>
            <p className="mt-1 text-xs text-gray-400">
              {createdAt ? new Date(createdAt).toLocaleString('zh-CN') : '时间未知'}
              {result.prompt_version ? ` · Prompt ${String(result.prompt_version)}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700" aria-label="关闭调研报告">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="whitespace-pre-wrap text-sm leading-7 text-gray-700">{researchReportText(job)}</div>
          {(queries.length > 0 || urls.length > 0) && (
            <section className="mt-6 border-t border-gray-100 pt-4">
              <h4 className="text-xs font-medium text-gray-600">调研过程</h4>
              {queries.length > 0 && <p className="mt-2 text-xs leading-5 text-gray-500">检索：{queries.join('；')}</p>}
              {urls.length > 0 && (
                <div className="mt-2 space-y-1">
                  {urls.map((url) => (
                    <a key={url} href={url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-brand-600 hover:underline">
                      <ExternalLink className="h-3 w-3 shrink-0" />
                      <span className="truncate">{url}</span>
                    </a>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
