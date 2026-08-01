import { useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, TestTube2 } from 'lucide-react';
import { modelConfig } from '../../lib/api';
import type { ModelNodeConfig, ModelProviderConfig } from '../../types/api';
import PromptDrawer from './PromptDrawer';
import { Editor, Field, Grid, SaveButton, asNumber, formatLatency, relativeTime } from './shared';

export default function NodeDrawer({
  node,
  models,
  variableLabels,
  nodeLabels,
  onClose,
  onSaved,
}: {
  node: ModelNodeConfig;
  models: ModelProviderConfig[];
  variableLabels: Record<string, string>;
  /** node_name → 中文名，用来把代跑提示里的节点也显示成中文。 */
  nodeLabels: Record<string, string>;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [modelId, setModelId] = useState(node.provider_config_id || '');
  const [temperature, setTemperature] = useState<number | string | null>(node.temperature);
  const [topP, setTopP] = useState<number | string | null>(node.top_p);
  const [timeout, setTimeoutValue] = useState(node.timeout_seconds);
  const [advanced, setAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);

  const save = async () => {
    if (!modelId) {
      alert('请选择模型。');
      return;
    }
    setSaving(true);
    try {
      await modelConfig.saveCatalogNode(node.node_name, {
        provider_config_id: modelId,
        temperature: asNumber(temperature),
        top_p: asNumber(topP),
        timeout_seconds: timeout,
      });
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '保存节点配置失败');
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    if (!node.id) return;
    setTesting(true);
    try {
      const started = await modelConfig.testNode(node.id, '');
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const result = await modelConfig.nodeTestJob(started.job_id);
        if (['succeeded', 'failed', 'canceled'].includes(result.job_status)) {
          if (result.job_status !== 'succeeded') alert(result.error_message || result.error_code || '节点业务测试失败');
          break;
        }
      }
      await onSaved();
    } catch (testError) {
      alert(testError instanceof Error ? testError.message : '节点业务测试失败');
    } finally {
      setTesting(false);
    }
  };

  if (promptOpen) {
    return (
      <PromptDrawer
        node={node}
        variableLabels={variableLabels}
        nodeLabels={nodeLabels}
        onClose={() => setPromptOpen(false)}
        onSaved={async () => { setPromptOpen(false); await onSaved(); }}
      />
    );
  }

  const call = node.latest_production_call;
  const test = node.test_summary;
  const testable = Boolean(node.id) && Boolean(node.default_prompt || !node.prompt_required);

  return (
    <Editor
      title={node.label}
      subtitle={(
        <span className="inline-flex flex-wrap items-center gap-2">
          <span className="font-mono">{node.node_name}</span>
          <span className="text-gray-300">·</span>
          <span>{node.node_type}</span>
          <span className="text-gray-300">·</span>
          <NodeStateLabel node={node} />
        </span>
      )}
      onClose={onClose}
      footer={(
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!testable || testing}
            onClick={() => void runTest()}
            className="inline-flex items-center gap-1.5 border border-gray-300 px-4 py-2 text-sm text-gray-700 disabled:opacity-40"
          >
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <TestTube2 className="h-4 w-4" />}业务测试
          </button>
          <SaveButton saving={saving} onClick={save} />
        </div>
      )}
    >
      {node.type_mismatch ? (
        <div className="border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          配置与代码目录不一致：库里的节点类型是 <code>{node.node_type}</code>，与代码目录声明的不同。请先确认后再修改。
        </div>
      ) : null}
      {!node.registered ? (
        <div className="border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          该节点未登记在代码目录中，可能是历史遗留配置。它不会被任何业务流程调用。
        </div>
      ) : null}

      <section>
        <h3 className="text-xs font-medium text-gray-600">用途</h3>
        <p className="mt-1 text-sm leading-6 text-gray-700">{node.description || '—'}</p>
        {node.understudy && !node.configured ? (
          <p className="mt-1 text-xs text-gray-500"><UnderstudyHint node={node} labels={nodeLabels} /></p>
        ) : null}
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-xs font-medium text-gray-600">运行时输入</h3>
          <ul className="mt-1 space-y-0.5 text-sm text-gray-700">
            {node.runtime_inputs.length === 0
              ? <li className="text-gray-400">—</li>
              : node.runtime_inputs.map((item) => <li key={item}>· {item}</li>)}
          </ul>
        </div>
        <div>
          <h3 className="text-xs font-medium text-gray-600">输出</h3>
          <p className="mt-1 text-sm text-gray-700">{node.output_mode}</p>
          {node.prompt_required ? <p className="text-xs text-gray-400">结构见 Prompt 的输出 Schema</p> : null}
        </div>
      </section>

      <hr className="border-gray-100" />

      <Field label="模型">
        <select className="input" value={modelId} onChange={(event) => setModelId(event.target.value)}>
          <option value="">请选择</option>
          {models.map((model) => (
            <option key={model.id} value={model.id}>{model.provider_name} · {model.model_name}</option>
          ))}
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

      {node.prompt_required ? (
        <>
          <hr className="border-gray-100" />
          <section>
            <h3 className="text-xs font-medium text-gray-600">Prompt</h3>
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-gray-700">
                {node.default_prompt
                  ? <>当前 <span className="font-medium">{node.default_prompt.version}</span> · {node.default_prompt.updated_at?.slice(0, 10)} 更新</>
                  : <span className="text-gray-500">未发布</span>}
              </p>
              <button type="button" onClick={() => setPromptOpen(true)} className="text-xs text-brand-700">
                {node.default_prompt ? '编辑 Prompt →' : '创建 Prompt →'}
              </button>
            </div>
          </section>
        </>
      ) : null}

      <hr className="border-gray-100" />
      <section>
        <h3 className="text-xs font-medium text-gray-600">运行状况</h3>
        <dl className="mt-1 space-y-1 text-sm">
          <div className="flex gap-3">
            <dt className="w-24 shrink-0 text-gray-500">最近生产调用</dt>
            <dd className={call?.status === 'failed' ? 'text-red-600' : 'text-gray-700'}>
              {call
                ? `${call.status} · ${relativeTime(call.started_at)}${call.latency_ms ? ` · ${formatLatency(call.latency_ms)}` : ''}${call.error_message ? ` · ${call.error_message}` : ''}`
                : <span className="text-gray-400">无记录</span>}
            </dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-24 shrink-0 text-gray-500">最近业务测试</dt>
            <dd className={test?.latest_status === 'failed' ? 'text-red-600' : 'text-gray-700'}>
              {test?.latest_status
                ? `${test.latest_status}${test.latest_latency_ms ? ` · ${formatLatency(test.latest_latency_ms)}` : ''}${test.latest_error_message ? ` · ${test.latest_error_message}` : ''}`
                : <span className="text-gray-400">无记录</span>}
            </dd>
          </div>
        </dl>
        {node.latest_test ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-gray-500">查看最近测试 JSON</summary>
            <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all bg-gray-50 p-2 text-[10px] text-gray-600">
              {JSON.stringify(node.latest_test, null, 2)}
            </pre>
          </details>
        ) : null}
      </section>
    </Editor>
  );
}

export function NodeStateLabel({ node }: { node: ModelNodeConfig }) {
  if (!node.configured) return <span className="text-gray-500">○ 未配置</span>;
  if (node.prompt_required && !node.default_prompt) return <span className="text-gray-500">○ 未发布 Prompt</span>;
  return <span className="text-emerald-700">● 已配置</span>;
}

/**
 * 代跑提示。两种语义的文案必须分开写：
 * and  —— 同组全部就绪才生效，只配一个等于没配；
 * solo —— 各自独立，配一个生效一个。
 */
export function UnderstudyHint({ node, labels }: { node: ModelNodeConfig; labels?: Record<string, string> }) {
  if (!node.understudy) return null;
  const name = (key: string) => labels?.[key] || key;
  if (node.understudy_kind === 'and' && node.understudy_group.length > 0) {
    return <>未启用 · 需与「{node.understudy_group.map(name).join('」「')}」同时就绪才生效</>;
  }
  return <>未启用 · 当前由「{name(node.understudy)}」代跑</>;
}
