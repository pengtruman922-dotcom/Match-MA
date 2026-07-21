import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, Loader2, Plus, RefreshCw, Trash2, Zap } from 'lucide-react';
import { searchConfig } from '../../lib/api';
import type { SearchConfigOverview, SearchProviderTestResult } from '../../types/api';

/**
 * 搜索工具：调研 Agent 的检索能力来源。
 * 复用模型配置那套密钥存储 —— 直填的 Key 经 Fernet 加密存库，接口只回「已加密保存」。
 */
export default function SearchProviderSection() {
  const [data, setData] = useState<SearchConfigOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, SearchProviderTestResult>>({});

  const [name, setName] = useState('Tavily');
  const [adapter, setAdapter] = useState('tavily');
  const [baseUrl, setBaseUrl] = useState('https://api.tavily.com');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await searchConfig.overview());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取搜索配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await searchConfig.create({
        provider_name: name.trim(),
        adapter,
        base_url: baseUrl.trim(),
        secret_mode: 'direct',
        api_key: apiKey.trim(),
      });
      setApiKey('');
      setCreating(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const runTest = async (providerId: string) => {
    setTesting(providerId);
    try {
      const result = await searchConfig.test({ provider_id: providerId, query: '并购 标的 行业地位' });
      setTestResult((prev) => ({ ...prev, [providerId]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '连通性测试失败');
    } finally {
      setTesting(null);
    }
  };

  const remove = async (providerId: string) => {
    if (!window.confirm('删除该搜索工具配置？调研功能将失去检索能力。')) return;
    try {
      await searchConfig.remove(providerId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 border border-gray-200 bg-white px-4 py-3 text-xs text-gray-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        加载搜索配置…
      </div>
    );
  }

  const encryptionReady = data?.direct_key_encryption_configured;

  return (
    <section>
      <div className="mb-3 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">搜索工具</h2>
          <p className="mt-1 text-xs text-gray-500">调研 Agent 的检索来源。Key 加密保存且永不回显。</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void load()} className="icon-button" title="刷新">
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setCreating((current) => !current)}
            className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white"
          >
            <Plus className="h-4 w-4" />
            新增搜索工具
          </button>
        </div>
      </div>

      {!encryptionReady && (
        <p className="mb-2 flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            尚未配置 <code className="font-mono">MODEL_SECRET_ENCRYPTION_KEY</code> 环境变量，直接填写的密钥无法加密保存。
            请先在部署环境加上该变量。
          </span>
        </p>
      )}
      {error && <p className="mb-2 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}

      {creating && (
        <div className="mb-3 grid gap-2 border border-gray-200 bg-gray-50 p-3 sm:grid-cols-2">
          <label className="text-xs text-gray-600">
            配置名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-1 w-full border border-gray-200 px-2 py-1.5 text-sm"
            />
          </label>
          <label className="text-xs text-gray-600">
            适配器
            <select
              value={adapter}
              onChange={(event) => setAdapter(event.target.value)}
              className="mt-1 w-full border border-gray-200 px-2 py-1.5 text-sm"
            >
              {(data?.available_adapters || []).map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-600">
            Base URL
            <input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <label className="text-xs text-gray-600">
            API Key（加密保存，保存后不再回显）
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="tvly-…"
              className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <div className="flex items-center gap-2 sm:col-span-2">
            <button
              type="button"
              disabled={saving || !apiKey.trim() || !name.trim() || !encryptionReady}
              onClick={() => void save()}
              className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-40"
            >
              <Check className="h-3.5 w-3.5" />
              保存
            </button>
            <button type="button" onClick={() => setCreating(false)} className="text-xs text-gray-500">
              取消
            </button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[760px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr>
              <th className="px-3 py-2 font-medium">配置名称</th>
              <th className="px-3 py-2 font-medium">适配器</th>
              <th className="px-3 py-2 font-medium">Base URL</th>
              <th className="px-3 py-2 font-medium">Key</th>
              <th className="px-3 py-2 font-medium">连通性</th>
              <th className="px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(data?.providers || []).map((provider) => {
              const result = testResult[provider.id];
              return (
                <tr key={provider.id}>
                  <td className="px-3 py-2 font-medium text-gray-900">{provider.provider_name}</td>
                  <td className="px-3 py-2 font-mono text-xs">{provider.adapter}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">{provider.base_url || '-'}</td>
                  <td className="px-3 py-2 text-xs">{provider.key_display}</td>
                  <td className="px-3 py-2 text-xs">
                    {result ? (
                      result.status === 'succeeded' ? (
                        <span className="text-emerald-700">通过 · 返回 {result.result_count} 条</span>
                      ) : (
                        <span className="text-red-600" title={result.error_message || ''}>失败</span>
                      )
                    ) : (
                      <span className="text-gray-300">未测试</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={testing === provider.id}
                        onClick={() => void runTest(provider.id)}
                        className="inline-flex items-center gap-1 text-xs text-brand-700 disabled:opacity-40"
                      >
                        {testing === provider.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                        测试
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(provider.id)}
                        className="text-xs text-gray-400 hover:text-red-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  </td>
                </tr>
              );
            })}
            {!(data?.providers || []).length && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-xs text-gray-400">
                  尚未配置搜索工具。调研 Agent 需要至少一个可用的搜索来源。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
