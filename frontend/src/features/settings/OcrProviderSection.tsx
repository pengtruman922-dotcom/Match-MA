import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { apiRequest } from '../../lib/api/client';
import { Th, Td } from './shared';

/**
 * OCR 服务商。
 *
 * 它**不是 AI 节点** —— 不绑模型、不吃提示词，只是一次第三方 HTTP 调用
 * （doc2x），所以和搜索工具放在一起，而不是「AI 节点」列表里。
 */
interface OcrConfigOverview {
  adapter: string;
  base_url: string;
  model: string;
  key_configured: boolean;
  configured: boolean;
  source: 'database' | 'environment';
  provider_name: string | null;
  adapters: string[];
  upload_timeout_seconds: number;
  poll_interval_seconds: number;
  max_wait_seconds: number;
}

export default function OcrProviderSection() {
  const [data, setData] = useState<OcrConfigOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await apiRequest<OcrConfigOverview>('/search-config/ocr-config/overview'));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取 OCR 配置失败');
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (error) return <p className="text-xs text-red-600">{error}</p>;
  if (!data) return null;

  return (
    <section>
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-gray-900">OCR 服务</h2>
        <p className="mt-1 text-xs text-gray-500">
          扫描件与图片附件的文字识别，调用第三方 API，不经过 AI 节点。
        </p>
      </div>
      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[860px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr><Th>适配器</Th><Th>Base URL</Th><Th>模型 / 版本</Th><Th>Key</Th><Th>配置来源</Th><Th>状态</Th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            <tr>
              <Td><span className="font-medium text-gray-900">{data.adapter}</span></Td>
              <Td clamp>{data.base_url || '-'}</Td>
              <Td><span className="font-mono text-xs">{data.model || '-'}</span></Td>
              <Td>{data.key_configured ? '已配置' : <span className="text-amber-700">未配置</span>}</Td>
              <Td>
                {data.source === 'database'
                  ? <span>设置页{data.provider_name ? ` · ${data.provider_name}` : ''}</span>
                  : <span className="text-gray-500">环境变量</span>}
              </Td>
              <Td>
                {data.configured
                  ? <span className="inline-flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />可用</span>
                  : <span className="inline-flex items-center gap-1 text-xs text-amber-700"><AlertCircle className="h-3.5 w-3.5" />不可用</span>}
              </Td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-400">
        超时 {data.upload_timeout_seconds}s · 轮询间隔 {data.poll_interval_seconds}s · 最长等待 {data.max_wait_seconds}s
        （运维调参，仍由环境变量给）。
      </p>
      {data.source === 'environment' ? (
        <p className="mt-1 text-xs text-amber-700">
          当前配置来自环境变量，而这里读到的是 <b>API 服务</b>的环境 —— OCR 任务跑在 worker-ocr 服务上，
          两边的环境变量各自独立，上面的状态未必等于 worker 的真实情况。
          在「模型配置」新增一条 OCR 配置后，两个服务读同一份，这里的状态才是权威的，改 Key 也不再需要重新部署。
        </p>
      ) : null}
      <p className="mt-1 text-xs text-gray-400">
        带文字层的 PDF 和 Office 文件直接抽取文本，不经过 OCR 服务；只有扫描件与图片才会调用它。
      </p>
    </section>
  );
}
