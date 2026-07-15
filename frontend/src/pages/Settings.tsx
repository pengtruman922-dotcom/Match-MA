import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Database, Loader2, Plus, RefreshCw, Save, Settings2, TestTube2, X } from 'lucide-react';
import { dataDictionaries, modelConfig } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type {
  IndustryDictionaryTerm,
  ModelConfigSettingsPage,
  ModelNodeConfig,
  ModelProviderConfig,
} from '../types/api';

type SettingsTab = 'ai' | 'dictionary';

const NODE_LABELS: Record<string, string> = {
  seller_target_parser: '标的新建解析',
  seller_target_update_parser: '标的更新解析',
  buyer_intent_parser: '买家新建解析',
  buyer_intent_update_parser: '买家更新与跟进解析',
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
  const [editingProvider, setEditingProvider] = useState<ModelProviderConfig | null>(null);
  const [promptNode, setPromptNode] = useState<ModelNodeConfig | null>(null);

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

  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error || '读取 AI 设置失败'} onRetry={load} />;
  const nodes = data.nodes.filter((node) => !HIDDEN_RETIRED_NODES.has(node.node_name));
  return (
    <div className="space-y-7">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <div><h2 className="text-sm font-semibold text-gray-900">模型供应商</h2><p className="mt-1 text-xs text-gray-500">真实密钥仍在 Railway 配置，这里只保存环境变量名。</p></div>
          <button type="button" onClick={() => void load()} className="icon-button" title="刷新"><RefreshCw className="h-4 w-4" /></button>
        </div>
        <div className="overflow-x-auto border border-gray-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500"><tr><Th>名称</Th><Th>类型</Th><Th>Base URL</Th><Th>Key 环境变量</Th><Th>状态</Th><Th>操作</Th></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {data.providers.map((provider) => <tr key={provider.id}><Td>{provider.provider_name}</Td><Td>{provider.provider_type}</Td><Td clamp>{provider.base_url || '-'}</Td><Td>{provider.api_key_secret_ref || '-'}</Td><Td><Status active={provider.is_active} /></Td><Td><button type="button" onClick={() => setEditingProvider(provider)} className="text-xs text-brand-700">配置</button></Td></tr>)}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-gray-900">业务节点</h2>
        <div className="overflow-x-auto border border-gray-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500"><tr><Th>业务节点</Th><Th>供应商 / 模型</Th><Th>参数</Th><Th>Prompt</Th><Th>测试</Th><Th>操作</Th></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {nodes.map((node) => (
                <tr key={node.id}>
                  <Td><div className="font-medium text-gray-900">{NODE_LABELS[node.node_name] || node.node_name}</div><div className="mt-0.5 font-mono text-[11px] text-gray-400">{node.node_name}</div></Td>
                  <Td><div>{node.provider_name || '-'}</div><div className="mt-0.5 text-xs text-gray-500">{node.model_name}</div></Td>
                  <Td><div className="text-xs text-gray-600">温度 {node.temperature ?? '-'} · {node.max_tokens ?? '-'} tokens</div><div className="mt-0.5 text-xs text-gray-400">超时 {node.timeout_seconds}s</div></Td>
                  <Td>{node.prompt_editable ? <button type="button" onClick={() => setPromptNode(node)} className="text-xs text-brand-700">{node.default_prompt?.version || '新建版本'}</button> : <span className="text-xs text-gray-400">无 Prompt</span>}</Td>
                  <Td><TestNodeButton node={node} /></Td>
                  <Td><button type="button" onClick={() => setEditingNode(node)} className="text-xs text-brand-700">配置</button></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {editingProvider ? <ProviderEditor provider={editingProvider} onClose={() => setEditingProvider(null)} onSaved={async () => { setEditingProvider(null); await load(); }} /> : null}
      {editingNode ? <NodeEditor node={editingNode} providers={data.providers} onClose={() => setEditingNode(null)} onSaved={async () => { setEditingNode(null); await load(); }} /> : null}
      {promptNode ? <PromptEditor node={promptNode} onClose={() => setPromptNode(null)} onSaved={async () => { setPromptNode(null); await load(); }} /> : null}
    </div>
  );
}

function ProviderEditor({ provider, onClose, onSaved }: { provider: ModelProviderConfig; onClose: () => void; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState(provider);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try { await modelConfig.updateProvider(provider.id, { provider_name: draft.provider_name, base_url: draft.base_url, api_key_secret_ref: draft.api_key_secret_ref, auth_type: draft.auth_type, is_active: draft.is_active }); await onSaved(); }
    catch (error) { alert(error instanceof Error ? error.message : '保存供应商失败'); }
    finally { setSaving(false); }
  };
  return <Editor title="配置模型供应商" onClose={onClose} footer={<SaveButton saving={saving} onClick={save} />}>
    <Grid><Field label="名称"><input className="input" value={draft.provider_name} onChange={(event) => setDraft({ ...draft, provider_name: event.target.value })} /></Field><Field label="认证方式"><select className="input" value={draft.auth_type} onChange={(event) => setDraft({ ...draft, auth_type: event.target.value })}><option value="bearer">Bearer</option><option value="api_key_header">API Key Header</option><option value="none">None</option></select></Field></Grid>
    <Field label="Base URL"><input className="input" value={draft.base_url || ''} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} /></Field>
    <Field label="API Key 环境变量名"><input className="input font-mono" value={draft.api_key_secret_ref || ''} onChange={(event) => setDraft({ ...draft, api_key_secret_ref: event.target.value })} /><p className="mt-1 text-xs text-gray-400">例如 ALIYUN_API_KEY，不要填写真实密钥。</p></Field>
  </Editor>;
}

function NodeEditor({ node, providers, onClose, onSaved }: { node: ModelNodeConfig; providers: ModelProviderConfig[]; onClose: () => void; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState(node);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try { await modelConfig.updateNode(node.id, { provider_config_id: draft.provider_config_id, model_name: draft.model_name, temperature: asNumber(draft.temperature), top_p: asNumber(draft.top_p), max_tokens: draft.max_tokens, timeout_seconds: draft.timeout_seconds, response_format: draft.response_format, is_active: draft.is_active }); await onSaved(); }
    catch (error) { alert(error instanceof Error ? error.message : '保存节点失败'); }
    finally { setSaving(false); }
  };
  return <Editor title={NODE_LABELS[node.node_name] || node.node_name} onClose={onClose} footer={<SaveButton saving={saving} onClick={save} />}>
    <Grid><Field label="模型供应商"><select className="input" value={draft.provider_config_id} onChange={(event) => setDraft({ ...draft, provider_config_id: event.target.value })}>{providers.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.provider_name}</option>)}</select></Field><Field label="模型名称"><input className="input" value={draft.model_name} onChange={(event) => setDraft({ ...draft, model_name: event.target.value })} /></Field><Field label="Temperature"><input className="input" type="number" step="0.1" min="0" max="2" value={draft.temperature ?? ''} onChange={(event) => setDraft({ ...draft, temperature: event.target.value })} /></Field><Field label="Top P"><input className="input" type="number" step="0.1" min="0" max="1" value={draft.top_p ?? ''} onChange={(event) => setDraft({ ...draft, top_p: event.target.value })} /></Field><Field label="Max Tokens"><input className="input" type="number" value={draft.max_tokens ?? ''} onChange={(event) => setDraft({ ...draft, max_tokens: Number(event.target.value) || null })} /></Field><Field label="超时（秒）"><input className="input" type="number" value={draft.timeout_seconds} onChange={(event) => setDraft({ ...draft, timeout_seconds: Number(event.target.value) || 60 })} /></Field></Grid>
  </Editor>;
}

