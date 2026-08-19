import { useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { ModelNodeConfig, ModelProviderConfig } from '../../types/api';
import NodeDrawer, { UnderstudyHint } from './NodeDrawer';
import { Th, formatLatency, relativeTime } from './shared';

const DOMAIN_LABELS: Record<string, string> = {
  target: '标的',
  buyer: '买家',
  recommendation: '推荐',
  common: '通用',
};
const DOMAIN_ORDER = ['target', 'buyer', 'recommendation', 'common'];

type Filter = 'all' | 'unconfigured';

export default function NodeList({
  nodes,
  models,
  variableLabels,
  onRefresh,
}: {
  nodes: ModelNodeConfig[];
  models: ModelProviderConfig[];
  variableLabels: Record<string, string>;
  onRefresh: () => Promise<void>;
}) {
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<ModelNodeConfig | null>(null);

  const labelByName = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.node_name, node.label])),
    [nodes],
  );

  // 隐藏依据只有两条，都来自代码目录：已退役、以及不是模型驱动的节点
  // （OCR 走第三方 API，配置在「模型与搜索」）。**不按 node_type 过滤** ——
  // 那正是附件 OCR 曾经整行从设置页消失的原因。
  const catalog = useMemo(
    () => nodes
      .filter((node) => node.lifecycle !== 'retired' && node.kind !== 'external_api')
      .sort((a, b) => a.sort_order - b.sort_order),
    [nodes],
  );

  const configuredCount = catalog.filter(isReady).length;
  const pendingCount = catalog.length - configuredCount;

  const visible = catalog.filter((node) => {
    if (filter === 'unconfigured' && isReady(node)) return false;
    if (!query.trim()) return true;
    const needle = query.trim().toLowerCase();
    return node.label.toLowerCase().includes(needle) || node.node_name.toLowerCase().includes(needle);
  });

  const grouped = DOMAIN_ORDER
    .map((domain) => ({ domain, items: visible.filter((node) => node.domain === domain) }))
    .filter((group) => group.items.length > 0);
  const ungrouped = visible.filter((node) => !DOMAIN_ORDER.includes(node.domain));

  return (
    <section className="space-y-3">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">AI 节点</h2>
          <p className="mt-1 text-xs text-gray-500">
            <span className="text-emerald-700">● 已配置 {configuredCount}</span>
            <span className="mx-2 text-gray-300">|</span>
            <span>○ 未配置 {pendingCount}</span>
            <span className="ml-2 text-gray-400">节点由代码固定，这里只配置模型与提示词。</span>
          </p>
        </div>
        <button type="button" onClick={() => void onRefresh()} className="icon-button self-start sm:self-auto" title="刷新">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex border border-gray-300 p-0.5">
          <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>全部</FilterChip>
          <FilterChip active={filter === 'unconfigured'} onClick={() => setFilter('unconfigured')}>仅未配置</FilterChip>
        </div>
        <input
          className="input max-w-xs"
          placeholder="搜索节点名 / node_name"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[900px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr><Th>节点</Th><Th>模型</Th><Th>Prompt</Th><Th>最近生产调用</Th><Th>操作</Th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {grouped.map((group) => (
              <NodeGroup
                key={group.domain}
                title={DOMAIN_LABELS[group.domain]}
                items={group.items}
                labelByName={labelByName}
                onEdit={setEditing}
              />
            ))}
            {ungrouped.length > 0 ? (
              <NodeGroup title="未登记" items={ungrouped} labelByName={labelByName} onEdit={setEditing} />
            ) : null}
            {visible.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-10 text-center text-sm text-gray-400">没有符合条件的节点</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {editing ? (
        <NodeDrawer
          node={editing}
          models={models}
          variableLabels={variableLabels}
          nodeLabels={labelByName}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await onRefresh(); }}
        />
      ) : null}
    </section>
  );
}

function NodeGroup({
  title,
  items,
  labelByName,
  onEdit,
}: {
  title: string;
  items: ModelNodeConfig[];
  labelByName: Record<string, string>;
  onEdit: (node: ModelNodeConfig) => void;
}) {
  return (
    <>
      <tr className="bg-gray-50/70">
        <td colSpan={5} className="border-l-2 border-brand-500 px-4 py-1.5 text-xs font-medium text-gray-600">{title}</td>
      </tr>
      {items.map((node) => (
        <NodeRow key={node.node_name} node={node} labelByName={labelByName} onEdit={onEdit} />
      ))}
    </>
  );
}

function NodeRow({
  node,
  labelByName,
  onEdit,
}: {
  node: ModelNodeConfig;
  labelByName: Record<string, string>;
  onEdit: (node: ModelNodeConfig) => void;
}) {
  const ready = isReady(node);
  const call = node.latest_production_call;
  return (
    <tr>
      <td className="px-4 py-3 align-top">
        <div className="flex items-start gap-1.5">
          <span className={ready ? 'text-emerald-600' : 'text-gray-300'}>{ready ? '●' : '○'}</span>
          <div className="min-w-0">
            <div className="font-medium text-gray-900">{node.label}</div>
            <div className="mt-0.5 font-mono text-[11px] text-gray-400">{node.node_name}</div>
            {!node.configured && node.understudy ? (
              <div className="mt-0.5 text-[11px] text-gray-500">
                ↳ <UnderstudyHint node={node} labels={labelByName} />
              </div>
            ) : null}
            {!node.registered ? (
              <div className="mt-0.5 text-[11px] text-amber-700">未登记：代码目录里没有这个节点</div>
            ) : null}
            {node.type_mismatch ? (
              <div className="mt-0.5 text-[11px] text-amber-700">配置与代码目录不一致</div>
            ) : null}
          </div>
        </div>
      </td>
      <td className="px-4 py-3 align-top">
        {node.configured ? (
          <>
            <div className="text-gray-700">{node.provider_name || '-'}</div>
            <div className="mt-0.5 font-mono text-xs text-gray-500">{node.model_name}</div>
          </>
        ) : (
          <span className="text-gray-400">未选择</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        {!node.prompt_required ? (
          <span className="text-xs text-gray-400">无（内置）</span>
        ) : node.default_prompt ? (
          <span className="text-gray-700">{node.default_prompt.version}</span>
        ) : (
          <span className="text-gray-400">未发布</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        {call ? (
          <span className={call.status === 'failed' ? 'text-red-600' : 'text-gray-600'}>
            {call.status === 'failed' ? '✘' : '✔'} {relativeTime(call.started_at)}
            {call.latency_ms ? ` · ${formatLatency(call.latency_ms)}` : ''}
          </span>
        ) : (
          <span className="text-gray-400">— 无记录</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        <button type="button" onClick={() => onEdit(node)} className="text-xs text-brand-700">配置</button>
      </td>
    </tr>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={`px-3 py-1.5 text-xs ${active ? 'bg-gray-900 text-white' : 'text-gray-600'}`}>
      {children}
    </button>
  );
}

/** 「已配置」= 有模型，且（若该节点需要）有已发布的 Prompt。与运行时口径一致。 */
/**
 * 「已配置」的四个条件，缺一不可。
 *
 * `is_active` 是 0819 补的：少了它，一个被停用的配置行照样显示成「已配置」，
 * 于是设置页宣布一切就绪，而那个节点其实根本不会被调用。这一批停用了 4 个退役
 * 节点的配置行，正好会踩中它。
 */
function isReady(node: ModelNodeConfig): boolean {
  if (!node.configured) return false;
  if (!node.is_active) return false;
  if (!node.model_name) return false;
  return node.prompt_required ? Boolean(node.default_prompt) : true;
}
