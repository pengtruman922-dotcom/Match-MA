import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Database,
  Download,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  TestTube2,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import SearchProviderSection from '../features/settings/SearchProviderSection';
import { dataDictionaries, modelConfig } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type {
  IndustryDictionaryImportResult,
  IndustryDictionaryTerm,
  ModelConfigSettingsPage,
  ModelConnectionTestResult,
  ModelNodeConfig,
  ModelProviderConfig,
  PromptTemplateConfig,
} from '../types/api';

type SettingsTab = 'ai' | 'dictionary';

const NODE_LABELS: Record<string, string> = {
  seller_target_parser: '标的新建解析',
  seller_target_update_parser: '标的更新解析',
  buyer_intent_parser: '买家新建解析',
  buyer_intent_update_parser: '买家基本信息更新解析',
  relation_followup_draft_parser: '推进跟进整理',
  seller_target_researcher: '标的 AI 调研',
  seller_target_research_mapper: '调研结果规范化',
  recommendation_deep_eval: '推荐深度评估',
  recommendation_report_writer: '推荐报告生成',
  ocr_attachment_parser: '附件 OCR',
  business_update_extractor: '混合更新兼容节点',
};

const HIDDEN_RETIRED_NODES = new Set(['embedding_seller_doc', 'embedding_buyer_intent', 'recommendation_reranker']);

export default function Settings() {
  const [tab, setTab] = useState<SettingsTab>('ai');
  if (!isAdmin()) {
    return <div className="border border-gray-200 bg-white px-5 py-10 text-center text-sm text-gray-500">设置仅管理员可见。</div>;
  }
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">设置</h1>
        <p className="mt-1 text-xs text-gray-500">管理 AI 业务节点、Prompt 版本和平台数据字典。</p>
      </header>
      <div className="flex border-b border-gray-200">
        <TabButton active={tab === 'ai'} onClick={() => setTab('ai')} icon={<Settings2 className="h-4 w-4" />}>AI 设置</TabButton>
        <TabButton active={tab === 'dictionary'} onClick={() => setTab('dictionary')} icon={<Database className="h-4 w-4" />}>数据字典</TabButton>
      </div>
      {tab === 'ai' ? <AiSettings /> : <IndustryDictionary />}
    </div>
  );
}

