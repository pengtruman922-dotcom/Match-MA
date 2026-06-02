import { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Sparkles,
  Send,
  Plus,
  CheckCircle2,
  Building2,
  MapPin,
  TrendingUp,
  Star,
  Ban,
  ArrowRightLeft,
  FileText,
  Eye,
  Info,
  X,
} from 'lucide-react';
import { sellerTargets, buyerIntents, buyerParties } from '../lib/api';
import type { SellerTarget, BuyerIntent, BuyerParty } from '../types/api';

type Mode = 'buyer-to-target' | 'target-to-buyer';

interface RecommendationItem {
  id: string;
  name: string;
  strength: string;
  industry: string;
  region: string;
  profit: string;
  pe: string;
  matchSummary: string;
  gapSummary: string;
  contactHint: string;
  inShortlist: boolean;
}

interface ChatMessage {
  role: 'user' | 'system';
  content: string;
}

export default function Recommend() {
  const [searchParams] = useSearchParams();
  const urlMode = searchParams.get('mode') as Mode | null;
  const urlIntentId = searchParams.get('intentId') || '';
  const urlTargetId = searchParams.get('targetId') || '';

  const [mode, setMode] = useState<Mode>(urlMode === 'target-to-buyer' ? 'target-to-buyer' : 'buyer-to-target');
  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [conditionsOpen, setConditionsOpen] = useState(false);

  const [targetsList, setTargetsList] = useState<SellerTarget[]>([]);
  const [intentsList, setIntentsList] = useState<BuyerIntent[]>([]);
  const [partiesList, setPartiesList] = useState<BuyerParty[]>([]);
  const [selectedIntentId, setSelectedIntentId] = useState(urlIntentId);
  const [selectedTargetId, setSelectedTargetId] = useState(urlTargetId);

  const initializedRef = useRef(false);

  useEffect(() => {
    sellerTargets.list({ limit: 50 }).then(setTargetsList).catch(() => {});
    buyerIntents.list({ limit: 50 }).then(setIntentsList).catch(() => {});
    buyerParties.list({ limit: 50 }).then(setPartiesList).catch(() => {});
  }, []);

  useEffect(() => {
    if (initializedRef.current) return;
    if (mode === 'buyer-to-target' && selectedIntentId && intentsList.length > 0) {
      const intent = intentsList.find((i) => i.id === selectedIntentId);
      if (intent) {
        initializedRef.current = true;
        const parts: string[] = [`已加载买家意向：${intent.intent_name}`];
        if (intent.industry_primary) parts.push(`行业：${intent.industry_primary}`);
        if (intent.region_scope_summary) parts.push(`地区：${intent.region_scope_summary}`);
        if (intent.min_net_profit_yuan) parts.push(`最低利润：${(Number(intent.min_net_profit_yuan) / 10000).toFixed(0)}万`);
        if (intent.max_pe) parts.push(`PE上限：${Number(intent.max_pe).toFixed(0)}`);
        if (intent.requires_consolidation && intent.requires_consolidation !== 'unknown') {
          parts.push(`并表要求：${intent.requires_consolidation === 'yes' ? '是' : '否'}`);
        }
        const guidanceLines = [
          parts.join('\n'),
          '',
          '您可以：',
          '- 直接发送"开始推荐"使用现有条件',
          '- 输入补充条件覆盖或细化',
          '- 输入"帮我总结当前条件"查看条件快照',
        ].join('\n');
        setChatMessages([{ role: 'system', content: guidanceLines }]);
      }
    } else if (mode === 'target-to-buyer' && selectedTargetId && targetsList.length > 0) {
      const target = targetsList.find((t) => t.id === selectedTargetId);
      if (target) {
        initializedRef.current = true;
        const parts: string[] = [`已加载标的：${target.target_name}`];
        if (target.industry_primary) parts.push(`行业：${target.industry_primary}`);
        if (target.headquarter_province) parts.push(`地区：${target.headquarter_province}${target.headquarter_city || ''}`);
        if (target.current_net_profit_yuan) parts.push(`利润：${(Number(target.current_net_profit_yuan) / 10000).toFixed(0)}万`);
        const guidanceLines = [
          parts.join('\n'),
          '',
          '您可以：',
          '- 直接发送"开始推荐"为该标的匹配买家意向',
          '- 输入补充条件，例如"只看浙江买家"',
        ].join('\n');
        setChatMessages([{ role: 'system', content: guidanceLines }]);
      }
    }
  }, [mode, selectedIntentId, selectedTargetId, intentsList, targetsList]);

  const shortlistCount = items.filter((i) => i.inShortlist).length;
  const selectedIntent = intentsList.find((i) => i.id === selectedIntentId);
  const selectedTarget = targetsList.find((t) => t.id === selectedTargetId);
  const intentParty = selectedIntent?.buyer_party_id
    ? partiesList.find((p) => p.id === selectedIntent.buyer_party_id) ?? null
    : null;

  function toggleShortlist(id: string) {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, inShortlist: !item.inShortlist } : item))
    );
  }

  function switchMode(newMode: Mode) {
    setMode(newMode);
    setItems([]);
    setChatMessages([]);
    setSelectedIntentId('');
    setSelectedTargetId('');
    initializedRef.current = false;
  }

  function handleSelectIntent(id: string) {
    setSelectedIntentId(id);
    if (id !== selectedIntentId) {
      initializedRef.current = false;
      setChatMessages([]);
    }
  }

  function handleSelectTarget(id: string) {
    setSelectedTargetId(id);
    if (id !== selectedTargetId) {
      initializedRef.current = false;
      setChatMessages([]);
    }
  }

  function handleSend() {
    if (!inputValue.trim()) return;
    setChatMessages((prev) => [...prev, { role: 'user', content: inputValue }]);
    setChatMessages((prev) => [
      ...prev,
      { role: 'system', content: '推荐引擎后端开发中，当前不可生成真实结果。已保存对话记录。' },
    ]);
    setInputValue('');
  }

  const objectLabel = mode === 'buyer-to-target'
    ? (selectedIntent ? `${intentParty?.buyer_name || ''} / ${selectedIntent.intent_name}` : '未选择买家意向')
    : (selectedTarget ? selectedTarget.target_name : '未选择标的');

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col">
      {/* Top control bar */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-gray-900">智能推荐</h1>
          <div className="flex items-center border border-gray-200 bg-white p-0.5">
            <button
              onClick={() => switchMode('buyer-to-target')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-all ${
                mode === 'buyer-to-target' ? 'bg-brand-600 text-white' : 'text-gray-600 hover:text-brand-600'
              }`}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              为买家找标的
            </button>
            <button
              onClick={() => switchMode('target-to-buyer')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-all ${
                mode === 'target-to-buyer' ? 'bg-brand-600 text-white' : 'text-gray-600 hover:text-brand-600'
              }`}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              为标的找买家
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-500">
            推荐 <span className="font-semibold text-gray-900">{items.length}</span> 项
          </span>
          <span className="text-gray-500">
            已加入 <span className="font-semibold text-emerald-700">{shortlistCount}</span> 项
          </span>
          <button
            disabled={shortlistCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 font-medium bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title={shortlistCount === 0 ? '请先将推荐项加入推荐列表' : ''}
          >
            <FileText className="w-3.5 h-3.5" />
            生成推荐报告
          </button>
          <button
            onClick={() => setConditionsOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors"
          >
            <Eye className="w-3.5 h-3.5" />
            查看条件
          </button>
        </div>
      </div>

      {/* Object selector bar */}
      <div className="flex items-center gap-3 mb-3 bg-white border border-gray-200 px-4 py-2.5">
        <span className="text-xs text-gray-500">对象：</span>
        {mode === 'buyer-to-target' ? (
          <select
            value={selectedIntentId}
            onChange={(e) => handleSelectIntent(e.target.value)}
            className="text-sm border border-gray-200 px-2 py-1 bg-gray-50 focus:border-brand-500 outline-none min-w-[200px]"
          >
            <option value="">选择买家意向...</option>
            {intentsList.map((i) => (
              <option key={i.id} value={i.id}>{i.intent_name}</option>
            ))}
          </select>
        ) : (
          <select
            value={selectedTargetId}
            onChange={(e) => handleSelectTarget(e.target.value)}
            className="text-sm border border-gray-200 px-2 py-1 bg-gray-50 focus:border-brand-500 outline-none min-w-[200px]"
          >
            <option value="">选择标的...</option>
            {targetsList.map((t) => (
              <option key={t.id} value={t.id}>{t.target_name}</option>
            ))}
          </select>
        )}
        <span className="text-sm text-gray-700">{objectLabel}</span>
      </div>

      {/* Backend notice */}
      <div className="mb-3 bg-amber-50 border border-amber-200 px-4 py-2 flex items-center gap-2">
        <Info className="w-4 h-4 text-amber-600 shrink-0" />
        <span className="text-xs text-amber-700">推荐引擎、LLM 意向解析、向量检索后端开发中。当前页面为交互框架，推荐结果待后端实现。</span>
      </div>

      {/* Two column layout: conversation + results */}
      <div className="flex-1 grid grid-cols-12 gap-4 min-h-0">
        {/* Left: Conversation */}
        <div className="col-span-7 bg-white border border-gray-200 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">对话</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {chatMessages.length === 0 && (
              <div className="border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                {mode === 'buyer-to-target' ? (
                  <>
                    <p className="font-medium text-gray-800 mb-1">
                      {selectedIntent ? `已加载买家意向条件。` : '请选择买家意向或输入需求。'}
                    </p>
                    <p className="text-xs text-gray-500">您可以：</p>
                    <ul className="text-xs text-gray-500 mt-1 space-y-0.5">
                      <li>- 直接发送"开始推荐"使用现有条件</li>
                      <li>- 输入补充条件覆盖或细化</li>
                      <li>- 输入"帮我总结当前条件"查看条件快照</li>
                    </ul>
                  </>
                ) : (
                  <>
                    <p className="font-medium text-gray-800 mb-1">
                      {selectedTarget ? `已加载标的：${selectedTarget.target_name}` : '请选择标的项目。'}
                    </p>
                    <ul className="text-xs text-gray-500 mt-1 space-y-0.5">
                      <li>- 直接发送"开始推荐"为该标的匹配买家意向</li>
                      <li>- 输入补充条件，例如"只看浙江买家"</li>
                    </ul>
                  </>
                )}
              </div>
            )}
            {chatMessages.map((msg, idx) => (
              <div
                key={idx}
                className={
                  msg.role === 'user'
                    ? 'border-l-2 border-l-brand-600 bg-brand-50 px-4 py-3'
                    : 'border border-gray-200 bg-white px-4 py-3'
                }
              >
                <span className="text-xs font-medium text-gray-500 mb-1 block">
                  {msg.role === 'user' ? '用户' : '系统'}
                </span>
                <p className="text-sm leading-relaxed text-gray-800 whitespace-pre-line">{msg.content}</p>
              </div>
            ))}
          </div>
          <div className="p-3 border-t border-gray-100">
            <div className="flex items-center gap-2 border border-gray-200 focus-within:border-brand-600 transition-all">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="继续输入..."
                className="flex-1 px-4 py-2.5 text-sm outline-none placeholder:text-gray-400"
              />
              <button
                onClick={handleSend}
                className="mr-2 p-2 bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-40"
                disabled={!inputValue.trim()}
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Right: Results */}
        <div className="col-span-5 bg-white border border-gray-200 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">
              推荐结果 <span className="text-gray-400 font-normal">{items.length} 项</span>
            </h2>
            {shortlistCount > 0 && (
              <span className="text-xs font-medium text-emerald-700">已加入 {shortlistCount} 项</span>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {items.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-6">
                <Sparkles className="w-8 h-8 text-gray-300 mb-3" />
                <p className="text-sm text-gray-400">暂无推荐结果</p>
                <p className="text-xs text-gray-400 mt-1">选择对象并发送推荐请求后，结果将展示在此处</p>
              </div>
            ) : (
              items.map((item, idx) => (
                <RecommendationCard
                  key={item.id}
                  item={item}
                  index={idx + 1}
                  onToggleShortlist={() => toggleShortlist(item.id)}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* Conditions Drawer */}
      {conditionsOpen && (
        <ConditionsDrawer
          mode={mode}
          intent={selectedIntent}
          target={selectedTarget}
          party={intentParty}
          onClose={() => setConditionsOpen(false)}
        />
      )}
    </div>
  );
}

function RecommendationCard({
  item,
  index,
  onToggleShortlist,
}: {
  item: RecommendationItem;
  index: number;
  onToggleShortlist: () => void;
}) {
  return (
    <div
      className={`border transition-all ${
        item.inShortlist
          ? 'border-emerald-300 bg-emerald-50/50'
          : 'border-gray-200 bg-white hover:border-brand-200'
      }`}
    >
      <div className="p-3 space-y-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-gray-400 w-4">{index}</span>
            <span className="text-sm font-semibold text-gray-900">{item.name}</span>
          </div>
          <span className="text-xs font-medium px-2 py-0.5 bg-brand-50 text-brand-700 border border-brand-200">
            {item.strength}
          </span>
        </div>

        <div className="ml-6 text-xs text-gray-600 space-y-0.5">
          <p>{item.industry} · {item.region} · 利润{item.profit}</p>
          {item.pe && <p>PE{item.pe}</p>}
          {item.matchSummary && <p className="text-emerald-700">匹配：{item.matchSummary}</p>}
          {item.gapSummary && <p className="text-amber-700">缺口：{item.gapSummary}</p>}
          {item.contactHint && <p className="text-gray-400">接触：{item.contactHint}</p>}
        </div>

        <div className="ml-6">
          {item.inShortlist ? (
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-emerald-600 text-white">
                <CheckCircle2 className="w-3 h-3" />
                已加入推荐列表
              </span>
              <button
                onClick={onToggleShortlist}
                className="text-xs text-gray-500 hover:text-red-600"
              >
                取消
              </button>
            </div>
          ) : (
            <button
              onClick={onToggleShortlist}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 hover:bg-brand-50 transition-colors"
            >
              <Plus className="w-3 h-3" />
              加入推荐列表
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ConditionsDrawer({
  mode,
  intent,
  target,
  party,
  onClose,
}: {
  mode: Mode;
  intent: BuyerIntent | undefined;
  target: SellerTarget | undefined;
  party: BuyerParty | null;
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 bottom-0 w-[400px] bg-white z-50 shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            {mode === 'buyer-to-target' ? '买家意向条件' : '标的条件'}
          </h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {mode === 'buyer-to-target' ? (
            intent ? (
              <>
                {party && (
                  <Section label="买家主体">
                    <p className="text-sm text-gray-800">{party.buyer_name}</p>
                  </Section>
                )}
                <Section label="Hard 条件">
                  <div className="space-y-2">
                    {intent.industry_primary && <ConditionRow icon={Building2} label="行业" value={intent.industry_primary} />}
                    {intent.region_scope_summary && <ConditionRow icon={MapPin} label="区域" value={intent.region_scope_summary} />}
                    {intent.min_net_profit_yuan && <ConditionRow icon={TrendingUp} label="利润" value={`>=${(Number(intent.min_net_profit_yuan) / 10000).toFixed(0)}万`} />}
                    {intent.max_pe && <ConditionRow icon={Star} label="PE" value={`<=${Number(intent.max_pe).toFixed(0)}`} />}
                    {intent.requires_consolidation && intent.requires_consolidation !== 'unknown' && (
                      <ConditionRow icon={CheckCircle2} label="并表" value={intent.requires_consolidation === 'yes' ? '需要' : '不需要'} />
                    )}
                  </div>
                </Section>
                {intent.preference_summary && (
                  <Section label="Preference">
                    <p className="text-sm text-gray-600">{intent.preference_summary}</p>
                  </Section>
                )}
                {intent.negative_summary && (
                  <Section label="排除项">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      <Ban className="w-3.5 h-3.5 text-gray-400" />
                      <span>{intent.negative_summary}</span>
                    </div>
                  </Section>
                )}
                {intent.unknown_summary && (
                  <Section label="Unknown / 待确认">
                    <p className="text-sm text-gray-600">{intent.unknown_summary}</p>
                  </Section>
                )}
              </>
            ) : (
              <p className="text-sm text-gray-400">未选择买家意向</p>
            )
          ) : (
            target ? (
              <Section label="标的条件">
                <div className="space-y-2">
                  {target.industry_primary && <ConditionRow icon={Building2} label="行业" value={target.industry_primary} />}
                  {target.headquarter_province && <ConditionRow icon={MapPin} label="地区" value={`${target.headquarter_province} ${target.headquarter_city || ''}`} />}
                  {target.current_net_profit_yuan && <ConditionRow icon={TrendingUp} label="利润" value={`${(Number(target.current_net_profit_yuan) / 10000).toFixed(0)}万`} />}
                  {target.pe_ratio && <ConditionRow icon={Star} label="PE" value={Number(target.pe_ratio).toFixed(1)} />}
                </div>
              </Section>
            ) : (
              <p className="text-sm text-gray-400">未选择标的</p>
            )
          )}
        </div>
      </div>
    </>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">{label}</h3>
      {children}
    </div>
  );
}

function ConditionRow({ icon: Icon, label, value }: { icon: typeof Building2; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
      <span className="text-gray-500 w-10 shrink-0">{label}</span>
      <span className="text-gray-800">{value}</span>
    </div>
  );
}
