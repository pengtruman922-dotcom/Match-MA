import { useEffect, useRef, useState } from 'react';
import { Copy, Loader2, RefreshCw } from 'lucide-react';
import { recommendations } from '../../lib/api';
import type { RecommendationReport, RecommendationSelectedItem } from '../../types/api';
import Modal from '../../components/Modal';
import TinyMarkdown from './TinyMarkdown';

const REPORT_POLL_INTERVAL_MS = 4000;
const REPORT_POLL_MAX_ATTEMPTS = 45;

type Phase = 'confirm' | 'generating' | 'preview' | 'failed';

export default function ReportModal({
  sessionId,
  selectedItems,
  defaultTitle,
  onClose,
  onGenerated,
}: {
  sessionId: string;
  selectedItems: RecommendationSelectedItem[];
  defaultTitle: string;
  onClose: () => void;
  onGenerated: () => void;
}) {
  const [phase, setPhase] = useState<Phase>('confirm');
  const [title, setTitle] = useState(defaultTitle);
  const [report, setReport] = useState<RecommendationReport | null>(null);
  const [history, setHistory] = useState<RecommendationReport[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    recommendations.reports(sessionId).then(setHistory).catch(() => {});
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [sessionId]);

  const startPolling = (reportId: string) => {
    let attempts = 0;
    pollRef.current = window.setInterval(async () => {
      attempts += 1;
      if (attempts > REPORT_POLL_MAX_ATTEMPTS) {
        if (pollRef.current) window.clearInterval(pollRef.current);
        setError('报告生成超时，请稍后在报告历史中查看');
        setPhase('failed');
        return;
      }
      try {
        const latest = await recommendations.getReport(reportId);
        if (latest.status === 'generated') {
          if (pollRef.current) window.clearInterval(pollRef.current);
          setReport(latest);
          setPhase('preview');
          recommendations.reports(sessionId).then(setHistory).catch(() => {});
          onGenerated();
        } else if (latest.status === 'failed') {
          if (pollRef.current) window.clearInterval(pollRef.current);
          setError('报告生成失败，可重试或联系管理员在任务中心排查');
          setPhase('failed');
        }
      } catch {
        // 网络抖动继续轮询，由 attempts 上限兜底
      }
    }, REPORT_POLL_INTERVAL_MS);
  };

  const generate = async () => {
    setPhase('generating');
    setError(null);
    try {
      const job = await recommendations.createReportJob(sessionId, { title: title.trim() || undefined });
      startPolling(job.report.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建报告任务失败');
      setPhase('failed');
    }
  };

  const copyMarkdown = async () => {
    if (!report?.markdown_content) return;
    try {
      await navigator.clipboard.writeText(report.markdown_content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError('复制失败，请手动选择文本复制');
    }
  };

  const viewHistoryReport = (item: RecommendationReport) => {
    setReport(item);
    setPhase('preview');
  };

  return (
    <Modal title="生成推荐报告" onClose={onClose} wide>
      {phase === 'confirm' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-700">将基于已加入的 {selectedItems.length} 个推荐项生成报告:</p>
          <ol className="space-y-1 text-sm text-gray-600">
            {selectedItems.map((item, index) => (
              <li key={item.id}>
                {index + 1}. {item.seller_target_name || item.buyer_intent_name || '未命名'}
                {item.recommendation_level && <span className="ml-2 text-xs text-gray-400">{item.recommendation_level}</span>}
              </li>
            ))}
          </ol>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">报告标题</span>
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          {history.length > 0 && (
            <div className="text-xs text-gray-500">
              历史报告:
              {history.map((item) => (
                <button key={item.id} type="button" onClick={() => viewHistoryReport(item)} className="ml-2 text-brand-600 hover:underline">
                  {item.title || item.created_at.slice(0, 16)}
                </button>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="border border-gray-200 px-4 py-2 text-sm text-gray-700">取消</button>
            <button
              type="button"
              onClick={() => void generate()}
              disabled={selectedItems.length === 0}
              className="bg-brand-600 px-4 py-2 text-sm text-white hover:bg-brand-700 disabled:opacity-50"
            >
              开始生成
            </button>
          </div>
        </div>
      )}

      {phase === 'generating' && (
        <div className="flex flex-col items-center gap-3 py-12 text-sm text-gray-500">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
          AI 正在撰写报告（约 30-60 秒）...
        </div>
      )}

      {phase === 'preview' && report && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-gray-800">{report.title || '推荐报告'}</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void copyMarkdown()}
                className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-600"
              >
                <Copy className="h-3 w-3" />
                {copied ? '已复制' : '复制 Markdown'}
              </button>
              <button
                type="button"
                onClick={() => setPhase('confirm')}
                className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-600"
              >
                <RefreshCw className="h-3 w-3" />
                重新生成
              </button>
            </div>
          </div>
          <div className="max-h-[52vh] overflow-y-auto border border-gray-200 bg-gray-50 p-4">
            {report.markdown_content ? <TinyMarkdown text={report.markdown_content} /> : <p className="text-sm text-gray-400">报告内容为空</p>}
          </div>
        </div>
      )}

      {phase === 'failed' && (
        <div className="space-y-3 py-4">
          <p className="text-sm text-red-700">{error || '报告生成失败'}</p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="border border-gray-200 px-4 py-2 text-sm text-gray-700">关闭</button>
            <button type="button" onClick={() => void generate()} className="bg-brand-600 px-4 py-2 text-sm text-white hover:bg-brand-700">
              重试
            </button>
          </div>
        </div>
      )}

      {error && phase !== 'failed' && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </Modal>
  );
}