function PromptEditor({ node, onClose, onSaved }: { node: ModelNodeConfig; onClose: () => void; onSaved: () => Promise<void> }) {
  const current = node.default_prompt;
  const [version, setVersion] = useState(nextVersion(current?.version));
  const [systemPrompt, setSystemPrompt] = useState(current?.system_prompt || '');
  const [userPrompt, setUserPrompt] = useState(current?.user_prompt_template || '');
  const [schema, setSchema] = useState(JSON.stringify(current?.output_schema_json || {}, null, 2));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    let outputSchema: Record<string, unknown>;
    try { outputSchema = JSON.parse(schema) as Record<string, unknown>; } catch { alert('输出 Schema 不是合法 JSON'); return; }
    setSaving(true);
    try { await modelConfig.createPrompt({ node_name: node.node_name, version, name: `${NODE_LABELS[node.node_name] || node.node_name} ${version}`, system_prompt: systemPrompt, user_prompt_template: userPrompt, output_schema_json: outputSchema, template_engine: 'jinja', variables_json: current?.variables_json || [], is_active: true, is_default: true }); await onSaved(); }
    catch (error) { alert(error instanceof Error ? error.message : '创建 Prompt 版本失败'); }
    finally { setSaving(false); }
  };
  return <Editor title="新建 Prompt 版本" onClose={onClose} footer={<SaveButton saving={saving} onClick={save} label="保存并设为当前版本" />}>
    <Field label="版本号"><input className="input" value={version} onChange={(event) => setVersion(event.target.value)} /></Field>
    <Field label="System Prompt"><textarea className="input min-h-28 resize-y font-mono text-xs" value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} /></Field>
    <Field label="User Prompt Template"><textarea className="input min-h-56 resize-y font-mono text-xs" value={userPrompt} onChange={(event) => setUserPrompt(event.target.value)} /></Field>
    <Field label="输出 Schema"><textarea className="input min-h-40 resize-y font-mono text-xs" value={schema} onChange={(event) => setSchema(event.target.value)} /></Field>
  </Editor>;
}

