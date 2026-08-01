import { useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Loader2, Pencil, Plus, RefreshCw, TestTube2 } from 'lucide-react';
import OcrProviderSection from './OcrProviderSection';
import SearchProviderSection from './SearchProviderSection';
import { modelConfig } from '../../lib/api';
import type { ModelConnectionTestResult, ModelNodeConfig, ModelProviderConfig } from '../../types/api';
import { Editor, Field, Grid, SaveButton, SegmentButton, Th, Td } from './shared';

export default function ModelSection({
  providers,
  nodes,
  directKeyAvailable,
  onRefresh,
}: {
  providers: ModelProviderConfig[];
  nodes: ModelNodeConfig[];
  directKeyAvailable: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<ModelProviderConfig | 'new' | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  // 删除前要能看见有没有节点在用它 —— 这个信息以前完全缺失。
  const usageByProvider = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const node of nodes) {
      if (!node.provider_config_id) continue;
      counts[node.provider_config_id] = (counts[node.provider_config_id] || 0) + 1;
    }
    return counts;
  }, [nodes]);

  const chatModels = providers.filter((model) => model.provider_type !== 'search');
  const active = chatModels.filter((model) => model.is_active);
  const inactive = chatModels.filter((model) => !model.is_active);

  const deactivate = async (model: ModelProviderConfig) => {
    // 接口本来就是停用（deactivate_provider），历史上按钮却写「删除」，
    // 于是被停用的配置从列表消失，管理员以为删掉了。文案必须说实话。
    if (!window.confirm(`停用「${model.provider_name}」？停用后不再可选，历史调用记录保留，可随时重新启用。`)) return;
    setPendingId(model.id);
    try {
      await modelConfig.deleteModel(model.id);
      await onRefresh();
    } catch (error) {
      alert(error instanceof Error ? error.message : '停用模型配置失败');
    } finally {
      setPendingId(null);
    }
  };

  const remove = async (model: ModelProviderConfig) => {
    if (!window.confirm(`彻底删除「${model.provider_name}」？此操作不可撤销。

仅当没有节点引用、也没有历史调用记录时才能删除。`)) return;
    setPendingId(model.id);
    try {
      await modelConfig.deleteModelPermanently(model.id);
      await onRefresh();
    } catch (error) {
      alert(error instanceof Error ? error.message : '删除模型配置失败');
    } finally {
      setPendingId(null);
    }
  };

  const reactivate = async (model: ModelProviderConfig) => {
    setPendingId(model.id);
    try {
      await modelConfig.updateModel(model.id, { is_active: true });
      await onRefresh();
    } catch (error) {
      alert(error instanceof Error ? error.message : '重新启用失败');
    } finally {
      setPendingId(null);
    }
  };

  return (
    <div className="space-y-7">
      <section>
        <div className="mb-3 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">模型配置</h2>
            <p className="mt-1 text-xs text-gray-500">一个配置对应一个可调用模型。直接录入的 Key 加密保存且永不回显。</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void onRefresh()} className="icon-button" title="刷新"><RefreshCw className="h-4 w-4" /></button>
            <button type="button" onClick={() => setEditing('new')} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white">
              <Plus className="h-4 w-4" />新增模型
            </button>
          </div>
        </div>
        <div className="overflow-x-auto border border-gray-200 bg-white">
          <table className="min-w-[900px] text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500">
              <tr><Th>配置名称</Th><Th>模型名称</Th><Th>Base URL</Th><Th>Key</Th><Th>被引用</Th><Th>操作</Th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {active.map((model) => (
                <tr key={model.id}>
                  <Td><span className="font-medium text-gray-900">{model.provider_name}</span></Td>
                  <Td><span className="font-mono text-xs">{model.model_name}</span></Td>
                  <Td clamp>{model.base_url || '-'}</Td>
                  <Td>{model.key_display}</Td>
                  <Td>{usageByProvider[model.id] ? `${usageByProvider[model.id]} 个节点` : <span className="text-gray-400">未引用</span>}</Td>
                  <Td>
                    <div className="flex items-center gap-3">
                      <button type="button" onClick={() => setEditing(model)} className="inline-flex items-center gap-1 text-xs text-brand-700"><Pencil className="h-3.5 w-3.5" />配置</button>
                      <button type="button" onClick={() => void deactivate(model)} disabled={pendingId === model.id} className="inline-flex items-center gap-1 text-xs text-gray-600 disabled:text-gray-300">
                        {pendingId === model.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}停用
                      </button>
                    </div>
                  </Td>
                </tr>
              ))}
              {active.length === 0 ? <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-400">暂无可用模型配置</td></tr> : null}

              {inactive.length > 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-2">
                    <button type="button" onClick={() => setShowInactive((value) => !value)} className="inline-flex items-center gap-1 text-xs text-gray-500">
                      {showInactive ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      已停用（{inactive.length}）
                    </button>
                  </td>
                </tr>
              ) : null}
              {showInactive
                ? inactive.map((model) => (
                  <tr key={model.id} className="bg-gray-50/60 text-gray-500">
                    <Td>{model.provider_name}</Td>
                    <Td><span className="font-mono text-xs">{model.model_name}</span></Td>
                    <Td clamp>{model.base_url || '-'}</Td>
                    <Td>{model.key_display}</Td>
                    <Td>{usageByProvider[model.id] ? `${usageByProvider[model.id]} 个节点` : <span className="text-gray-400">未引用</span>}</Td>
                    <Td>
                      <div className="flex items-center gap-3">
                        <button type="button" onClick={() => void reactivate(model)} disabled={pendingId === model.id} className="text-xs text-brand-700 disabled:text-gray-300">
                          {pendingId === model.id ? '处理中...' : '重新启用'}
                        </button>
                        <button type="button" onClick={() => void remove(model)} disabled={pendingId === model.id} className="text-xs text-red-600 disabled:text-gray-300">
                          删除
                        </button>
                      </div>
                    </Td>
                  </tr>
                ))
                : null}
            </tbody>
          </table>
        </div>
      </section>

      <SearchProviderSection />

      <OcrProviderSection />

      {editing ? (
        <ModelEditor
          model={editing === 'new' ? null : editing}
          directKeyAvailable={directKeyAvailable}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await onRefresh(); }}
        />
      ) : null}
    </div>
  );
}

