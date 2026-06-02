import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Search, X, ChevronDown, ChevronUp, Sparkles, MessageSquarePlus } from 'lucide-react';
import { sellerTargets } from '../lib/api';
import type { SellerTarget, SellerTargetCreate } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';

export default function Targets() {
  const [items, setItems] = useState<SellerTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [updateDrawer, setUpdateDrawer] = useState<{ open: boolean; targetId?: string; targetName?: string }>({ open: false });

  const fetchTargets = (q?: string) => {
    setLoading(true);
    sellerTargets.list({ q: q || undefined, limit: 50 })
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchTargets(); }, []);

  const handleSearch = () => { fetchTargets(searchQuery); };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">标的管理</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建标的
          </button>
          <button className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors bg-white">
            批量调研
          </button>
        </div>
      </div>

      {/* Search + Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="搜索标的名称..."
            className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 transition-colors bg-white"
          />
        </div>
        <select className="px-3 py-2 border border-gray-200 text-sm text-gray-600 bg-white">
          <option>行业 全部</option>
        </select>
        <select className="px-3 py-2 border border-gray-200 text-sm text-gray-600 bg-white">
          <option>地区 全部</option>
        </select>
        <select className="px-3 py-2 border border-gray-200 text-sm text-gray-600 bg-white">
          <option>状态 全部</option>
        </select>
        <select className="px-3 py-2 border border-gray-200 text-sm text-gray-600 bg-white">
          <option>信息 全部</option>
        </select>
        <button onClick={handleSearch} className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-600 hover:text-brand-600 transition-colors bg-white">
          搜索
        </button>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-4 py-3 font-medium text-gray-600">标的名称</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">行业</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">地区</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">营收</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">利润</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">估值</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">PE</th>
                <th className="text-center px-4 py-3 font-medium text-gray-600">状态</th>
                <th className="text-center px-4 py-3 font-medium text-gray-600">信息</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center">
                    <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" />
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center text-gray-400">暂无标的数据</td>
                </tr>
              ) : (
                items.map((item) => (
                  <TargetRow
                    key={item.id}
                    item={item}
                    expanded={expandedId === item.id}
                    onToggleExpand={() => setExpandedId(expandedId === item.id ? null : item.id)}
                    onOpenUpdateDrawer={() => setUpdateDrawer({ open: true, targetId: item.id, targetName: item.target_name })}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showCreateModal && (
        <CreateTargetModal
          onClose={() => setShowCreateModal(false)}
          onCreated={() => { setShowCreateModal(false); fetchTargets(); }}
        />
      )}

      <BusinessUpdateDrawer
        open={updateDrawer.open}
        onClose={() => setUpdateDrawer({ open: false })}
        defaultTargetId={updateDrawer.targetId}
        defaultTargetName={updateDrawer.targetName}
        onSuccess={() => fetchTargets(searchQuery)}
      />
    </div>
  );
}

function TargetRow({
  item,
  expanded,
  onToggleExpand,
  onOpenUpdateDrawer,
}: {
  item: SellerTarget;
  expanded: boolean;
  onToggleExpand: () => void;
  onOpenUpdateDrawer: () => void;
}) {
  return (
    <>
      <tr className="hover:bg-brand-50/30 transition-colors">
        <td className="px-4 py-3">
          <div className="flex items-center gap-1">
            <button onClick={onToggleExpand} className="text-gray-400 hover:text-gray-600">
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            <Link to={`/targets/${item.id}`} className="font-medium text-gray-900 hover:text-brand-600 transition-colors">
              {item.target_name}
            </Link>
          </div>
        </td>
        <td className="px-4 py-3 text-gray-600">{item.industry_primary || '-'}</td>
        <td className="px-4 py-3 text-gray-600">{item.headquarter_province || '-'}{item.headquarter_city ? ` ${item.headquarter_city}` : ''}</td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">
          {item.current_revenue_yuan ? formatYuan(item.current_revenue_yuan) : '-'}
        </td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">
          {item.current_net_profit_yuan ? formatYuan(item.current_net_profit_yuan) : '-'}
        </td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">
          {item.valuation_yuan ? formatYuan(item.valuation_yuan) : '-'}
        </td>
        <td className="px-4 py-3 text-right text-gray-600 font-mono">
          {item.pe_ratio ? Number(item.pe_ratio).toFixed(1) : '-'}
        </td>
        <td className="px-4 py-3 text-center">
          <StatusBadge status={item.recommendation_status} type="recommendation" />
        </td>
        <td className="px-4 py-3 text-center">
          <StatusBadge status={item.information_status} type="information" />
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-1">
            <Link
              to={`/recommendations?mode=target-to-buyer&targetId=${item.id}`}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 transition-colors"
            >
              <Sparkles className="w-3 h-3" />
              推荐买家
            </Link>
            <span className="text-gray-200">|</span>
            <button
              onClick={onOpenUpdateDrawer}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 transition-colors"
            >
              <MessageSquarePlus className="w-3 h-3" />
              录入更新
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50/50">
          <td colSpan={10} className="px-8 py-2.5">
            <p className="text-xs text-gray-600 line-clamp-2">
              {item.business_summary || '暂无摘要'}
              {item.information_status === 'insufficient' && (
                <span className="text-amber-600 ml-2">· 信息不足</span>
              )}
            </p>
          </td>
        </tr>
      )}
    </>
  );
}

function StatusBadge({ status, type }: { status: string; type: 'recommendation' | 'information' }) {
  const colors =
    type === 'recommendation'
      ? status === 'recommendable'
        ? 'bg-emerald-50 text-emerald-700'
        : 'bg-gray-100 text-gray-600'
      : status === 'normal'
        ? 'bg-emerald-50 text-emerald-700'
        : status === 'insufficient'
          ? 'bg-amber-50 text-amber-700'
          : 'bg-gray-100 text-gray-600';

  const label =
    type === 'recommendation'
      ? status === 'recommendable' ? '可推荐' : '暂不推荐'
      : status === 'normal' ? '信息完善' : status === 'insufficient' ? '信息不足' : status;

  return <span className={`text-xs px-2 py-0.5 font-medium ${colors}`}>{label}</span>;
}

function formatYuan(val: string): string {
  const num = Number(val);
  if (num >= 100000000) return `${(num / 100000000).toFixed(1)}亿`;
  if (num >= 10000) return `${(num / 10000).toFixed(0)}万`;
  return String(num);
}

function CreateTargetModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<SellerTargetCreate>({ target_name: '' });
  const [saving, setSaving] = useState(false);
  const [duplicates, setDuplicates] = useState<SellerTarget[]>([]);
  const [nameWarning, setNameWarning] = useState('');

  const checkDuplicate = (name: string) => {
    if (name.trim().length < 2) {
      setDuplicates([]);
      setNameWarning(name.trim().length === 1 ? '名称过短，建议补充公司全称或地区' : '');
      return;
    }
    setNameWarning('');
    sellerTargets.list({ q: name.trim(), limit: 5 })
      .then((results) => setDuplicates(results.filter((r) => r.target_name !== name.trim())))
      .catch(() => {});
  };

  const handleNameChange = (value: string) => {
    setForm({ ...form, target_name: value });
    const timer = setTimeout(() => checkDuplicate(value), 300);
    return () => clearTimeout(timer);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.target_name.trim()) return;
    setSaving(true);
    try {
      await sellerTargets.create(form);
      onCreated();
    } catch {
      alert('创建失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="新建标的" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="标的名称 *" required>
          <input
            type="text"
            value={form.target_name}
            onChange={(e) => handleNameChange(e.target.value)}
            className="input"
            placeholder="例如：上海启元项目"
            autoFocus
          />
          {nameWarning && (
            <p className="text-xs text-amber-600 mt-1">{nameWarning}</p>
          )}
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="行业">
            <input type="text" value={form.industry_primary || ''} onChange={(e) => setForm({ ...form, industry_primary: e.target.value })} className="input" placeholder="可选，留空由系统解析" />
          </Field>
          <Field label="地区">
            <input type="text" value={form.headquarter_province || ''} onChange={(e) => setForm({ ...form, headquarter_province: e.target.value })} className="input" placeholder="可选，留空由系统解析" />
          </Field>
        </div>
        <Field label="一句话描述">
          <input
            type="text"
            value={form.business_summary || ''}
            onChange={(e) => setForm({ ...form, business_summary: e.target.value })}
            className="input"
            placeholder="简要描述标的情况"
          />
        </Field>

        {duplicates.length > 0 && (
          <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-800">疑似重复</p>
            {duplicates.map((d) => (
              <div key={d.id} className="flex items-center justify-between text-xs">
                <span className="text-gray-700">
                  {d.target_name} · {d.headquarter_province || '未知'} · {d.industry_primary || '未知'}
                </span>
                <Link
                  to={`/targets/${d.id}`}
                  className="text-brand-600 hover:text-brand-700 font-medium shrink-0"
                  onClick={onClose}
                >
                  更新它
                </Link>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700 hover:border-gray-300 transition-colors">取消</button>
          <button type="submit" disabled={saving || !form.target_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-50">
            {saving ? '创建中...' : (duplicates.length > 0 ? '仍然新建' : '创建')}
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
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label} {required && <span className="text-brand-600">*</span>}
      </label>
      {children}
    </div>
  );
}
