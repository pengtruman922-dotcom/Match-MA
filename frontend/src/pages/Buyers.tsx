import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Search, X, ChevronDown, ChevronUp, Sparkles, MessageSquarePlus } from 'lucide-react';
import { buyerParties, buyerIntents } from '../lib/api';
import type { BuyerParty, BuyerPartyCreate, BuyerIntent, BuyerIntentCreate } from '../types/api';

type Tab = 'intents' | 'parties';

export default function Buyers() {
  const [tab, setTab] = useState<Tab>('intents');
  const [showCreateIntent, setShowCreateIntent] = useState(false);
  const [showCreateParty, setShowCreateParty] = useState(false);
  const [intentRefreshKey, setIntentRefreshKey] = useState(0);
  const [partyRefreshKey, setPartyRefreshKey] = useState(0);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">买家管理</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateIntent(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建买家意向
          </button>
          <button
            onClick={() => { setTab('parties'); setShowCreateParty(true); }}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors bg-white"
          >
            <Plus className="w-4 h-4" />
            新建买家
          </button>
        </div>
      </div>

      {/* Tab Switch */}
      <div className="border-b border-gray-200 flex items-center gap-0.5">
        <button
          onClick={() => setTab('intents')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${tab === 'intents' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
        >
          买家意向
        </button>
        <button
          onClick={() => setTab('parties')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${tab === 'parties' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
        >
          买家主体
        </button>
      </div>

      {tab === 'intents' ? (
        <IntentsList
          externalShowCreate={showCreateIntent}
          onExternalCreateClose={() => setShowCreateIntent(false)}
          refreshKey={intentRefreshKey}
          onCreated={() => setIntentRefreshKey((k) => k + 1)}
        />
      ) : (
        <PartiesList
          externalShowCreate={showCreateParty}
          onExternalCreateClose={() => setShowCreateParty(false)}
          refreshKey={partyRefreshKey}
          onCreated={() => setPartyRefreshKey((k) => k + 1)}
        />
      )}
    </div>
  );
}

function IntentsList({
  externalShowCreate,
  onExternalCreateClose,
  refreshKey,
  onCreated,
}: {
  externalShowCreate: boolean;
  onExternalCreateClose: () => void;
  refreshKey: number;
  onCreated: () => void;
}) {
  const [items, setItems] = useState<BuyerIntent[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const showCreate = externalShowCreate;

  const fetchData = (q?: string) => {
    setLoading(true);
    buyerIntents.list({ q: q || undefined, limit: 50 })
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, [refreshKey]);

  return (
    <>
      <div className="flex items-center gap-2">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && fetchData(searchQuery)}
            placeholder="搜索买家意向..."
            className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 bg-white"
          />
        </div>
        <button onClick={() => fetchData(searchQuery)} className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-600 hover:text-brand-600 bg-white">搜索</button>
      </div>

      <div className="bg-white border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 font-medium text-gray-600">意向名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">行业</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">地区</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">上市要求</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">利润要求</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">市值范围</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">状态</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">暂无买家意向</td></tr>
            ) : items.map((item) => (
              <IntentRow
                key={item.id}
                item={item}
                expanded={expandedId === item.id}
                onToggle={() => setExpandedId(expandedId === item.id ? null : item.id)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateIntentModal onClose={onExternalCreateClose} onCreated={() => { onExternalCreateClose(); onCreated(); fetchData(); }} />
      )}
    </>
  );
}

function IntentRow({ item, expanded, onToggle }: { item: BuyerIntent; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className="hover:bg-brand-50/30 transition-colors">
        <td className="px-4 py-3">
          <div className="flex items-center gap-1">
            <button onClick={onToggle} className="text-gray-400 hover:text-gray-600">
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            <span className="font-medium text-gray-900">{item.intent_name}</span>
          </div>
        </td>
        <td className="px-4 py-3 text-gray-600">{item.industry_primary || '-'}</td>
        <td className="px-4 py-3 text-gray-600">{item.region_scope_summary || '-'}</td>
        <td className="px-4 py-3 text-gray-600">{listingRequirementLabel(item)}</td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">
          {item.min_net_profit_yuan ? `${(Number(item.min_net_profit_yuan) / 10000).toFixed(0)}万+` : '-'}
        </td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">
          {marketCapRangeLabel(item)}
        </td>
        <td className="px-4 py-3 text-center">
          <span className={`text-xs px-2 py-0.5 font-medium ${item.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>
            {item.status === 'active' ? '继续推荐' : '暂停推荐'}
          </span>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-1">
            <Link
              to={`/recommendations?mode=buyer-to-target&intentId=${item.id}`}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 transition-colors"
            >
              <Sparkles className="w-3 h-3" />
              推荐标的
            </Link>
            <span className="text-gray-200">|</span>
            <button className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 transition-colors">
              <MessageSquarePlus className="w-3 h-3" />
              录入更新
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50/50">
          <td colSpan={8} className="px-8 py-2.5">
            <div className="space-y-1">
              <p className="text-xs text-gray-600 line-clamp-2">
                {item.raw_requirement_text || item.intent_summary || '暂无摘要'}
                {item.requires_consolidation === 'yes' && <span className="text-gray-500 ml-2">· 需并表</span>}
                {item.buyer_party_id ? '' : <span className="text-amber-600 ml-2">· 未关联买家主体</span>}
              </p>
              <p className="text-xs text-gray-500 line-clamp-1">{compactRequirementNotes(item)}</p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function listingRequirementLabel(item: BuyerIntent): string {
  const status: Record<string, string> = {
    listed: '已上市',
    preparing_listing: '准备上市',
    pre_ipo: 'pre-IPO',
    unlisted: '未上市',
    any: '均可',
    unknown: '未知',
  };
  const parts = [
    item.preferred_listed_status ? status[item.preferred_listed_status] || item.preferred_listed_status : null,
    item.listing_board_requirement_summary,
    item.financing_stage_requirement_summary,
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

function marketCapRangeLabel(item: BuyerIntent): string {
  if (item.market_cap_range_summary) return item.market_cap_range_summary;
  const min = item.min_market_cap_yuan ? `${(Number(item.min_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  const max = item.max_market_cap_yuan ? `${(Number(item.max_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  if (min && max) return `${min}-${max}`;
  if (min) return `≥${min}`;
  if (max) return `≤${max}`;
  return '-';
}

function compactRequirementNotes(item: BuyerIntent): string {
  const parts = [
    item.max_debt_ratio ? `负债率≤${Number(item.max_debt_ratio).toFixed(0)}%` : null,
    item.max_premium_rate ? `溢价≤${Number(item.max_premium_rate).toFixed(0)}%` : item.premium_tolerance_summary,
    item.major_risk_tolerance_summary,
    item.buyer_industry_advantage_summary,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '暂无补充约束';
}

function PartiesList({
  externalShowCreate,
  onExternalCreateClose,
  refreshKey,
  onCreated,
}: {
  externalShowCreate: boolean;
  onExternalCreateClose: () => void;
  refreshKey: number;
  onCreated: () => void;
}) {
  const [items, setItems] = useState<BuyerParty[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const showCreate = externalShowCreate;

  const fetchData = (q?: string) => {
    setLoading(true);
    buyerParties.list({ q: q || undefined, limit: 50 })
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, [refreshKey]);

  return (
    <>
      <div className="flex items-center gap-2">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && fetchData(searchQuery)}
            placeholder="搜索买家名称..."
            className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 bg-white"
          />
        </div>
        <button onClick={() => fetchData(searchQuery)} className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-600 hover:text-brand-600 bg-white">搜索</button>
      </div>

      <div className="bg-white border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 font-medium text-gray-600">买家名称</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">类型</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">地区</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">主营业务</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">状态</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center"><div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" /></td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">暂无买家主体</td></tr>
            ) : items.map((item) => (
              <tr key={item.id} className="hover:bg-brand-50/30 transition-colors">
                <td className="px-4 py-3">
                  <Link to={`/buyers/${item.id}`} className="font-medium text-gray-900 hover:text-brand-600 transition-colors">
                    {item.buyer_name}
                  </Link>
                  {item.legal_name && <span className="text-xs text-gray-400 ml-2">{item.legal_name}</span>}
                </td>
                <td className="px-4 py-3 text-gray-600">{item.buyer_type || '-'}</td>
                <td className="px-4 py-3 text-gray-600">{item.region_province || '-'}</td>
                <td className="px-4 py-3 text-gray-600 truncate max-w-[200px]">{item.main_business || '-'}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`text-xs px-2 py-0.5 font-medium ${item.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>
                    {item.status === 'active' ? '活跃' : item.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-center">
                  <Link to={`/buyers/${item.id}`} className="text-xs text-brand-600 hover:text-brand-700 font-medium">查看</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreatePartyModal onClose={onExternalCreateClose} onCreated={() => { onExternalCreateClose(); onCreated(); fetchData(); }} />
      )}
    </>
  );
}

type IntentStep = 'buyer_link' | 'buyer_search' | 'buyer_new' | 'intent_details';
type BuyerLinkChoice = 'link_existing' | 'create_new' | 'no_link';

function CreateIntentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [step, setStep] = useState<IntentStep>('buyer_link');
  const [linkChoice, setLinkChoice] = useState<BuyerLinkChoice | null>(null);
  const [selectedParty, setSelectedParty] = useState<BuyerParty | null>(null);
  const [newPartyName, setNewPartyName] = useState('');
  const [dedupResults, setDedupResults] = useState<BuyerParty[]>([]);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<BuyerParty[]>([]);
  const [searching, setSearching] = useState(false);
  const [form, setForm] = useState<BuyerIntentCreate>({ intent_name: '' });
  const [saving, setSaving] = useState(false);

  const handleBuyerLinkChoice = (choice: BuyerLinkChoice) => {
    setLinkChoice(choice);
    if (choice === 'link_existing') setStep('buyer_search');
    else if (choice === 'create_new') setStep('buyer_new');
    else setStep('intent_details');
  };

  const handleSearch = async (q: string) => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const results = await buyerParties.list({ q: q.trim(), limit: 10 });
      setSearchResults(results);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleNewPartyCheck = async () => {
    if (!newPartyName.trim()) return;
    setSearching(true);
    try {
      const results = await buyerParties.list({ q: newPartyName.trim(), limit: 5 });
      setDedupResults(results);
      setDedupChecked(true);
    } catch {
      setDedupResults([]);
      setDedupChecked(true);
    } finally {
      setSearching(false);
    }
  };

  const handleSelectExisting = (party: BuyerParty) => {
    setSelectedParty(party);
    setStep('intent_details');
  };

  const handleConfirmNewParty = async () => {
    if (!newPartyName.trim()) return;
    setSaving(true);
    try {
      const created = await buyerParties.create({ buyer_name: newPartyName.trim() });
      setSelectedParty(created);
      setStep('intent_details');
    } catch {
      alert('创建买家主体失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.intent_name.trim()) return;
    setSaving(true);
    try {
      await buyerIntents.create({
        ...form,
        buyer_party_id: selectedParty?.id,
      });
      onCreated();
    } catch {
      alert('创建失败');
    } finally {
      setSaving(false);
    }
  };

  const stepTitles: Record<IntentStep, string> = {
    buyer_link: '新建买家意向 — 关联买家',
    buyer_search: '新建买家意向 — 搜索买家',
    buyer_new: '新建买家意向 — 新建买家主体',
    intent_details: '新建买家意向 — 意向详情',
  };

  return (
    <Modal title={stepTitles[step]} onClose={onClose}>
      {/* Step indicator */}
      <div className="flex items-center gap-1.5 mb-5">
        {(['buyer_link', 'intent_details'] as const).map((s, i) => (
          <div key={s} className="flex items-center gap-1.5">
            <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium ${
              step === s || (i === 1 && (step === 'intent_details'))
                ? 'bg-brand-600 text-white'
                : step === 'intent_details' && s === 'buyer_link'
                  ? 'bg-emerald-500 text-white'
                  : 'bg-gray-200 text-gray-500'
            }`}>
              {i === 0 && step === 'intent_details' ? '✓' : i + 1}
            </div>
            <span className="text-xs text-gray-500">{i === 0 ? '关联买家' : '意向信息'}</span>
            {i === 0 && <div className="w-6 h-px bg-gray-200" />}
          </div>
        ))}
      </div>

      {/* Step 1a: Link choice */}
      {step === 'buyer_link' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600 mb-4">请选择如何关联买家主体：</p>
          {[
            { key: 'link_existing' as BuyerLinkChoice, label: '关联已有买家', desc: '从现有买家主体中搜索并关联' },
            { key: 'create_new' as BuyerLinkChoice, label: '新建买家主体', desc: '先创建买家主体，再建意向' },
            { key: 'no_link' as BuyerLinkChoice, label: '暂不关联', desc: '直接创建意向，后续再关联买家' },
          ].map((opt) => (
            <button
              key={opt.key}
              onClick={() => handleBuyerLinkChoice(opt.key)}
              className={`w-full text-left px-4 py-3 border transition-colors ${
                linkChoice === opt.key ? 'border-brand-500 bg-brand-50' : 'border-gray-200 hover:border-gray-300 bg-white'
              }`}
            >
              <div className="text-sm font-medium text-gray-900">{opt.label}</div>
              <div className="text-xs text-gray-500 mt-0.5">{opt.desc}</div>
            </button>
          ))}
        </div>
      )}

      {/* Step 1b: Search existing buyer */}
      {step === 'buyer_search' && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch(searchQuery)}
              placeholder="输入买家名称搜索..."
              className="input flex-1"
              autoFocus
            />
            <button
              onClick={() => handleSearch(searchQuery)}
              disabled={searching}
              className="px-3 py-2 bg-brand-600 text-white text-sm hover:bg-brand-700 disabled:opacity-50"
            >
              {searching ? '搜索中' : '搜索'}
            </button>
          </div>
          {searchResults.length > 0 && (
            <div className="border border-gray-200 divide-y divide-gray-100 max-h-48 overflow-y-auto">
              {searchResults.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleSelectExisting(p)}
                  className="w-full text-left px-4 py-2.5 hover:bg-brand-50 transition-colors"
                >
                  <span className="text-sm font-medium text-gray-900">{p.buyer_name}</span>
                  {p.legal_name && <span className="text-xs text-gray-400 ml-2">{p.legal_name}</span>}
                  {p.region_province && <span className="text-xs text-gray-400 ml-2">· {p.region_province}</span>}
                </button>
              ))}
            </div>
          )}
          {searchResults.length === 0 && searchQuery && !searching && (
            <p className="text-sm text-gray-400 text-center py-3">未找到匹配买家</p>
          )}
          <div className="flex justify-between pt-2">
            <button onClick={() => setStep('buyer_link')} className="px-3 py-2 text-sm border border-gray-200 text-gray-700">返回</button>
            <button onClick={() => { setStep('intent_details'); }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">跳过关联</button>
          </div>
        </div>
      )}

      {/* Step 1c: Create new buyer party */}
      {step === 'buyer_new' && (
        <div className="space-y-3">
          <Field label="买家名称 *">
            <div className="flex gap-2">
              <input
                type="text"
                value={newPartyName}
                onChange={(e) => { setNewPartyName(e.target.value); setDedupChecked(false); setDedupResults([]); }}
                placeholder="例如：浙江某国资平台"
                className="input flex-1"
                autoFocus
              />
              <button
                onClick={handleNewPartyCheck}
                disabled={searching || !newPartyName.trim()}
                className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap"
              >
                {searching ? '查重中' : '查重'}
              </button>
            </div>
          </Field>
          {dedupChecked && dedupResults.length > 0 && (
            <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
              <p className="text-xs font-medium text-amber-700">发现相似买家，请确认是否已存在：</p>
              {dedupResults.slice(0, 5).map((p) => (
                <div key={p.id} className="flex items-center justify-between">
                  <span className="text-sm text-gray-800">{p.buyer_name}</span>
                  <button onClick={() => handleSelectExisting(p)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">关联它</button>
                </div>
              ))}
            </div>
          )}
          {dedupChecked && dedupResults.length === 0 && (
            <p className="text-xs text-emerald-600">未发现重名买家</p>
          )}
          <div className="flex justify-between pt-2">
            <button onClick={() => setStep('buyer_link')} className="px-3 py-2 text-sm border border-gray-200 text-gray-700">返回</button>
            <button
              onClick={handleConfirmNewParty}
              disabled={saving || !newPartyName.trim()}
              className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {saving ? '创建中...' : '创建并继续'}
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Intent details */}
      {step === 'intent_details' && (
        <form onSubmit={handleSubmit} className="space-y-4">
          {selectedParty && (
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border border-gray-200 text-sm">
              <span className="text-gray-500">关联买家：</span>
              <span className="font-medium text-gray-900">{selectedParty.buyer_name}</span>
            </div>
          )}
          <Field label="意向名称 *">
            <input
              type="text"
              value={form.intent_name}
              onChange={(e) => setForm({ ...form, intent_name: e.target.value })}
              className="input"
              placeholder="例如：浙江国资医药健康并表需求"
              autoFocus
            />
          </Field>
          <Field label="原始需求描述">
            <textarea
              value={form.raw_requirement_text || ''}
              onChange={(e) => setForm({ ...form, raw_requirement_text: e.target.value })}
              className="input min-h-[80px] resize-y"
              placeholder="自然语言描述买家收购需求"
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="行业">
              <input type="text" value={form.industry_primary || ''} onChange={(e) => setForm({ ...form, industry_primary: e.target.value })} className="input" placeholder="healthcare" />
            </Field>
            <Field label="地区范围">
              <input type="text" value={form.region_scope_summary || ''} onChange={(e) => setForm({ ...form, region_scope_summary: e.target.value })} className="input" placeholder="浙江优先，长三角可接受" />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="最低利润 (元)">
              <input type="number" value={form.min_net_profit_yuan || ''} onChange={(e) => setForm({ ...form, min_net_profit_yuan: Number(e.target.value) || undefined })} className="input" placeholder="20000000" />
            </Field>
            <Field label="PE上限">
              <input type="number" value={form.max_pe || ''} onChange={(e) => setForm({ ...form, max_pe: Number(e.target.value) || undefined })} className="input" placeholder="13" />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="最低市值 (元)">
              <input type="number" value={form.min_market_cap_yuan || ''} onChange={(e) => setForm({ ...form, min_market_cap_yuan: Number(e.target.value) || undefined })} className="input" placeholder="500000000" />
            </Field>
            <Field label="最高市值 (元)">
              <input type="number" value={form.max_market_cap_yuan || ''} onChange={(e) => setForm({ ...form, max_market_cap_yuan: Number(e.target.value) || undefined })} className="input" placeholder="3000000000" />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="上市状态">
              <select value={form.preferred_listed_status || ''} onChange={(e) => setForm({ ...form, preferred_listed_status: e.target.value || undefined })} className="input">
                <option value="">未明确</option>
                <option value="listed">已上市</option>
                <option value="preparing_listing">准备上市</option>
                <option value="unlisted">未上市</option>
                <option value="any">均可</option>
                <option value="unknown">未知</option>
              </select>
            </Field>
            <Field label="并表要求">
              <select value={form.requires_consolidation || ''} onChange={(e) => setForm({ ...form, requires_consolidation: e.target.value || undefined })} className="input">
                <option value="">未明确</option>
                <option value="yes">需要并表</option>
                <option value="no">不需要并表</option>
                <option value="unknown">未知</option>
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="上市板块">
              <input type="text" value={form.listing_board_requirement_summary || ''} onChange={(e) => setForm({ ...form, listing_board_requirement_summary: e.target.value })} className="input" placeholder="主板 / 创业板 / 科创板 / 北交所" />
            </Field>
            <Field label="阶段明细">
              <input type="text" value={form.financing_stage_requirement_summary || ''} onChange={(e) => setForm({ ...form, financing_stage_requirement_summary: e.target.value })} className="input" placeholder="pre-IPO / A轮 / 辅导备案" />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="溢价上限 (%)">
              <input type="number" value={form.max_premium_rate || ''} onChange={(e) => setForm({ ...form, max_premium_rate: Number(e.target.value) || undefined })} className="input" placeholder="20" />
            </Field>
            <Field label="负债率上限 (%)">
              <input type="number" value={form.max_debt_ratio || ''} onChange={(e) => setForm({ ...form, max_debt_ratio: Number(e.target.value) || undefined })} className="input" placeholder="65" />
            </Field>
          </div>
          <Field label="其他要求 / 排除项">
            <textarea
              value={form.negative_summary || ''}
              onChange={(e) => setForm({ ...form, negative_summary: e.target.value })}
              className="input min-h-[60px] resize-y"
              placeholder="例如：不接受重大诉讼、冻结、执行或违规违法风险"
            />
          </Field>
          <div className="flex justify-between pt-2">
            <button type="button" onClick={() => setStep('buyer_link')} className="px-3 py-2 text-sm border border-gray-200 text-gray-700">返回</button>
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
              <button type="submit" disabled={saving || !form.intent_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
                {saving ? '创建中...' : '创建意向'}
              </button>
            </div>
          </div>
        </form>
      )}
    </Modal>
  );
}

function CreatePartyModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<BuyerPartyCreate>({ buyer_name: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.buyer_name.trim()) return;
    setSaving(true);
    try {
      await buyerParties.create(form);
      onCreated();
    } catch {
      alert('创建失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="新建买家主体" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="买家名称 *">
          <input type="text" value={form.buyer_name} onChange={(e) => setForm({ ...form, buyer_name: e.target.value })} className="input" placeholder="例如：浙江某国资平台" autoFocus />
        </Field>
        <Field label="公司全称">
          <input type="text" value={form.legal_name || ''} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} className="input" placeholder="浙江某国资平台有限公司" />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="买家类型">
            <input type="text" value={form.buyer_type || ''} onChange={(e) => setForm({ ...form, buyer_type: e.target.value })} className="input" placeholder="state_owned_platform" />
          </Field>
          <Field label="所在省份">
            <input type="text" value={form.region_province || ''} onChange={(e) => setForm({ ...form, region_province: e.target.value })} className="input" placeholder="浙江省" />
          </Field>
        </div>
        <Field label="主营业务">
          <input type="text" value={form.main_business || ''} onChange={(e) => setForm({ ...form, main_business: e.target.value })} className="input" placeholder="国资产业投资与并购整合" />
        </Field>
        <Field label="画像摘要">
          <textarea value={form.profile_summary || ''} onChange={(e) => setForm({ ...form, profile_summary: e.target.value })} className="input min-h-[60px] resize-y" />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
          <button type="submit" disabled={saving || !form.buyer_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
            {saving ? '创建中...' : '创建'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white border border-gray-200 shadow-lg w-full max-w-lg mx-4 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