function TestNodeButton({ node }: { node: ModelNodeConfig }) {
  const [testing, setTesting] = useState(false);
  const test = async () => {
    const input = window.prompt('输入一段连接测试文本：', '测试模型连接并返回简短 JSON。');
    if (!input) return;
    setTesting(true);
    try { const result = await modelConfig.testNode(node.id, input); alert(`测试任务已创建：${result.job_id}`); }
    catch (error) { alert(error instanceof Error ? error.message : '创建测试任务失败'); }
    finally { setTesting(false); }
  };
  return <button type="button" onClick={() => void test()} disabled={testing || !node.is_active} className="inline-flex items-center gap-1 text-xs text-brand-700 disabled:text-gray-300">{testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TestTube2 className="h-3.5 w-3.5" />}测试</button>;
}

function IndustryDictionary() {
  const [items, setItems] = useState<IndustryDictionaryTerm[]>([]);
  const [l1Options, setL1Options] = useState<IndustryDictionaryTerm[]>([]);
  const [q, setQ] = useState('');
  const [level, setLevel] = useState('');
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ term: '', level: 'alias' as 'l1' | 'l2' | 'alias', l1_name: '', active: true, sort_order: 0 });
  const load = useCallback(async () => { setLoading(true); try { setItems(await dataDictionaries.industry({ q: q || undefined, level: level || undefined, include_inactive: true })); } catch (error) { alert(error instanceof Error ? error.message : '读取行业字典失败'); } finally { setLoading(false); } }, [q, level]);
  const loadL1Options = useCallback(async () => { try { setL1Options(await dataDictionaries.industry({ level: 'l1', include_inactive: false })); } catch { setL1Options([]); } }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 250); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => { void loadL1Options(); }, [loadL1Options]);
  const create = async () => { try { await dataDictionaries.createIndustryTerm(draft); setCreating(false); setDraft({ term: '', level: 'alias', l1_name: '', active: true, sort_order: 0 }); await Promise.all([load(), loadL1Options()]); } catch (error) { alert(error instanceof Error ? error.message : '新增行业词失败'); } };
  const toggle = async (item: IndustryDictionaryTerm) => { try { await dataDictionaries.updateIndustryTerm(item.id, { active: !item.active }); await Promise.all([load(), item.level === 'l1' ? loadL1Options() : Promise.resolve()]); } catch (error) { alert(error instanceof Error ? error.message : '更新状态失败'); } };
  return <div className="space-y-4">
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><h2 className="text-sm font-semibold text-gray-900">行业分类</h2><p className="mt-1 text-xs text-gray-500">当前数据字典仅包含行业一级分类、二级分类和别名。</p></div><button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新增词条</button></div>
    <div className="flex gap-2"><input className="input max-w-sm" placeholder="搜索词条或一级行业" value={q} onChange={(event) => setQ(event.target.value)} /><select className="input w-36" value={level} onChange={(event) => setLevel(event.target.value)}><option value="">全部层级</option><option value="l1">一级行业</option><option value="l2">二级行业</option><option value="alias">别名</option></select></div>
    <div className="overflow-x-auto border border-gray-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-gray-50 text-xs text-gray-500"><tr><Th>词条</Th><Th>层级</Th><Th>所属一级行业</Th><Th>使用量</Th><Th>状态</Th><Th>操作</Th></tr></thead><tbody className="divide-y divide-gray-100">{loading ? <tr><td colSpan={6}><Loading /></td></tr> : items.map((item) => <tr key={item.id}><Td><span className="font-medium text-gray-900">{item.term}</span></Td><Td>{levelLabel(item.level)}</Td><Td>{item.l1_name}</Td><Td>{item.usage_count}</Td><Td><Status active={item.active} /></Td><Td><button type="button" onClick={() => void toggle(item)} className="text-xs text-brand-700">{item.active ? '停用' : '启用'}</button></Td></tr>)}</tbody></table></div>
    {creating ? <Editor title="新增行业词条" onClose={() => setCreating(false)} footer={<SaveButton saving={false} onClick={create} label="新增" />}><Grid><Field label="词条"><input className="input" value={draft.term} onChange={(event) => setDraft({ ...draft, term: event.target.value })} /></Field><Field label="层级"><select className="input" value={draft.level} onChange={(event) => setDraft({ ...draft, level: event.target.value as typeof draft.level, l1_name: event.target.value === 'l1' ? draft.term : draft.l1_name })}><option value="l1">一级行业</option><option value="l2">二级行业</option><option value="alias">别名</option></select></Field></Grid>{draft.level !== 'l1' ? <Field label="所属一级行业"><select className="input" value={draft.l1_name} onChange={(event) => setDraft({ ...draft, l1_name: event.target.value })}><option value="">请选择</option>{l1Options.map((item) => <option key={item.id} value={item.term}>{item.term}</option>)}</select></Field> : null}</Editor> : null}
  </div>;
}

