import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Loader2, MessageSquarePlus, Sparkles, UserRound } from 'lucide-react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import BuyerIntentWorkspace, {
  IntentParseBadge,
  IntentStatusBadge,
} from '../components/BuyerIntentWorkspace';
import type { BuyerWorkspaceTab } from '../components/BuyerIntentWorkspace';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';
import { businessUpdates, buyerIntents, buyerParties, users } from '../lib/api';
import { isAdmin } from '../lib/auth';
import { valueLabel } from '../lib/fieldLabels';
import type {
  AppUserOption,
  BuyerIntent,
  BuyerIntentFollowUp,
  BuyerIntentParseStatus,
  BuyerParty,
} from '../types/api';

export default function BuyerIntentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [intent, setIntent] = useState<BuyerIntent | null>(null);
  const [party, setParty] = useState<BuyerParty | null>(null);
  const [parseStatus, setParseStatus] = useState<BuyerIntentParseStatus | null>(null);
  const [followUps, setFollowUps] = useState<BuyerIntentFollowUp[]>([]);
  const [activeTab, setActiveTab] = useState<BuyerWorkspaceTab>(() => workspaceTab(searchParams.get('tab')));
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [statusSaving, setStatusSaving] = useState(false);
  const [ownerSaving, setOwnerSaving] = useState(false);
  const [ownerOptions, setOwnerOptions] = useState<AppUserOption[]>([]);
  const updateWatchRef = useRef(0);
  const admin = isAdmin();

  const load = useCallback(async (silent = false) => {
    if (!id) return;
    if (!silent) setLoading(true);
    try {
      const nextIntent = await buyerIntents.get(id);
      const [nextParty, nextParseStatus, nextFollowUps] = await Promise.all([
        nextIntent.buyer_party_id ? buyerParties.get(nextIntent.buyer_party_id).catch(() => null) : Promise.resolve(null),
        buyerIntents.parseStatus(id).catch(() => null),
        buyerIntents.followUps(id).catch(() => []),
      ]);
      setIntent(nextIntent);
      setParty(nextParty);
      setParseStatus(nextParseStatus);
      setFollowUps(nextFollowUps);
    } catch {
      navigate('/buyers');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => { updateWatchRef.current += 1; }, []);
  useEffect(() => {
    if (!admin) return;
    users.options().then(setOwnerOptions).catch(() => {});
  }, [admin]);

  const changeStatus = async (status: string) => {
    if (!intent || status === intent.status) return;
    setStatusSaving(true);
    try {
      setIntent(await buyerIntents.update(intent.id, { status }));
      setHistoryRefreshKey((current) => current + 1);
    } catch (error) {
      alert(error instanceof Error ? error.message : '更新推荐状态失败');
    } finally {
      setStatusSaving(false);
    }
  };

  const changeOwner = async (ownerUserId: string) => {
    if (!intent || ownerUserId === (intent.owner_user_id || '')) return;
    setOwnerSaving(true);
    try {
      setIntent(await buyerIntents.update(intent.id, { owner_user_id: ownerUserId || null }));
    } catch (error) {
      alert(error instanceof Error ? error.message : '更新负责人失败');
    } finally {
      setOwnerSaving(false);
    }
  };

  const watchBusinessUpdate = useCallback(async (businessUpdateId: string) => {
    const watchId = updateWatchRef.current + 1;
    updateWatchRef.current = watchId;
    const delays = [0, 2000, 3000, 5000, 10000, 15000, 30000, 60000, 60000];
    for (const delay of delays) {
      if (delay) await new Promise((resolve) => window.setTimeout(resolve, delay));
      if (updateWatchRef.current !== watchId) return;
      try {
        const update = await businessUpdates.get(businessUpdateId);
        await load(true);
        setHistoryRefreshKey((current) => current + 1);
        if (['applied', 'partially_applied', 'parsed', 'failed'].includes(update.processing_status)) return;
      } catch {
        return;
      }
    }
  }, [load]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm text-gray-400"><Loader2 className="mr-2 h-5 w-5 animate-spin text-brand-600" />正在加载</div>;
  if (!intent) return null;

  return (
    <div className="space-y-5">
      <header className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
        <div className="flex min-w-0 items-start gap-3">
          <Link to="/buyers" className="mt-0.5 p-1.5 text-gray-400 hover:text-gray-700"><ArrowLeft className="h-4 w-4" /></Link>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold text-gray-900">{intent.intent_name}</h1>
              <IntentStatusBadge status={intent.status} />
              <IntentParseBadge intent={intent} parseStatus={parseStatus} />
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span>买家：{party?.buyer_name || intent.buyer_name || '未关联买家'}</span>
              {party?.buyer_type ? <span>{valueLabel('buyer_type', party.buyer_type)}</span> : null}
              {party?.region_province || party?.region_city ? <span>· {party?.region_province}{party?.region_city}</span> : null}
              <span className="inline-flex items-center gap-1"><UserRound className="h-3 w-3" />负责人：{intent.owner_name || '未指派'}</span>
              <span>· 更新于 {formatDateTime(intent.updated_at)}</span>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {admin ? <label className="flex items-center gap-1 text-xs text-gray-500">负责人<select value={intent.owner_user_id || ''} onChange={(event) => void changeOwner(event.target.value)} disabled={ownerSaving} className="border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:opacity-50"><option value="">未指派</option>{ownerOptions.filter((option) => option.status === 'active').map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label> : null}
          <select value={intent.status} onChange={(event) => void changeStatus(event.target.value)} disabled={statusSaving} className="border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:opacity-50"><option value="active">持续推荐</option><option value="paused">暂停推荐</option><option value="closed">已结束</option></select>
          <button type="button" onClick={() => setDrawerOpen(true)} className="inline-flex items-center gap-1.5 border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:border-brand-500 hover:text-brand-700"><MessageSquarePlus className="h-3.5 w-3.5" />录入更新</button>
          <Link to={`/recommendations?mode=buyer-to-target&intentId=${intent.id}`} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"><Sparkles className="h-3.5 w-3.5" />推荐标的</Link>
        </div>
      </header>

      <BuyerIntentWorkspace
        intent={intent}
        party={party}
        parseStatus={parseStatus}
        followUps={followUps}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        historyRefreshKey={historyRefreshKey}
        onPartySaved={setParty}
        onIntentRefresh={load}
      />

      <BusinessUpdateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        defaultIntentId={intent.id}
        defaultIntentName={intent.intent_name}
        onSuccess={(businessUpdateId) => { void watchBusinessUpdate(businessUpdateId); }}
      />
    </div>
  );
}

function workspaceTab(value: string | null): BuyerWorkspaceTab { return value === 'buyer' || value === 'progress' || value === 'attachments' || value === 'followups' || value === 'history' ? value : 'intent'; }
function formatDateTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