function AiSettings() {
  const [data, setData] = useState<ModelConfigSettingsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingNode, setEditingNode] = useState<ModelNodeConfig | null>(null);
  const [editingModel, setEditingModel] = useState<ModelProviderConfig | 'new' | null>(null);
  const [promptNode, setPromptNode] = useState<ModelNodeConfig | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await modelConfig.settingsPage());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取 AI 设置失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const removeModel = async (model: ModelProviderConfig) => {
    if (!window.confirm(`确定删除模型配置“${model.provider_name}”吗？`)) return;
    setDeletingId(model.id);
    try {
      await modelConfig.deleteModel(model.id);
      await load();
    } catch (removeError) {
      alert(removeError instanceof Error ? removeError.message : '删除模型配置失败');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error || '读取 AI 设置失败'} onRetry={load} />;

  const nodes = data.nodes.filter((node) => !HIDDEN_RETIRED_NODES.has(node.node_name) && ['llm', 'parser', 'research'].includes(node.node_type));
  const models = data.providers.filter((model) => model.is_active && model.provider_type !== 'search' && !isRetiredModel(model));
  return (
    <div className="space-y-7">
      <section>
        <div className="mb-3 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">模型配置</h2>
            <p className="mt-1 text-xs text-gray-500">一个配置对应一个可调用模型。直接录入的 Key 加密保存且永不回显。</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void load()} className="icon-button" title="刷新"><RefreshCw className="h-4 w-4" /></button>
            <button type="button" onClick={() => setEditingModel('new')} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white">
              <Plus className="h-4 w-4" />新增模型
            </button>
          </div>
        </div>
        <div className="overflow-x-auto border border-gray-200 bg-white">
          <table className="min-w-[880px] text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500"><tr><Th>配置名称</Th><Th>模型名称</Th><Th>Base URL</Th><Th>Key</Th><Th>状态</Th><Th>操作</Th></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {models.map((model) => (
                <tr key={model.id}>
                  <Td><span className="font-medium text-gray-900">{model.provider_name}</span></Td>
                  <Td><span className="font-mono text-xs">{model.model_name}</span></Td>
                  <Td clamp>{model.base_url || '-'}</Td>
                  <Td>{model.key_display}</Td>
                  <Td><Status active={model.is_active} /></Td>
                  <Td>
                    <div className="flex items-center gap-3">
                      <button type="button" onClick={() => setEditingModel(model)} className="inline-flex items-center gap-1 text-xs text-brand-700"><Pencil className="h-3.5 w-3.5" />配置</button>
                      <button type="button" onClick={() => void removeModel(model)} disabled={deletingId === model.id} className="inline-flex items-center gap-1 text-xs text-red-600 disabled:text-gray-300">
                        {deletingId === model.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}删除
                      </button>
                    </div>
                  </Td>
                </tr>
              ))}
              {models.length === 0 ? <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-400">暂无可用模型配置</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-gray-900">业务节点</h2>
          <p className="mt-1 text-xs text-gray-500">为每个业务流程选择模型，Prompt 在节点中独立维护。</p>
        </div>
        <div className="overflow-x-auto border border-gray-200 bg-white">
          <table className="min-w-[720px] text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500"><tr><Th>业务节点</Th><Th>当前模型</Th><Th>Prompt</Th><Th>操作</Th></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {nodes.map((node) => {
                const selectedModel = data.providers.find((item) => item.id === node.provider_config_id);
                return (
                  <tr key={node.id}>
                    <Td><div className="font-medium text-gray-900">{NODE_LABELS[node.node_name] || node.node_name}</div><div className="mt-0.5 font-mono text-[11px] text-gray-400">{node.node_name}</div></Td>
                    <Td><div>{selectedModel?.provider_name || node.provider_name || '-'}</div><div className="mt-0.5 font-mono text-xs text-gray-500">{selectedModel?.model_name || node.model_name}</div></Td>
                    <Td>{node.prompt_editable ? <button type="button" onClick={() => setPromptNode(node)} className="text-xs text-brand-700">{node.default_prompt?.version || '新建版本'}</button> : <span className="text-xs text-gray-400">无 Prompt</span>}</Td>
                    <Td><button type="button" onClick={() => setEditingNode(node)} className="inline-flex items-center gap-1 text-xs text-brand-700"><Pencil className="h-3.5 w-3.5" />配置</button></Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <SearchProviderSection />

      {editingModel ? (
        <ModelEditor
          model={editingModel === 'new' ? null : editingModel}
          directKeyAvailable={Boolean(data.capabilities.direct_key_encryption_configured)}
          onClose={() => setEditingModel(null)}
          onSaved={async () => { setEditingModel(null); await load(); }}
        />
      ) : null}
      {editingNode ? <NodeEditor node={editingNode} models={models} onClose={() => setEditingNode(null)} onSaved={async () => { setEditingNode(null); await load(); }} /> : null}
      {promptNode ? <PromptEditor node={promptNode} onClose={() => setPromptNode(null)} onSaved={async () => { setPromptNode(null); await load(); }} /> : null}
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

function ModelEditor({ model, directKeyAvailable, onClose, onSaved }: { model: ModelProviderConfig | null; directKeyAvailable: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
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
      alert('请先在 Railway API 和 LLM Worker 服务中配置 MODEL_SECRET_ENCRYPTION_KEY。');
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
      alert('请先在 Railway API 和 LLM Worker 服务中配置 MODEL_SECRET_ENCRYPTION_KEY。');
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
          <SegmentButton active={draft.secretMode === 'env'} onClick={() => updateConnectionDraft({ secretMode: 'env' })}>Railway 环境变量</SegmentButton>
          <SegmentButton active={draft.secretMode === 'direct'} onClick={() => updateConnectionDraft({ secretMode: 'direct' })}>直接录入</SegmentButton>
        </div>
      </Field>
      {draft.secretMode === 'env' ? (
        <Field label="Key 环境变量名"><input className="input font-mono" placeholder="例如：ALIYUN_API_KEY" value={draft.keyReference} onChange={(event) => updateConnectionDraft({ keyReference: event.target.value.toUpperCase() })} /></Field>
      ) : (
        <Field label={model?.secret_configured ? 'API Key（留空则不修改）' : 'API Key'}>
          <input className="input font-mono" type="password" autoComplete="new-password" placeholder={model?.secret_configured ? '已加密保存，输入新值可替换' : '输入 API Key'} value={draft.apiKey} onChange={(event) => updateConnectionDraft({ apiKey: event.target.value })} />
          <p className="mt-1 text-xs text-gray-400">保存后仅保留加密密文，页面和接口均不回显原始 Key。</p>
          {!directKeyAvailable ? <p className="mt-1 text-xs text-amber-700">Railway 尚未配置 MODEL_SECRET_ENCRYPTION_KEY，直接录入模式暂不可保存。</p> : null}
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
      <div className="flex items-center gap-2 font-medium">{succeeded ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}{succeeded ? '连接成功' : '连接失败'}</div>
      {succeeded ? <p className="mt-1 text-xs">耗时 {result.latency_ms ?? '-'} ms · Token {result.total_tokens ?? '-'}</p> : <p className="mt-1 break-all text-xs">{result.error_message || result.error_code || '未知错误'}</p>}
    </div>
  );
}

function NodeEditor({ node, models, onClose, onSaved }: { node: ModelNodeConfig; models: ModelProviderConfig[]; onClose: () => void; onSaved: () => Promise<void> }) {
  const [modelId, setModelId] = useState(node.provider_config_id);
  const [temperature, setTemperature] = useState<number | string | null>(node.temperature);
  const [topP, setTopP] = useState<number | string | null>(node.top_p);
  const [timeout, setTimeoutValue] = useState(node.timeout_seconds);
  const [advanced, setAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!modelId) {
      alert('请选择模型。');
      return;
    }
    setSaving(true);
    try {
      await modelConfig.updateNode(node.id, {
        provider_config_id: modelId,
        temperature: asNumber(temperature),
        top_p: asNumber(topP),
        timeout_seconds: timeout,
      });
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '保存业务节点失败');
    } finally {
      setSaving(false);
    }
  };
  return (
    <Editor title={NODE_LABELS[node.node_name] || node.node_name} onClose={onClose} footer={<SaveButton saving={saving} onClick={save} />}>
      <Field label="模型">
        <select className="input" value={modelId} onChange={(event) => setModelId(event.target.value)}>
          <option value="">请选择</option>
          {models.map((model) => <option key={model.id} value={model.id}>{model.provider_name} · {model.model_name}</option>)}
        </select>
      </Field>
      <button type="button" onClick={() => setAdvanced((value) => !value)} className="inline-flex items-center gap-1 text-xs text-gray-600">
        {advanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}高级参数
      </button>
      {advanced ? (
        <Grid>
          <Field label="Temperature"><input className="input" type="number" step="0.1" min="0" max="2" value={temperature ?? ''} onChange={(event) => setTemperature(event.target.value)} /></Field>
          <Field label="Top P"><input className="input" type="number" step="0.1" min="0" max="1" value={topP ?? ''} onChange={(event) => setTopP(event.target.value)} /></Field>
          <Field label="超时（秒）"><input className="input" type="number" min="1" max="3600" value={timeout} onChange={(event) => setTimeoutValue(Math.max(1, Number(event.target.value) || 60))} /></Field>
        </Grid>
      ) : null}
    </Editor>
  );
}

const PROMPT_VARIABLE_DESCRIPTIONS: Record<string, string> = {
  raw_requirement_text: '买家需求原文',
  buyer_profile_json: '买家画像 JSON',
  raw_target_text: '标的材料原文',
  target_context_json: '标的上下文 JSON',
  raw_text: '用户录入原文（含附件文本）',
  context_json: '业务更新上下文 JSON',
  industry_l1_list: '一级行业字典（渲染时自动注入当前启用清单）',
  mode: '推荐方向（buyer_to_target / target_to_buyer）',
  anchor_context: '推荐对象条件与画像文本',
  candidates_json: '候选清单 JSON',
  report_context_json: '报告上下文 JSON',
  selected_items_json: '已选推荐项 JSON',
};

function PromptEditor({ node, onClose, onSaved }: { node: ModelNodeConfig; onClose: () => void; onSaved: () => Promise<void> }) {
  const current = node.default_prompt;
  const [version, setVersion] = useState(nextVersion(current?.version));
  const [systemPrompt, setSystemPrompt] = useState(current?.system_prompt || '');
  const [userPrompt, setUserPrompt] = useState(current?.user_prompt_template || '');
  const [schema, setSchema] = useState(JSON.stringify(current?.output_schema_json || {}, null, 2));
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<PromptTemplateConfig[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [rollingBackId, setRollingBackId] = useState<string | null>(null);
  const [industryTerms, setIndustryTerms] = useState<IndustryDictionaryTerm[]>([]);
  const [preview, setPreview] = useState<{ system: string; user: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const userPromptRef = useRef<HTMLTextAreaElement | null>(null);

  const declaredVariables = Array.isArray(current?.variables_json)
    ? (current?.variables_json as unknown[]).filter((item): item is string => typeof item === 'string')
    : [];
  const templateVariables = Array.from(new Set([
    ...declaredVariables,
    ...extractVariableNames(systemPrompt),
    ...extractVariableNames(userPrompt),
  ]));

  useEffect(() => {
    dataDictionaries.industry({ level: 'l1' }).then(setIndustryTerms).catch(() => setIndustryTerms([]));
  }, []);

  const insertVariable = (name: string) => {
    const token = `{{ ${name} }}`;
    const textarea = userPromptRef.current;
    if (!textarea) {
      setUserPrompt((prev) => prev + token);
      return;
    }
    const start = textarea.selectionStart ?? userPrompt.length;
    const end = textarea.selectionEnd ?? userPrompt.length;
    const next = userPrompt.slice(0, start) + token + userPrompt.slice(end);
    setUserPrompt(next);
    window.setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start + token.length, start + token.length);
    }, 0);
  };

  const runPreview = async () => {
    setPreviewLoading(true);
    try {
      const result = await modelConfig.renderPromptPreview({
        system_prompt: systemPrompt,
        user_prompt_template: userPrompt,
      });
      setPreview({ system: result.rendered_system_prompt, user: result.rendered_user_prompt });
    } catch (previewError) {
      alert(previewError instanceof Error ? previewError.message : '渲染预览失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      setHistory(await modelConfig.listPrompts(node.node_name));
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [node.node_name]);
  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const save = async () => {
    let outputSchema: Record<string, unknown>;
    try { outputSchema = JSON.parse(schema) as Record<string, unknown>; } catch { alert('输出 Schema 不是合法 JSON'); return; }
    setSaving(true);
    try {
      await modelConfig.createPrompt({ node_name: node.node_name, version, name: `${NODE_LABELS[node.node_name] || node.node_name} ${version}`, system_prompt: systemPrompt, user_prompt_template: userPrompt, output_schema_json: outputSchema, template_engine: 'jinja', variables_json: current?.variables_json || [], is_active: true, is_default: true });
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '创建 Prompt 版本失败');
    } finally {
      setSaving(false);
    }
  };

  const loadIntoEditor = (item: PromptTemplateConfig) => {
    setSystemPrompt(item.system_prompt || '');
    setUserPrompt(item.user_prompt_template || '');
    setSchema(JSON.stringify(item.output_schema_json || {}, null, 2));
  };

  const rollbackTo = async (item: PromptTemplateConfig) => {
    if (!window.confirm(`将「${item.version}」设为当前版本？之后的解析任务会立即使用该版本。`)) return;
    setRollingBackId(item.id);
    try {
      await modelConfig.updatePrompt(item.id, { is_default: true, is_active: true });
      await loadHistory();
      await onSaved();
    } catch (rollbackError) {
      alert(rollbackError instanceof Error ? rollbackError.message : '切换版本失败');
    } finally {
      setRollingBackId(null);
    }
  };

  return (
    <Editor title="Prompt 版本管理" onClose={onClose} wide footer={<SaveButton saving={saving} onClick={save} label="保存为新版本并设为当前" />}>
      <div>
        <span className="mb-1 block text-xs font-medium text-gray-600">历史版本</span>
        {historyLoading ? (
          <p className="py-2 text-xs text-gray-400">正在加载版本历史...</p>
        ) : history.length === 0 ? (
          <p className="py-2 text-xs text-gray-400">暂无历史版本</p>
        ) : (
          <div className="max-h-40 overflow-y-auto border border-gray-200 divide-y divide-gray-100">
            {history.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <span className="font-medium text-gray-800">{item.version}</span>
                  {item.is_default ? <span className="ml-2 bg-emerald-50 px-1.5 py-0.5 text-emerald-700">当前版本</span> : null}
                  {!item.is_active ? <span className="ml-2 bg-gray-100 px-1.5 py-0.5 text-gray-500">已停用</span> : null}
                  <span className="ml-2 text-gray-400">{item.updated_at?.slice(0, 16).replace('T', ' ')}</span>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button type="button" onClick={() => loadIntoEditor(item)} className="text-brand-700 hover:underline">载入编辑</button>
                  {!item.is_default ? (
                    <button type="button" disabled={rollingBackId === item.id} onClick={() => void rollbackTo(item)} className="text-gray-600 hover:underline disabled:opacity-50">
                      {rollingBackId === item.id ? '切换中...' : '设为当前版本'}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="mt-1 text-[11px] text-gray-400">「载入编辑」把历史版本内容填入下方编辑器（保存时生成新版本）；「设为当前版本」直接回滚，立即生效。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
        <div className="space-y-4">
          <Field label="版本号"><input className="input" value={version} onChange={(event) => setVersion(event.target.value)} /></Field>
          <Field label="System Prompt"><textarea className="input min-h-28 resize-y font-mono text-xs" value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} /></Field>
          <Field label="User Prompt Template">
            <textarea ref={userPromptRef} className="input min-h-56 resize-y font-mono text-xs" value={userPrompt} onChange={(event) => setUserPrompt(event.target.value)} />
          </Field>
          <Field label="输出 Schema"><textarea className="input min-h-40 resize-y font-mono text-xs" value={schema} onChange={(event) => setSchema(event.target.value)} /></Field>
        </div>

        <div className="space-y-4">
          <div className="border border-gray-200 p-3">
            <p className="mb-2 text-xs font-medium text-gray-700">可用变量（点击插入到 User Prompt 光标处）</p>
            {templateVariables.length === 0 ? (
              <p className="text-[11px] text-gray-400">该节点暂无声明变量</p>
            ) : (
              <div className="space-y-1.5">
                {templateVariables.map((name) => (
                  <button
                    key={name}
                    type="button"
                    onClick={() => insertVariable(name)}
                    className="block w-full text-left text-[11px] leading-relaxed hover:bg-brand-50"
                  >
                    <code className="text-brand-700">{'{{ '}{name}{' }}'}</code>
                    <span className="ml-1 text-gray-500">{PROMPT_VARIABLE_DESCRIPTIONS[name] || ''}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="border border-gray-200 p-3">
            <p className="mb-2 text-xs font-medium text-gray-700">行业字典当前内容（{industryTerms.length} 项一级行业）</p>
            <div className="flex flex-wrap gap-1">
              {industryTerms.length === 0 ? (
                <p className="text-[11px] text-gray-400">暂无可用一级行业</p>
              ) : (
                industryTerms.map((item) => (
                  <span key={item.id} className="bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">{item.term}</span>
                ))
              )}
            </div>
            <p className="mt-2 text-[11px] text-gray-400">
              提示词里的 <code>{'{{ industry_l1_list }}'}</code> 渲染时会自动注入上述启用中的清单，改字典即时生效、无需改提示词。
            </p>
          </div>

          <div className="border border-amber-200 bg-amber-50 p-3 text-[11px] leading-relaxed text-amber-800">
            ⚠ few-shot 示例请直接写进左侧 User Prompt 正文；few_shot_examples_json 字段是历史遗留存储，<b>不会</b>注入给模型。
          </div>

          <button
            type="button"
            onClick={() => void runPreview()}
            disabled={previewLoading}
            className="inline-flex w-full items-center justify-center gap-1.5 border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50"
          >
            {previewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            渲染预览（查看模型实际收到的内容）
          </button>
        </div>
      </div>

      {preview ? (
        <div className="border border-gray-200">
          <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-2">
            <p className="text-xs font-medium text-gray-700">渲染预览（变量已代入；行业字典为真实内容，其余为示例占位）</p>
            <button type="button" onClick={() => setPreview(null)} className="text-xs text-gray-400 hover:text-gray-600">收起</button>
          </div>
          <div className="max-h-80 overflow-y-auto p-3 text-xs">
            {preview.system && (
              <>
                <p className="mb-1 font-medium text-gray-500">System:</p>
                <pre className="mb-3 whitespace-pre-wrap break-words font-mono text-[11px] text-gray-700">{preview.system}</pre>
              </>
            )}
            <p className="mb-1 font-medium text-gray-500">User:</p>
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-gray-700">{preview.user}</pre>
          </div>
        </div>
      ) : null}
    </Editor>
  );
}

function extractVariableNames(template: string): string[] {
  const names: string[] = [];
  const pattern = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(template)) !== null) {
    if (!names.includes(match[1])) names.push(match[1]);
  }
  return names;
}

function IndustryDictionary() {
  const [items, setItems] = useState<IndustryDictionaryTerm[]>([]);
  const [l1Options, setL1Options] = useState<IndustryDictionaryTerm[]>([]);
  const [q, setQ] = useState('');
  const [level, setLevel] = useState('');
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<IndustryDictionaryTerm | 'new' | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await dataDictionaries.industry({ q: q || undefined, level: level || undefined, include_inactive: true }));
    } catch (loadError) {
      alert(loadError instanceof Error ? loadError.message : '读取行业字典失败');
    } finally {
      setLoading(false);
    }
  }, [q, level]);
  const loadL1Options = useCallback(async () => {
    try {
      setL1Options(await dataDictionaries.industry({ level: 'l1', include_inactive: true }));
    } catch {
      setL1Options([]);
    }
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => { void loadL1Options(); }, [loadL1Options]);
  const toggle = async (item: IndustryDictionaryTerm) => {
    try {
      await dataDictionaries.updateIndustryTerm(item.id, { active: !item.active });
      await Promise.all([load(), loadL1Options()]);
    } catch (toggleError) {
      alert(toggleError instanceof Error ? toggleError.message : '更新状态失败');
    }
  };
  const downloadTemplate = async () => {
    try {
      const response = await dataDictionaries.industryImportTemplate();
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'industry_dictionary_template.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      alert(downloadError instanceof Error ? downloadError.message : '下载模板失败');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div><h2 className="text-sm font-semibold text-gray-900">行业字典</h2><p className="mt-1 text-xs text-gray-500">维护一级、二级标准行业及其别名。现有推荐召回规则保持不变。</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void downloadTemplate()} className="inline-flex items-center gap-1.5 border border-gray-300 px-3 py-2 text-sm text-gray-700"><Download className="h-4 w-4" />下载模板</button>
          <button type="button" onClick={() => setImporting(true)} className="inline-flex items-center gap-1.5 border border-gray-300 px-3 py-2 text-sm text-gray-700"><Upload className="h-4 w-4" />批量导入</button>
          <button type="button" onClick={() => setEditing('new')} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新增词条</button>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input className="input max-w-sm" placeholder="搜索标准行业或别名" value={q} onChange={(event) => setQ(event.target.value)} />
        <select className="input w-36" value={level} onChange={(event) => setLevel(event.target.value)}><option value="">全部层级</option><option value="l1">一级行业</option><option value="l2">二级行业</option></select>
      </div>
      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[920px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500"><tr><Th>标准行业</Th><Th>层级</Th><Th>所属一级行业</Th><Th>别名</Th><Th>使用量</Th><Th>状态</Th><Th>操作</Th></tr></thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? <tr><td colSpan={7}><Loading /></td></tr> : items.map((item) => (
              <tr key={item.id}>
                <Td><span className="font-medium text-gray-900">{item.term}</span></Td>
                <Td>{levelLabel(item.level)}</Td>
                <Td>{item.level === 'l1' ? '-' : item.parent_name || item.l1_name}</Td>
                <Td clamp><span title={item.aliases.map((alias) => alias.term).join('、')}>{item.aliases.filter((alias) => alias.active).map((alias) => alias.term).join('、') || '-'}</span></Td>
                <Td>{item.usage_count}</Td>
                <Td><Status active={item.active} /></Td>
                <Td><div className="flex items-center gap-3"><button type="button" onClick={() => setEditing(item)} className="inline-flex items-center gap-1 text-xs text-brand-700"><Pencil className="h-3.5 w-3.5" />编辑</button><button type="button" onClick={() => void toggle(item)} className="text-xs text-gray-600">{item.active ? '停用' : '启用'}</button></div></Td>
              </tr>
            ))}
            {!loading && items.length === 0 ? <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-400">没有符合条件的词条</td></tr> : null}
          </tbody>
        </table>
      </div>
      {editing ? <IndustryTermEditor term={editing === 'new' ? null : editing} l1Options={l1Options} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await Promise.all([load(), loadL1Options()]); }} /> : null}
      {importing ? <IndustryImportEditor onClose={() => setImporting(false)} onImported={async () => { setImporting(false); await Promise.all([load(), loadL1Options()]); }} /> : null}
    </div>
  );
}

function IndustryTermEditor({ term, l1Options, onClose, onSaved }: { term: IndustryDictionaryTerm | null; l1Options: IndustryDictionaryTerm[]; onClose: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(term?.term || '');
  const [level, setLevel] = useState<'l1' | 'l2'>(term?.level || 'l2');
  const [parentId, setParentId] = useState(term?.parent_id || '');
  const [aliases, setAliases] = useState(term?.aliases.filter((alias) => alias.active).map((alias) => alias.term).join('、') || '');
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!name.trim()) { alert('请填写标准行业名称。'); return; }
    if (level === 'l2' && !parentId) { alert('请选择所属一级行业。'); return; }
    const payload = {
      term: name.trim(),
      parent_id: level === 'l2' ? parentId : null,
      aliases: splitAliases(aliases),
    };
    setSaving(true);
    try {
      if (term) await dataDictionaries.updateIndustryTerm(term.id, payload);
      else await dataDictionaries.createIndustryTerm({ ...payload, level, active: true, sort_order: 0 });
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '保存行业词条失败');
    } finally {
      setSaving(false);
    }
  };
  return (
    <Editor title={term ? '编辑行业词条' : '新增行业词条'} onClose={onClose} footer={<SaveButton saving={saving} onClick={save} />}>
      <Grid>
        <Field label="层级"><select className="input" value={level} disabled={Boolean(term)} onChange={(event) => setLevel(event.target.value as 'l1' | 'l2')}><option value="l1">一级行业</option><option value="l2">二级行业</option></select></Field>
        <Field label="标准行业名称"><input className="input" value={name} disabled={term?.level === 'l1'} onChange={(event) => setName(event.target.value)} /></Field>
      </Grid>
      {level === 'l2' ? <Field label="所属一级行业"><select className="input" value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">请选择</option>{l1Options.map((item) => <option key={item.id} value={item.id} disabled={!item.active && item.id !== parentId}>{item.term}{item.active ? '' : '（已停用）'}</option>)}</select></Field> : null}
      <Field label="别名"><textarea className="input min-h-24 resize-y" placeholder="多个别名用逗号、顿号或换行分隔" value={aliases} onChange={(event) => setAliases(event.target.value)} /><p className="mt-1 text-xs text-gray-400">别名不是分类层级，用于把常见说法映射到当前标准行业。</p></Field>
    </Editor>
  );
}

function IndustryImportEditor({ onClose, onImported }: { onClose: () => void; onImported: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<IndustryDictionaryImportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const selectFile = async (selected: File | null) => {
    setFile(selected);
    setPreview(null);
    if (!selected) return;
    setLoading(true);
    try {
      setPreview(await dataDictionaries.importIndustry(selected, true));
    } catch (previewError) {
      alert(previewError instanceof Error ? previewError.message : '读取导入文件失败');
    } finally {
      setLoading(false);
    }
  };
  const apply = async () => {
    if (!file || !preview || preview.error_rows > 0) return;
    setLoading(true);
    try {
      const result = await dataDictionaries.importIndustry(file, false);
      alert(`导入完成：新增一级行业 ${result.created_l1} 条、二级行业 ${result.created_l2} 条、别名 ${result.created_aliases} 条。`);
      await onImported();
    } catch (applyError) {
      alert(applyError instanceof Error ? applyError.message : '导入行业字典失败');
    } finally {
      setLoading(false);
    }
  };
  return (
    <Editor title="批量导入行业字典" onClose={onClose} footer={<SaveButton saving={loading} onClick={apply} label="确认导入" disabled={!preview || preview.error_rows > 0} />}>
      <label className="flex cursor-pointer items-center justify-center border border-dashed border-gray-300 px-4 py-8 text-sm text-gray-600">
        <Upload className="mr-2 h-4 w-4" />{file?.name || '选择 CSV 或 XLSX 文件'}
        <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(event) => void selectFile(event.target.files?.[0] || null)} />
      </label>
      {loading && !preview ? <Loading /> : null}
      {preview ? (
        <>
          <div className="flex gap-4 text-xs text-gray-600"><span>总计 {preview.total_rows}</span><span className="text-emerald-700">可导入 {preview.ready_rows}</span><span className={preview.error_rows ? 'text-red-600' : ''}>错误 {preview.error_rows}</span></div>
          <div className="max-h-[50vh] overflow-auto border border-gray-200">
            <table className="min-w-[720px] text-left text-xs"><thead className="sticky top-0 bg-gray-50 text-gray-500"><tr><Th>行</Th><Th>一级行业</Th><Th>二级行业</Th><Th>别名</Th><Th>校验</Th></tr></thead><tbody className="divide-y divide-gray-100">{preview.rows.map((row) => <tr key={row.row_number}><Td>{row.row_number}</Td><Td>{row.l1 || '-'}</Td><Td>{row.l2 || '-'}</Td><Td clamp>{row.aliases.join('、') || '-'}</Td><Td><span className={row.status === 'error' ? 'text-red-600' : 'text-emerald-700'}>{row.message}</span></Td></tr>)}</tbody></table>
          </div>
        </>
      ) : null}
    </Editor>
  );
}

function Editor({ title, onClose, footer, children, wide = false }: { title: string; onClose: () => void; footer: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/20"><div className={`flex h-full w-full ${wide ? 'max-w-5xl' : 'max-w-2xl'} flex-col bg-white shadow-xl`}><div className="flex items-center justify-between border-b border-gray-200 px-5 py-4"><h2 className="text-base font-semibold text-gray-900">{title}</h2><button type="button" onClick={onClose} className="icon-button" title="关闭"><X className="h-4 w-4" /></button></div><div className="flex-1 space-y-4 overflow-y-auto p-5">{children}</div><div className="flex justify-end border-t border-gray-200 px-5 py-4">{footer}</div></div></div>;
}

function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) { return <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium ${active ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500'}`}>{icon}{children}</button>; }
function SegmentButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button type="button" onClick={onClick} className={`px-3 py-1.5 text-xs ${active ? 'bg-gray-900 text-white' : 'text-gray-600'}`}>{children}</button>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>{children}</label>; }
function Grid({ children }: { children: React.ReactNode }) { return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>; }
function Th({ children }: { children: React.ReactNode }) { return <th className="px-4 py-3 font-medium">{children}</th>; }
function Td({ children, clamp = false }: { children: React.ReactNode; clamp?: boolean }) { return <td className="px-4 py-3 text-gray-700"><div className={clamp ? 'max-w-xs truncate' : ''}>{children}</div></td>; }
function Status({ active }: { active: boolean }) { return <span className={`inline-flex items-center gap-1 text-xs ${active ? 'text-emerald-700' : 'text-gray-400'}`}>{active ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}{active ? '启用' : '停用'}</span>; }
function Loading() { return <div className="flex items-center justify-center py-12 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在加载</div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void | Promise<void> }) { return <div className="border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700"><p>{message}</p><button type="button" onClick={() => void onRetry()} className="mt-2 text-xs underline">重新加载</button></div>; }
function SaveButton({ saving, onClick, label = '保存', disabled = false }: { saving: boolean; onClick: () => void | Promise<void>; label?: string; disabled?: boolean }) { return <button type="button" onClick={() => void onClick()} disabled={saving || disabled} className="inline-flex items-center gap-1.5 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{label}</button>; }
function levelLabel(level: string) { return level === 'l1' ? '一级行业' : '二级行业'; }
function asNumber(value: number | string | null): number | null { if (value === null || value === '') return null; const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; }
function nextVersion(version?: string | null): string { const match = /^v(\d+)\.(\d+)\.(\d+)$/.exec(version || ''); return match ? `v${match[1]}.${Number(match[2]) + 1}.0` : 'v1.0.0'; }
function splitAliases(value: string): string[] { return Array.from(new Set(value.split(/[，、,;；\n]/).map((item) => item.trim()).filter(Boolean))); }
function isRetiredModel(model: ModelProviderConfig): boolean { return model.provider_name === 'aliyun_dashscope_rerank' || model.model_name === 'qwen3-rerank'; }