function Editor({ title, onClose, footer, children }: { title: string; onClose: () => void; footer: React.ReactNode; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex justify-end bg-black/20"><div className="flex h-full w-full max-w-2xl flex-col bg-white shadow-xl"><div className="flex items-center justify-between border-b border-gray-200 px-5 py-4"><h2 className="text-base font-semibold text-gray-900">{title}</h2><button type="button" onClick={onClose} className="icon-button" title="关闭"><X className="h-4 w-4" /></button></div><div className="flex-1 space-y-4 overflow-y-auto p-5">{children}</div><div className="flex justify-end border-t border-gray-200 px-5 py-4">{footer}</div></div></div>; }
function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) { return <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium ${active ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500'}`}>{icon}{children}</button>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>{children}</label>; }
function Grid({ children }: { children: React.ReactNode }) { return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>; }
function Th({ children }: { children: React.ReactNode }) { return <th className="px-4 py-3 font-medium">{children}</th>; }
function Td({ children, clamp = false }: { children: React.ReactNode; clamp?: boolean }) { return <td className="px-4 py-3 text-gray-700"><div className={clamp ? 'max-w-xs truncate' : ''}>{children}</div></td>; }
function Status({ active }: { active: boolean }) { return <span className={`inline-flex items-center gap-1 text-xs ${active ? 'text-emerald-700' : 'text-gray-400'}`}>{active ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}{active ? '启用' : '停用'}</span>; }
function Loading() { return <div className="flex items-center justify-center py-12 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在加载</div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void | Promise<void> }) { return <div className="border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700"><p>{message}</p><button type="button" onClick={() => void onRetry()} className="mt-2 text-xs underline">重新加载</button></div>; }
function SaveButton({ saving, onClick, label = '保存' }: { saving: boolean; onClick: () => void | Promise<void>; label?: string }) { return <button type="button" onClick={() => void onClick()} disabled={saving} className="inline-flex items-center gap-1.5 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{label}</button>; }
function levelLabel(level: string) { return level === 'l1' ? '一级行业' : level === 'l2' ? '二级行业' : '别名'; }
function asNumber(value: number | string | null): number | null { if (value === null || value === '') return null; const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; }
function nextVersion(version?: string | null): string { const match = /^v(\d+)\.(\d+)\.(\d+)$/.exec(version || ''); return match ? `v${match[1]}.${Number(match[2]) + 1}.0` : 'v1.0.0'; }
