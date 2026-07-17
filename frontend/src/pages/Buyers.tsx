import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Plus } from 'lucide-react';
import IntentsList from '../features/buyers/IntentsList';

export default function Buyers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [showCreateIntent, setShowCreateIntent] = useState(false);
  const [intentRefreshKey, setIntentRefreshKey] = useState(0);

  useEffect(() => {
    const action = searchParams.get('action');
    if (action !== 'new-intent' && action !== 'new-party') return;
    const next = new URLSearchParams(searchParams);
    next.delete('tab');
    setShowCreateIntent(true);
    next.delete('action');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">买家管理</h1>
          <p className="text-xs text-gray-400 mt-1">管理买家及其当前并购需求</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateIntent(true)}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建买家
          </button>
        </div>
      </div>

      <IntentsList
        externalShowCreate={showCreateIntent}
        onExternalCreateClose={() => setShowCreateIntent(false)}
        refreshKey={intentRefreshKey}
        onCreated={() => setIntentRefreshKey((k) => k + 1)}
      />
    </div>
  );
}
