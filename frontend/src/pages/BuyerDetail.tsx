import { useEffect, useState } from 'react';
import { ArrowLeft, Loader2, Plus, X } from 'lucide-react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { BuyerInfo } from '../components/BuyerIntentWorkspace';
import { buyerIntents, buyerParties } from '../lib/api';
import type { BuyerIntent, BuyerParty } from '../types/api';

export default function BuyerDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [party, setParty] = useState<BuyerParty | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([buyerParties.get(id), buyerParties.intents(id)])
      .then(([nextParty, intents]) => {
        const requestedId = searchParams.get('intentId');
        const destination =
          intents.find((intent) => intent.id === requestedId) ||
          intents.find((intent) => intent.status === 'active') ||
          intents[0];
        if (destination) {
          navigate(`/buyer-intents/${destination.id}`, { replace: true });
          return;
        }
        setParty(nextParty);
      })
      .catch(() => navigate('/buyers', { replace: true }))
      .finally(() => setLoading(false));
  }, [id, navigate, searchParams]);

  if (loading) {
    return <div className="flex items-center justify-center py-20 text-sm text-gray-400"><Loader2 className="mr-2 h-5 w-5 animate-spin text-brand-600" />正在加载</div>;
  }
  if (!party) return null;

  return (
    <div className="space-y-5">
      <header className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link to="/buyers" className="p-1.5 text-gray-400 hover:text-gray-700"><ArrowLeft className="h-4 w-4" /></Link>
          <div className="min-w-0"><h1 className="truncate text-lg font-semibold text-gray-900">{party.buyer_name}</h1><p className="mt-1 text-xs text-gray-500">该买家尚未录入并购需求</p></div>
        </div>
        <button type="button" onClick={() => setDialogOpen(true)} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"><Plus className="h-4 w-4" />录入并购需求</button>
      </header>
      <div className="border border-gray-200 bg-white p-5"><BuyerInfo party={party} onPartySaved={setParty} /></div>
      {dialogOpen ? <NewRequirementDialog party={party} onClose={() => setDialogOpen(false)} onCreated={(intent) => navigate(`/buyer-intents/${intent.id}`, { replace: true })} /> : null}
    </div>
  );
}

function NewRequirementDialog({ party, onClose, onCreated }: { party: BuyerParty; onClose: () => void; onCreated: (intent: BuyerIntent) => void }) {
  const [name, setName] = useState(() => `${party.buyer_name}-并购需求（${new Date().toISOString().slice(0, 7)}）`);
  const [rawText, setRawText] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const created = await buyerIntents.create({ buyer_party_id: party.id, intent_name: name.trim(), raw_requirement_text: rawText.trim() || undefined });
      if (rawText.trim()) await buyerIntents.parse(created.id, { raw_requirement_text: rawText.trim() });
      onCreated(created);
    } catch (error) {
      alert(error instanceof Error ? error.message : '录入并购需求失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4">
      <div className="w-full max-w-2xl border border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4"><h2 className="text-base font-semibold text-gray-900">录入并购需求</h2><button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700"><X className="h-4 w-4" /></button></div>
        <div className="space-y-4 p-5">
          <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">需求名称</span><input className="input" value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">需求材料</span><textarea className="input min-h-48 resize-y" value={rawText} onChange={(event) => setRawText(event.target.value)} placeholder="可填写行业、地区、利润、市值或估值、PE、股权比例、交易方式及排除项。" /></label>
        </div>
        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4"><button type="button" onClick={onClose} className="border border-gray-200 px-4 py-2 text-sm text-gray-700">取消</button><button type="button" onClick={() => void submit()} disabled={saving || !name.trim()} className="inline-flex items-center gap-2 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{saving ? '提交中' : '提交'}</button></div>
      </div>
    </div>
  );
}
