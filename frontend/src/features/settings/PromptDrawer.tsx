import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, Loader2 } from 'lucide-react';
import { dataDictionaries, modelConfig } from '../../lib/api';
import type { IndustryDictionaryTerm, ModelNodeConfig, PromptTemplateConfig } from '../../types/api';
import { Editor, SaveButton } from './shared';

type EditorTab = 'system' | 'user' | 'schema';

/** 会自动注入字典内容的变量，值来自后端渲染，编辑器只提供一个「看一眼」的入口。 */
const DICTIONARY_VARIABLES = new Set(['industry_l1_list', 'industry_l2_list']);

export default function PromptDrawer({
  node,
  variableLabels,
  nodeLabels,
  onClose,
  onSaved,
}: {
  node: ModelNodeConfig;
  variableLabels: Record<string, string>;
  /** node_name → 中文名，用于把「从 XX 复制」里的节点显示成中文。 */
  nodeLabels: Record<string, string>;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const current = node.default_prompt;
  const [history, setHistory] = useState<PromptTemplateConfig[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(current?.id ?? null);
  const [mode, setMode] = useState<'view' | 'edit'>(current ? 'view' : 'edit');
  const [tab, setTab] = useState<EditorTab>('user');

  const [version, setVersion] = useState(nextVersion(current?.version));
  const [systemPrompt, setSystemPrompt] = useState(current?.system_prompt || '');
  const [userPrompt, setUserPrompt] = useState(current?.user_prompt_template || '');
  const [schema, setSchema] = useState(JSON.stringify(current?.output_schema_json || {}, null, 2));

  const [saving, setSaving] = useState(false);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ system: string; user: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const userPromptRef = useRef<HTMLTextAreaElement | null>(null);

  const selected = history.find((item) => item.id === selectedId) || current;
  const readOnly = mode === 'view';

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

  /** 变量面板：节点声明的（来自代码目录）+ 模板里实际写到的，合并去重。 */
  const declared = node.prompt_variables;
  const used = useMemo(
    () => new Set([...extractVariableNames(systemPrompt), ...extractVariableNames(userPrompt)]),
    [systemPrompt, userPrompt],
  );
  const variables = useMemo(
    () => Array.from(new Set([...declared, ...used])),
    [declared, used],
  );

  const loadVersion = (item: PromptTemplateConfig | null | undefined) => {
    setSystemPrompt(item?.system_prompt || '');
    setUserPrompt(item?.user_prompt_template || '');
    setSchema(JSON.stringify(item?.output_schema_json || {}, null, 2));
    setPreview(null);
  };

  const pickVersion = (id: string) => {
    setSelectedId(id);
    loadVersion(history.find((item) => item.id === id));
  };

  const insertVariable = (name: string) => {
    if (readOnly) return;
    const token = `{{ ${name} }}`;
    setTab('user');
    const textarea = userPromptRef.current;
    if (!textarea) {
      setUserPrompt((prev) => prev + token);
      return;
    }
    const start = textarea.selectionStart ?? userPrompt.length;
    const end = textarea.selectionEnd ?? userPrompt.length;
    setUserPrompt(userPrompt.slice(0, start) + token + userPrompt.slice(end));
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

  const save = async () => {
    let outputSchema: Record<string, unknown>;
    try {
      outputSchema = JSON.parse(schema) as Record<string, unknown>;
    } catch {
      setTab('schema');
      alert('输出 Schema 不是合法 JSON');
      return;
    }
    setSaving(true);
    try {
      await modelConfig.createPrompt({
        node_name: node.node_name,
        version,
        name: `${node.label} ${version}`,
        system_prompt: systemPrompt,
        user_prompt_template: userPrompt,
        output_schema_json: outputSchema,
        template_engine: 'jinja',
        // 从模板重算，不再透传旧值 —— 否则声明变量会随着编辑越来越不准。
        variables_json: Array.from(used),
        is_active: true,
        is_default: true,
      });
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '创建 Prompt 版本失败');
    } finally {
      setSaving(false);
    }
  };

  const makeCurrent = async () => {
    if (!selected || selected.is_default) return;
    if (!window.confirm(`将「${selected.version}」设为当前版本？之后的任务会立即使用该版本。`)) return;
    setSwitchingId(selected.id);
    try {
      await modelConfig.updatePrompt(selected.id, { is_default: true, is_active: true });
      await loadHistory();
      await onSaved();
    } catch (switchError) {
      alert(switchError instanceof Error ? switchError.message : '切换版本失败');
    } finally {
      setSwitchingId(null);
    }
  };

  const showFewShotWarning = (selected?.few_shot_examples_json?.length ?? 0) > 0;

  const seed = current ? null : node.prompt_seed;
  const seedLabel = seed ? nodeLabels[seed.source_node_name] || seed.source_node_name : '';
  const applySeed = () => {
    if (!seed?.compatible) return;
    setSystemPrompt(seed.system_prompt || '');
    setUserPrompt(seed.user_prompt_template || '');
    setSchema(JSON.stringify(seed.output_schema_json || {}, null, 2));
    setMode('edit');
    setPreview(null);
  };

  return (
    <Editor
      title={`Prompt · ${node.label}`}
      subtitle={<span className="font-mono">{node.node_name}</span>}
      onClose={onClose}
      wide
      footer={(
        <div className="flex items-center gap-2">
          <button type="button" onClick={onClose} className="border border-gray-300 px-4 py-2 text-sm text-gray-700">取消</button>
          <SaveButton saving={saving} onClick={save} disabled={readOnly} label={`保存为 ${version} 并设为当前`} />
        </div>
      )}
    >
      <div className="flex flex-wrap items-center gap-3 border border-gray-200 bg-gray-50 px-3 py-2">
        <span className="text-xs font-medium text-gray-600">版本</span>
        {historyLoading ? (
          <span className="text-xs text-gray-400">加载中...</span>
        ) : history.length === 0 ? (
          <span className="text-xs text-gray-400">暂无历史版本</span>
        ) : (
          <select
            className="input h-8 w-48 py-0 text-xs"
            value={selectedId ?? ''}
            onChange={(event) => pickVersion(event.target.value)}
          >
            {history.map((item) => (
              <option key={item.id} value={item.id}>
                {item.version}
                {item.is_default ? ' · 当前' : ''}
                {item.is_active ? '' : ' · 已停用'}
              </option>
            ))}
          </select>
        )}

        <div className="inline-flex border border-gray-300 bg-white p-0.5">
          <button
            type="button"
            onClick={() => { setMode('view'); loadVersion(selected); }}
            className={`px-2.5 py-1 text-xs ${readOnly ? 'bg-gray-900 text-white' : 'text-gray-600'}`}
          >
            查看
          </button>
          <button
            type="button"
            onClick={() => setMode('edit')}
            className={`px-2.5 py-1 text-xs ${readOnly ? 'text-gray-600' : 'bg-gray-900 text-white'}`}
          >
            编辑为新版本
          </button>
        </div>

        {readOnly ? null : (
          <input
            className="input h-8 w-28 py-0 text-xs"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            aria-label="新版本号"
          />
        )}

        <div className="ml-auto">
          {selected && !selected.is_default ? (
            <button
              type="button"
              disabled={switchingId === selected.id}
              onClick={() => void makeCurrent()}
              className="border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-700 disabled:opacity-50"
            >
              {switchingId === selected.id ? '切换中...' : '设为当前版本'}
            </button>
          ) : (
            <span className="text-xs text-gray-400">{selected ? '这是当前版本' : ''}</span>
          )}
        </div>
      </div>

      {seed ? (
        seed.compatible ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border border-brand-200 bg-brand-50/60 px-3 py-2 text-xs text-gray-700">
            <span>
              该节点还没有提示词。代跑节点「{seedLabel}」{seed.source_version ? ` ${seed.source_version}` : ''} 的输入与它一致，可以复制过来当起点。
            </span>
            <button type="button" onClick={applySeed} className="shrink-0 border border-brand-500 bg-white px-3 py-1.5 text-xs font-medium text-brand-700">
              复制为起点
            </button>
          </div>
        ) : (
          <div className="border border-gray-200 bg-gray-50 px-3 py-2 text-xs leading-5 text-gray-600">
            该节点还没有提示词，且<b>不能</b>从代跑节点「{seedLabel}」复制 —— 后者用到
            {seed.extra_variables.map((name) => <code key={name} className="mx-1 text-gray-800">{`{{ ${name} }}`}</code>)}
            ，而本节点运行时收不到这些变量，照抄会让它们渲染成 <code>null</code> 塞给模型。请按右侧「变量」列出的输入重新编写。
          </div>
        )
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
        <div>
          <div className="flex border-b border-gray-200">
            <PromptTab active={tab === 'system'} filled={Boolean(systemPrompt)} onClick={() => setTab('system')}>System</PromptTab>
            <PromptTab active={tab === 'user'} filled={Boolean(userPrompt)} onClick={() => setTab('user')}>User Prompt</PromptTab>
            <PromptTab active={tab === 'schema'} filled={schema.trim().length > 2} onClick={() => setTab('schema')}>输出 Schema</PromptTab>
          </div>
          <div className="pt-3">
            {tab === 'system' ? (
              <textarea
                className="input min-h-[26rem] resize-y font-mono text-xs"
                readOnly={readOnly}
                value={systemPrompt}
                onChange={(event) => setSystemPrompt(event.target.value)}
              />
            ) : null}
            {tab === 'user' ? (
              <textarea
                ref={userPromptRef}
                className="input min-h-[26rem] resize-y font-mono text-xs"
                readOnly={readOnly}
                value={userPrompt}
                onChange={(event) => setUserPrompt(event.target.value)}
              />
            ) : null}
            {tab === 'schema' ? (
              <>
                <textarea
                  className="input min-h-[26rem] resize-y font-mono text-xs"
                  readOnly={readOnly}
                  value={schema}
                  onChange={(event) => setSchema(event.target.value)}
                />
                {showFewShotWarning ? (
                  <div className="mt-2 border border-amber-200 bg-amber-50 p-3 text-[11px] leading-relaxed text-amber-800">
                    ⚠ 该版本的 <code>few_shot_examples_json</code> 非空，但这个字段是历史遗留存储，<b>不会</b>注入给模型。
                    示例请直接写进 User Prompt 正文。
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        <div className="space-y-4">
          <div className="border border-gray-200 p-3">
            <p className="mb-2 text-xs font-medium text-gray-700">
              变量{readOnly ? '' : '（点击插入到 User Prompt）'}
            </p>
            {variables.length === 0 ? (
              <p className="text-[11px] text-gray-400">该节点没有可用变量</p>
            ) : (
              <div className="space-y-1.5">
                {variables.map((name) => (
                  <VariableRow
                    key={name}
                    name={name}
                    label={variableLabels[name] || ''}
                    used={used.has(name)}
                    readOnly={readOnly}
                    onInsert={() => insertVariable(name)}
                  />
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => void runPreview()}
            disabled={previewLoading}
            className="inline-flex w-full items-center justify-center gap-1.5 border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50"
          >
            {previewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            渲染预览
          </button>

          {preview ? (
            <div className="border border-gray-200">
              <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-2">
                <p className="text-[11px] font-medium text-gray-700">模型实际收到的内容</p>
                <button type="button" onClick={() => setPreview(null)} className="text-[11px] text-gray-400 hover:text-gray-600">收起</button>
              </div>
              <div className="max-h-96 overflow-y-auto p-3">
                {preview.system ? (
                  <>
                    <p className="mb-1 text-[11px] font-medium text-gray-500">System:</p>
                    <pre className="mb-3 whitespace-pre-wrap break-words font-mono text-[11px] text-gray-700">{preview.system}</pre>
                  </>
                ) : null}
                <p className="mb-1 text-[11px] font-medium text-gray-500">User:</p>
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-gray-700">{preview.user}</pre>
              </div>
              <p className="border-t border-gray-100 px-3 py-2 text-[10px] text-gray-400">
                字典类变量为真实内容，其余为示例占位。
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </Editor>
  );
}

function PromptTab({ active, filled, onClick, children }: { active: boolean; filled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium ${active ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500'}`}
    >
      {children}
      {filled ? <span className="text-[8px] text-brand-500">●</span> : null}
    </button>
  );
}

function VariableRow({
  name,
  label,
  used,
  readOnly,
  onInsert,
}: {
  name: string;
  label: string;
  used: boolean;
  readOnly: boolean;
  onInsert: () => void;
}) {
  const [terms, setTerms] = useState<IndustryDictionaryTerm[] | null>(null);
  const [open, setOpen] = useState(false);
  const isDictionary = DICTIONARY_VARIABLES.has(name);

  // 懒加载：不点开就不请求字典，避免每次打开 Prompt 都白拉一次全量词条。
  const toggleDictionary = async () => {
    setOpen((value) => !value);
    if (terms) return;
    try {
      setTerms(await dataDictionaries.industry({ level: name === 'industry_l2_list' ? 'l2' : 'l1' }));
    } catch {
      setTerms([]);
    }
  };

  return (
    <div>
      <button
        type="button"
        disabled={readOnly}
        onClick={onInsert}
        className="block w-full text-left text-[11px] leading-relaxed hover:bg-brand-50 disabled:hover:bg-transparent"
      >
        <span className={used ? 'text-emerald-600' : 'text-gray-300'}>{used ? '✔' : '○'}</span>
        <code className="ml-1 text-brand-700">{'{{ '}{name}{' }}'}</code>
      </button>
      <div className="ml-4 flex items-center gap-1 text-[11px] text-gray-500">
        <span>{label || (used ? '' : '模板中新增')}</span>
        {isDictionary ? (
          <button type="button" onClick={() => void toggleDictionary()} className="inline-flex items-center gap-0.5 text-brand-600 hover:underline">
            查看当前内容<ExternalLink className="h-3 w-3" />
          </button>
        ) : null}
      </div>
      {isDictionary && open ? (
        <div className="ml-4 mt-1 flex max-h-32 flex-wrap gap-1 overflow-y-auto border border-gray-100 bg-gray-50 p-2">
          {terms === null ? (
            <span className="text-[10px] text-gray-400">加载中...</span>
          ) : terms.length === 0 ? (
            <span className="text-[10px] text-gray-400">暂无启用词条</span>
          ) : (
            terms.map((item) => (
              <span key={item.id} className="bg-white px-1.5 py-0.5 text-[10px] text-gray-600">{item.term}</span>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

export function extractVariableNames(template: string): string[] {
  const names: string[] = [];
  const pattern = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(template)) !== null) {
    if (!names.includes(match[1])) names.push(match[1]);
  }
  return names;
}

export function nextVersion(version?: string | null): string {
  const match = /^v(\d+)\.(\d+)\.(\d+)$/.exec(version || '');
  return match ? `v${match[1]}.${Number(match[2]) + 1}.0` : 'v1.0.0';
}