interface ModelDraft {
  providerName: string;
  modelName: string;
  baseUrl: string;
  secretMode: 'env' | 'direct';
  keyReference: string;
  apiKey: string;
}

function ModelEditor({
  model,
  directKeyAvailable,
  onClose,
  onSaved,
}: {
  model: ModelProviderConfig | null;
  directKeyAvailable: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<ModelDraft>({
    providerName: model?.provider_name || '',
    modelName: model?.model_name || '',
    baseUrl: model?.base_url || '',
    secretMode: model?.secret_mode || 'env',
    keyReference: model?.api_key_secret_ref || '',
    apiKey: '',
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelConnectionTestResult | null>(null);
  const [connectionTestPassed, setConnectionTestPassed] = useState(false);

  const updateConnectionDraft = (patch: Partial<ModelDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setConnectionTestPassed(false);
    setTestResult(null);
  };

  const hasConnectionFields = Boolean(
    draft.modelName.trim()
    && draft.baseUrl.trim()
    && (draft.secretMode === 'env'
      ? draft.keyReference.trim()
      : draft.apiKey.trim() || (model?.secret_mode === 'direct' && model.secret_configured)),
  );

  const save = async () => {
    if (!draft.providerName.trim() || !draft.modelName.trim() || !draft.baseUrl.trim()) {
      alert('请填写配置名称、模型名称和 Base URL。');
      return;
    }
    if (draft.secretMode === 'env' && !draft.keyReference.trim()) {
      alert('请填写 Key 环境变量名。');
      return;
    }
    if (draft.secretMode === 'direct' && !model && !draft.apiKey.trim()) {
      alert('请填写 API Key。');
      return;
    }
    if (draft.secretMode === 'direct' && !directKeyAvailable) {
      alert('请先在 API 和 LLM Worker 服务中配置 MODEL_SECRET_ENCRYPTION_KEY。');
      return;
    }
    if (!connectionTestPassed) {
      alert('请先测试当前模型配置，连接成功后才能保存。');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        provider_name: draft.providerName.trim(),
        model_name: draft.modelName.trim(),
        base_url: draft.baseUrl.trim().replace(/\/$/, ''),
        secret_mode: draft.secretMode,
        api_key_secret_ref: draft.secretMode === 'env' ? draft.keyReference.trim() : null,
        ...(draft.secretMode === 'direct' && draft.apiKey.trim() ? { api_key: draft.apiKey.trim() } : {}),
      };
      if (model) await modelConfig.updateModel(model.id, payload);
      else await modelConfig.createModel(payload);
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '保存模型配置失败');
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!hasConnectionFields) {
      alert('请先填写模型名称、Base URL 和 Key 配置。');
      return;
    }
    if (draft.secretMode === 'direct' && !directKeyAvailable) {
      alert('请先在 API 和 LLM Worker 服务中配置 MODEL_SECRET_ENCRYPTION_KEY。');
      return;
    }
    setTesting(true);
    setTestResult(null);
    setConnectionTestPassed(false);
    try {
      const result = await modelConfig.testModelDraft({
        provider_config_id: model?.id || null,
        model_name: draft.modelName.trim(),
        base_url: draft.baseUrl.trim().replace(/\/$/, ''),
        secret_mode: draft.secretMode,
        api_key_secret_ref: draft.secretMode === 'env' ? draft.keyReference.trim() : null,
        ...(draft.secretMode === 'direct' && draft.apiKey.trim() ? { api_key: draft.apiKey.trim() } : {}),
      });
      setTestResult(result);
      setConnectionTestPassed(result.status === 'succeeded');
    } catch (testError) {
      setTestResult({
        status: 'failed', model_name: draft.modelName.trim(), latency_ms: null, prompt_tokens: null,
        completion_tokens: null, total_tokens: null, output_preview: null,
        error_code: 'request_failed', error_message: testError instanceof Error ? testError.message : '测试失败',
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Editor
      title={model ? '配置模型' : '新增模型'}
      onClose={onClose}
      footer={(
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void test()} disabled={!hasConnectionFields || testing} className="inline-flex items-center gap-1.5 border border-gray-300 px-4 py-2 text-sm text-gray-700 disabled:opacity-40">
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <TestTube2 className="h-4 w-4" />}测试连接
          </button>
          <SaveButton saving={saving} onClick={save} disabled={!connectionTestPassed} />
        </div>
      )}
    >
      <Grid>
        <Field label="配置名称"><input className="input" placeholder="例如：通义千问主模型" value={draft.providerName} onChange={(event) => setDraft({ ...draft, providerName: event.target.value })} /></Field>
        <Field label="模型名称"><input className="input font-mono" placeholder="例如：qwen-plus" value={draft.modelName} onChange={(event) => updateConnectionDraft({ modelName: event.target.value })} /></Field>
      </Grid>
      <Field label="Base URL"><input className="input font-mono" placeholder="https://example.com/v1" value={draft.baseUrl} onChange={(event) => updateConnectionDraft({ baseUrl: event.target.value })} /></Field>
      <Field label="Key 保存方式">
        <div className="inline-flex border border-gray-300 p-0.5">
          <SegmentButton active={draft.secretMode === 'env'} onClick={() => updateConnectionDraft({ secretMode: 'env' })}>环境变量</SegmentButton>
          <SegmentButton active={draft.secretMode === 'direct'} onClick={() => updateConnectionDraft({ secretMode: 'direct' })}>直接录入</SegmentButton>
        </div>
      </Field>
      {draft.secretMode === 'env' ? (
        <Field label="Key 环境变量名"><input className="input font-mono" placeholder="例如：ALIYUN_API_KEY" value={draft.keyReference} onChange={(event) => updateConnectionDraft({ keyReference: event.target.value.toUpperCase() })} /></Field>
      ) : (
        <Field
          label={model?.secret_configured ? 'API Key（留空则不修改）' : 'API Key'}
          hint="保存后仅保留加密密文，页面和接口均不回显原始 Key。"
        >
          <input className="input font-mono" type="password" autoComplete="new-password" placeholder={model?.secret_configured ? '已加密保存，输入新值可替换' : '输入 API Key'} value={draft.apiKey} onChange={(event) => updateConnectionDraft({ apiKey: event.target.value })} />
          {!directKeyAvailable ? <p className="mt-1 text-xs text-amber-700">尚未配置 MODEL_SECRET_ENCRYPTION_KEY，直接录入模式暂不可保存。</p> : null}
        </Field>
      )}
      <p className="text-xs text-gray-400">请先测试连接；测试成功后才可保存。修改连接参数后需要重新测试。</p>
      {testResult ? <ModelTestResult result={testResult} /> : null}
    </Editor>
  );
}

function ModelTestResult({ result }: { result: ModelConnectionTestResult }) {
  const succeeded = result.status === 'succeeded';
  return (
    <div className={`border px-4 py-3 text-sm ${succeeded ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-red-200 bg-red-50 text-red-700'}`}>
      <div className="flex items-center gap-2 font-medium">
        {succeeded ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
        {succeeded ? '连接成功' : '连接失败'}
      </div>
      {succeeded
        ? <p className="mt-1 text-xs">耗时 {result.latency_ms ?? '-'} ms · Token {result.total_tokens ?? '-'}</p>
        : <p className="mt-1 break-all text-xs">{result.error_message || result.error_code || '未知错误'}</p>}
    </div>
  );
}
