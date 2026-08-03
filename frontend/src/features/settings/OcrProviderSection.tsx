import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Loader2,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Star,
} from 'lucide-react';
import { ocrConfig } from '../../lib/api';
import type { OcrConfigOverview, OcrProviderConfig } from '../../types/api';
import { Th, Td } from './shared';

/** OCR 是第三方 HTTP 服务，不绑模型节点，也不使用 Prompt。 */
export default function OcrProviderSection() {
  const [data, setData] = useState<OcrConfigOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<OcrProviderConfig | 'new' | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState('Doc2X');
  const [adapter, setAdapter] = useState('doc2x');
  const [baseUrl, setBaseUrl] = useState('https://v2.doc2x.noedgeai.com');
  const [model, setModel] = useState('v3-2026');
  const [apiKey, setApiKey] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await ocrConfig.overview());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取 OCR 配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const beginCreate = () => {
    setName('Doc2X');
    setAdapter('doc2x');
    setBaseUrl(data?.base_url || 'https://v2.doc2x.noedgeai.com');
    setModel(data?.model || 'v3-2026');
    setApiKey('');
    setEditing('new');
  };

  const beginEdit = (provider: OcrProviderConfig) => {
    setName(provider.provider_name);
    setAdapter(provider.adapter);
    setBaseUrl(provider.base_url || '');
    setModel(provider.model);
    setApiKey('');
    setEditing(provider);
  };

  const closeEditor = () => {
    setEditing(null);
    setApiKey('');
  };

  const save = async () => {
    if (!editing || !name.trim() || !baseUrl.trim() || !model.trim()) return;
    const isNew = editing === 'new';
    if (isNew && !apiKey.trim()) {
      setError('新增 OCR 配置时必须填写 API Key。');
      return;
    }
    if (apiKey.trim() && !data?.direct_key_encryption_configured) {
      setError('尚未配置 MODEL_SECRET_ENCRYPTION_KEY，无法加密保存新 Key。');
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        await ocrConfig.create({
          provider_name: name.trim(),
          adapter,
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim(),
        });
      } else {
        await ocrConfig.update(editing.id, {
          provider_name: name.trim(),
          adapter,
          base_url: baseUrl.trim(),
          model: model.trim(),
          extra_config_json: editing.extra_config_json,
          ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        });
      }
      closeEditor();
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存 OCR 配置失败');
    } finally {
      setSaving(false);
    }
  };

  const deactivate = async (provider: OcrProviderConfig) => {
    if (!window.confirm(`停用「${provider.provider_name}」？停用后 OCR 将切换到其他启用配置或环境变量兜底。`)) return;
    setPending(provider.id);
    try {
      await ocrConfig.deactivate(provider.id);
      await load();
    } catch (deactivateError) {
      setError(deactivateError instanceof Error ? deactivateError.message : '停用 OCR 配置失败');
    } finally {
      setPending(null);
    }
  };

  const activate = async (provider: OcrProviderConfig, makeDefault = false) => {
    setPending(provider.id);
    try {
      await ocrConfig.update(provider.id, {
        is_active: true,
        ...(makeDefault || !(data?.providers || []).some((item) => item.is_active)
          ? { is_default: true }
          : {}),
      });
      await load();
    } catch (activateError) {
      setError(activateError instanceof Error ? activateError.message : '启用 OCR 配置失败');
    } finally {
      setPending(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 border border-gray-200 bg-white px-4 py-3 text-xs text-gray-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        加载 OCR 配置…
      </div>
    );
  }
  if (!data) return <p className="text-xs text-red-600">{error || '读取 OCR 配置失败'}</p>;

  const providers = data.providers || [];
  const isNew = editing === 'new';
  const realAdapters = data.adapters.filter((item) => item !== 'skeleton');
  const adapterOptions = realAdapters.includes(adapter) ? realAdapters : [adapter, ...realAdapters];
  const canSave = Boolean(
    editing
    && name.trim()
    && baseUrl.trim()
    && model.trim()
    && !saving
    && (!isNew || (apiKey.trim() && data.direct_key_encryption_configured))
    && (!apiKey.trim() || data.direct_key_encryption_configured),
  );

  return (
    <section>
      <div className="mb-3 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">OCR 服务</h2>
          <p className="mt-1 text-xs text-gray-500">扫描 PDF 的文字识别服务。Key 加密保存且永不回显。</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void load()} className="icon-button" title="刷新"><RefreshCw className="h-4 w-4" /></button>
          <button type="button" onClick={beginCreate} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white">
            <Plus className="h-4 w-4" />新增 OCR 配置
          </button>
        </div>
      </div>

      {!data.direct_key_encryption_configured ? (
        <p className="mb-2 flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          尚未配置 MODEL_SECRET_ENCRYPTION_KEY，不能新增或替换直接录入的 Key。
        </p>
      ) : null}
      {error ? <p className="mb-2 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p> : null}

      <div className={`mb-3 flex items-center gap-2 border px-3 py-2 text-xs ${data.configured ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
        {data.configured ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertCircle className="h-4 w-4 shrink-0" />}
        <span>
          当前生效：{data.source === 'database' ? data.provider_name || data.adapter : '环境变量兜底'} · {data.configured ? '配置完整' : '未配置真实 OCR 服务'}
        </span>
      </div>

      {editing ? (
        <div className="mb-3 grid gap-2 border border-gray-200 bg-gray-50 p-3 sm:grid-cols-2">
          <div className="sm:col-span-2 text-xs font-medium text-gray-700">
            {isNew ? '新增 OCR 配置' : `编辑 · ${editing.provider_name}`}
          </div>
          <label className="text-xs text-gray-600">
            配置名称
            <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-gray-600">
            适配器
            <select value={adapter} onChange={(event) => setAdapter(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 text-sm">
              {adapterOptions.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-600">
            Base URL
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm" />
          </label>
          <label className="text-xs text-gray-600">
            模型 / 版本
            <input value={model} onChange={(event) => setModel(event.target.value)} className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm" />
          </label>
          <label className="text-xs text-gray-600 sm:col-span-2">
            {isNew ? 'API Key' : 'API Key（留空则不修改）'}
            <input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={isNew ? '输入 Doc2X API Key' : '已保存，输入新值可替换'}
              className="mt-1 w-full border border-gray-200 px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <div className="flex items-center gap-2 sm:col-span-2">
            <button type="button" disabled={!canSave} onClick={() => void save()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-40">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存
            </button>
            <button type="button" onClick={closeEditor} className="text-xs text-gray-500">取消</button>
          </div>
        </div>
      ) : null}

      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[940px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr><Th>配置名称</Th><Th>适配器</Th><Th>Base URL</Th><Th>模型 / 版本</Th><Th>Key</Th><Th>状态</Th><Th>操作</Th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {providers.map((provider) => {
              const isEffective = data.source === 'database' && data.provider_config_id === provider.id;
              return (
                <tr key={provider.id} className={provider.is_active ? '' : 'bg-gray-50/60 text-gray-500'}>
                  <Td><span className="font-medium text-gray-900">{provider.provider_name}</span></Td>
                  <Td><span className="font-mono text-xs">{provider.adapter}</span></Td>
                  <Td clamp>{provider.base_url || '-'}</Td>
                  <Td><span className="font-mono text-xs">{provider.model || '-'}</span></Td>
                  <Td>{provider.key_display}</Td>
                  <Td>{isEffective ? <span className="text-emerald-700">当前使用</span> : provider.is_active ? '已启用' : '已停用'}</Td>
                  <Td>
                    <span className="flex items-center gap-3 whitespace-nowrap">
                      <button type="button" onClick={() => beginEdit(provider)} className="inline-flex items-center gap-1 text-xs text-brand-700"><Pencil className="h-3.5 w-3.5" />编辑</button>
                      {provider.is_active ? (
                        <>
                          {!isEffective ? <button type="button" disabled={pending === provider.id} onClick={() => void activate(provider, true)} className="inline-flex items-center gap-1 text-xs text-gray-600 disabled:opacity-40"><Star className="h-3.5 w-3.5" />设为当前</button> : null}
                          <button type="button" disabled={pending === provider.id} onClick={() => void deactivate(provider)} className="inline-flex items-center gap-1 text-xs text-gray-500 disabled:opacity-40"><Power className="h-3.5 w-3.5" />停用</button>
                        </>
                      ) : (
                        <button type="button" disabled={pending === provider.id} onClick={() => void activate(provider, true)} className="inline-flex items-center gap-1 text-xs text-brand-700 disabled:opacity-40"><RotateCcw className="h-3.5 w-3.5" />重新启用</button>
                      )}
                    </span>
                  </Td>
                </tr>
              );
            })}
            {providers.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs text-gray-400">尚未保存 OCR 配置。当前使用环境变量兜底。</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-xs text-gray-400">
        上传超时 {data.upload_timeout_seconds}s · 轮询间隔 {data.poll_interval_seconds}s · 最长等待 {data.max_wait_seconds}s（仍由部署环境调节）。
      </p>
      {data.source === 'environment' ? (
        <p className="mt-1 text-xs text-amber-700">
          当前状态来自 API 服务的环境变量；保存数据库配置后，API 与 worker-ocr 会读取同一条配置，无需为更换 OCR Key 重新部署。
        </p>
      ) : null}
      <p className="mt-1 text-xs text-gray-400">
        带文字层的 PDF 和 Office 文件在本地提取；扫描 PDF 才调用 OCR；图片直接交给多模态模型。
      </p>
    </section>
  );
}
