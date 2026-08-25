import { useEffect, useState } from 'react';
import { buyerParties, indicatorRegistry } from '../../lib/api';
import type { BuyerPartyCreate, BuyerPartyDedupCheck, IndicatorRegistryResponse } from '../../types/api';
import Modal, { Field } from '../../components/Modal';
import AdministrativeAreaPicker, { type AdministrativeAreaValue } from '../../components/AdministrativeAreaPicker';
import { dedupMatchLabel } from './presentation';

export default function CreatePartyModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<BuyerPartyCreate>({ buyer_name: '' });
  const [saving, setSaving] = useState(false);
  const [dedupCheck, setDedupCheck] = useState<BuyerPartyDedupCheck | null>(null);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [checkingDedup, setCheckingDedup] = useState(false);
  const [location, setLocation] = useState<AdministrativeAreaValue>({ province: '' });
  const [tagsText, setTagsText] = useState('');
  // 枚举中文名来自指标注册表，不在前端硬编码：注册表改一处，下拉跟着变。
  const [registry, setRegistry] = useState<IndicatorRegistryResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    indicatorRegistry.list('buyer_party').then((value) => { if (!cancelled) setRegistry(value); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const enumOptions = (column: string) =>
    registry?.indicators.find((item) => item.column === column)?.enum_options || [];

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
      await buyerParties.create({
        ...form,
        location_province: location.province || null,
        location_city: location.city || null,
        location_district: location.district || null,
        business_tags_json: splitTags(tagsText),
      });
      onCreated();
    } catch (error) {
      alert(error instanceof Error ? error.message : '创建失败');
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
        <Field label="所在地">
          <AdministrativeAreaPicker value={location} onChange={setLocation} />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="企业性质">
            <select className="input" value={form.ownership_type || 'unknown'} onChange={(e) => setForm({ ...form, ownership_type: e.target.value })}>
              {enumOptions('ownership_type').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </Field>
          <Field label="上市状态">
            <select className="input" value={form.listed_status || 'unknown'} onChange={(e) => setForm({ ...form, listed_status: e.target.value })}>
              {enumOptions('listed_status').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </Field>
        </div>
        <Field label="业务标签">
          <input type="text" className="input" value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="这家买家自己做什么，多个用顿号分隔，5 个以内" />
        </Field>
        <Field label="业务说明">
          <textarea className="input min-h-20 resize-y" value={form.business_summary || ''} onChange={(e) => setForm({ ...form, business_summary: e.target.value || null })} placeholder="主营业务与产业链位置，200 字左右" />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="联系人">
            <input type="text" className="input" value={form.contact_name || ''} onChange={(e) => setForm({ ...form, contact_name: e.target.value || null })} />
          </Field>
          <Field label="我方对接人">
            <input type="text" className="input" value={form.our_contact_name || ''} onChange={(e) => setForm({ ...form, our_contact_name: e.target.value || null })} />
          </Field>
        </div>
        <p className="text-xs leading-relaxed text-gray-500">财务信息（市值/估值、营收、经营现金流）与补充信息在创建后的「买家信息」中维护；这些资料会同步到同一买家的所有需求。</p>
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

/** 顿号、逗号、换行都算分隔符，与买家信息 tab 的标签输入同一套规则。 */
function splitTags(value: string): string[] {
  return [...new Set(value.split(/[、，,\n]/).map((item) => item.trim()).filter(Boolean))];
}
