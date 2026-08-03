import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Loader2,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Star,
  Zap,
} from 'lucide-react';
import { searchConfig } from '../../lib/api';
import type {
  SearchConfigOverview,
  SearchProviderConfig,
  SearchProviderTestResult,
} from '../../types/api';

/** 调研 Agent 的检索来源。Key 经 Fernet 加密存库，接口只返回配置状态。 */
export default function SearchProviderSection() {
  const [data, setData] = useState<SearchConfigOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<SearchProviderConfig | 'new' | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
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

  const beginCreate = () => {
    setName('Tavily');
    setAdapter(data?.available_adapters[0] || 'tavily');
    setBaseUrl('https://api.tavily.com');
    setApiKey('');
    setEditing('new');
  };

  const beginEdit = (provider: SearchProviderConfig) => {
    setName(provider.provider_name);
    setAdapter(provider.adapter);
    setBaseUrl(provider.base_url || '');
    setApiKey('');
    setEditing(provider);
  };

  const closeEditor = () => {
    setEditing(null);
    setApiKey('');
  };

  const save = async () => {
    if (!editing || !name.trim() || !baseUrl.trim()) return;
    const isNew = editing === 'new';
    if (isNew && !apiKey.trim()) {
      setError('新增搜索工具时必须填写 API Key。');
      return;
    }
    if (apiKey.trim() && !data?.direct_key_encryption_configured) {
      setError('尚未配置 MODEL_SECRET_ENCRYPTION_KEY，无法加密保存新 Key。');
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        await searchConfig.create({
          provider_name: name.trim(),
          adapter,
          base_url: baseUrl.trim(),
          secret_mode: 'direct',
          api_key: apiKey.trim(),
        });
      } else {
        await searchConfig.update(editing.id, {
          provider_name: name.trim(),
          adapter,
          base_url: baseUrl.trim(),
          extra_config_json: editing.extra_config_json,
          ...(apiKey.trim() ? { secret_mode: 'direct' as const, api_key: apiKey.trim() } : {}),
        });
        setTestResult((current) => {
          const next = { ...current };
          delete next[editing.id];
          return next;
        });
      }
      closeEditor();
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

  const deactivate = async (provider: SearchProviderConfig) => {
    if (!window.confirm(`停用「${provider.provider_name}」？停用后调研 Agent 不再使用该配置。`)) return;
    setPending(provider.id);
    try {
      await searchConfig.remove(provider.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '停用失败');
    } finally {
      setPending(null);
    }
  };

  const reactivate = async (provider: SearchProviderConfig) => {
    setPending(provider.id);
    try {
      await searchConfig.update(provider.id, { is_active: true });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新启用失败');
    } finally {
      setPending(null);
    }
  };

  const makeDefault = async (provider: SearchProviderConfig) => {
    setPending(provider.id);
    try {
      await searchConfig.update(provider.id, { is_active: true, is_default: true });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换搜索工具失败');
    } finally {
      setPending(null);
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

  const encryptionReady = Boolean(data?.direct_key_encryption_configured);
  const providers = data?.providers || [];
  const activeProviders = providers.filter((provider) => provider.is_active);
  const effectiveId = activeProviders.find((provider) => provider.is_default)?.id || activeProviders[0]?.id;
  const isNew = editing === 'new';
  const canSave = Boolean(
    editing
    && name.trim()
    && baseUrl.trim()
    && !saving
    && (!isNew || (apiKey.trim() && encryptionReady))
    && (!apiKey.trim() || encryptionReady),
  );

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
            onClick={beginCreate}
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
            尚未配置 <code className="font-mono">MODEL_SECRET_ENCRYPTION_KEY</code>，不能新增或替换直接录入的 Key。
          </span>
        </p>
      )}
      {error && <p className="mb-2 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}

      {editing && (
        <div className="mb-3 grid gap-2 border border-gray-200 bg-gray-50 p-3 sm:grid-cols-2">
          <div className="sm:col-span-2 text-xs font-medium text-gray-700">
            {isNew ? '新增搜索工具' : `编辑 · ${editing.provider_name}`}
          </div>
          <label className="text-xs text-gray-600">
            配置名称
            <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-gray-600">
            适配器
            <select value={adapter} onChange={(event) => setAdapter(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 text-sm">
              {(data?.available_adapters || []).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-600">
            Base URL
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm" />
          </label>
          <label className="text-xs text-gray-600">
            {isNew ? 'API Key' : 'API Key（留空则不修改）'}
            <input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={isNew ? '输入 API Key' : '已保存，输入新值可替换'}
              className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <div className="flex items-center gap-2 sm:col-span-2">
            <button type="button" disabled={!canSave} onClick={() => void save()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-40">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              保存
            </button>
            <button type="button" onClick={closeEditor} className="text-xs text-gray-500">取消</button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[900px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr>
              <th className="px-3 py-2 font-medium">配置名称</th>
              <th className="px-3 py-2 font-medium">适配器</th>
              <th className="px-3 py-2 font-medium">Base URL</th>
              <th className="px-3 py-2 font-medium">Key</th>
              <th className="px-3 py-2 font-medium">状态</th>
              <th className="px-3 py-2 font-medium">连通性</th>
              <th className="px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {providers.map((provider) => {
              const result = testResult[provider.id];
              const isEffective = provider.id === effectiveId;
              return (
                <tr key={provider.id} className={provider.is_active ? '' : 'bg-gray-50/60 text-gray-500'}>
                  <td className="px-3 py-2 font-medium text-gray-900">{provider.provider_name}</td>
                  <td className="px-3 py-2 font-mono text-xs">{provider.adapter}</td>
                  <td className="max-w-[260px] truncate px-3 py-2 text-xs text-gray-500" title={provider.base_url || ''}>{provider.base_url || '-'}</td>
                  <td className="px-3 py-2 text-xs">{provider.key_display}</td>
                  <td className="px-3 py-2 text-xs">
                    {isEffective ? <span className="text-emerald-700">当前使用</span> : provider.is_active ? '已启用' : '已停用'}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {result ? result.status === 'succeeded'
                      ? <span className="text-emerald-700">通过 · {result.result_count} 条</span>
                      : <span className="text-red-600" title={result.error_message || ''}>失败</span>
                      : <span className="text-gray-300">未测试</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-3 whitespace-nowrap">
                      <button type="button" onClick={() => beginEdit(provider)} className="inline-flex items-center gap-1 text-xs text-brand-700">
                        <Pencil className="h-3.5 w-3.5" />编辑
                      </button>
                      {provider.is_active ? (
                        <>
                          <button type="button" disabled={testing === provider.id} onClick={() => void runTest(provider.id)} className="inline-flex items-center gap-1 text-xs text-brand-700 disabled:opacity-40">
                            {testing === provider.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}测试
                          </button>
                          {!isEffective && (
                            <button type="button" disabled={pending === provider.id} onClick={() => void makeDefault(provider)} className="inline-flex items-center gap-1 text-xs text-gray-600 disabled:opacity-40">
                              <Star className="h-3.5 w-3.5" />设为当前
                            </button>
                          )}
                          <button type="button" disabled={pending === provider.id} onClick={() => void deactivate(provider)} className="inline-flex items-center gap-1 text-xs text-gray-500 disabled:opacity-40">
                            <Power className="h-3.5 w-3.5" />停用
                          </button>
                        </>
                      ) : (
                        <button type="button" disabled={pending === provider.id} onClick={() => void reactivate(provider)} className="inline-flex items-center gap-1 text-xs text-brand-700 disabled:opacity-40">
                          <RotateCcw className="h-3.5 w-3.5" />重新启用
                        </button>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
            {providers.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs text-gray-400">尚未配置搜索工具。调研 Agent 需要至少一个可用的搜索来源。</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
