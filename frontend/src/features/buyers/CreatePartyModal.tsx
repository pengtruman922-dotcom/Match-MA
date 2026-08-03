import { useState } from 'react';
import { buyerParties } from '../../lib/api';
import type { BuyerPartyCreate, BuyerPartyDedupCheck } from '../../types/api';
import Modal, { Field } from '../../components/Modal';
import { dedupMatchLabel } from './presentation';

export default function CreatePartyModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<BuyerPartyCreate>({ buyer_name: '' });
  const [saving, setSaving] = useState(false);
  const [dedupCheck, setDedupCheck] = useState<BuyerPartyDedupCheck | null>(null);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [checkingDedup, setCheckingDedup] = useState(false);

  const handleDedupCheck = async () => {
    if (!form.buyer_name.trim()) return;
    setCheckingDedup(true);
    try {
      const response = await buyerParties.dedupCheck({ q: form.buyer_name.trim(), limit: 5 });
      setDedupCheck(response);
      setDedupChecked(true);
    } catch {
      setDedupCheck(null);
      setDedupChecked(true);
    } finally {
      setCheckingDedup(false);
    }
  };

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
          <div className="flex gap-2">
            <input
              type="text"
              value={form.buyer_name}
              onChange={(e) => {
                setForm({ ...form, buyer_name: e.target.value });
                setDedupChecked(false);
                setDedupCheck(null);
              }}
              className="input flex-1"
              placeholder="例如：浙江某国资平台"
              autoFocus
            />
            <button
              type="button"
              onClick={handleDedupCheck}
              disabled={checkingDedup || !form.buyer_name.trim()}
              className="px-3 py-2 border border-gray-200 text-sm text-gray-700 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50 whitespace-nowrap"
            >
              {checkingDedup ? '查重中' : '查重'}
            </button>
          </div>
        </Field>
        {dedupChecked && Boolean(dedupCheck?.matches.length) && (
          <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-700">系统里已有同名或别名买家，请确认是否重复录入：</p>
            {dedupCheck!.matches.map((match) => (
              <div key={`${match.buyer_name}-${match.match_type}`} className="text-sm text-gray-800">
                <span className="font-medium">{match.buyer_name}</span>
                <span className="ml-2 text-xs text-amber-700">负责人：{match.owner_name || '未指派'}</span>
                <span className="ml-2 text-xs text-gray-500">匹配：{dedupMatchLabel(match.match_type)}</span>
              </div>
            ))}
          </div>
        )}
        {dedupChecked && !dedupCheck?.matches.length && (
          <p className="text-xs text-emerald-600">未发现同名买家。</p>
        )}
        <p className="text-xs leading-relaxed text-gray-500">创建后可在买家信息中统一维护所属行业、地区、联系人、联系方式和其他资料；这些资料会同步到同一买家的所有需求。</p>
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
