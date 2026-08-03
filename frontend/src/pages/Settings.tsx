import { useCallback, useEffect, useState } from 'react';
import { Database, Server, Settings2 } from 'lucide-react';
import IndustryDictionary from '../features/settings/IndustryDictionary';
import ModelSection from '../features/settings/ModelSection';
import NodeList from '../features/settings/NodeList';
import { ErrorState, Loading, TabButton } from '../features/settings/shared';
import { modelConfig } from '../lib/api';
import { isAdmin } from '../lib/auth';
import type { ModelConfigSettingsPage } from '../types/api';

type SettingsTab = 'nodes' | 'models' | 'dictionary';

export default function Settings() {
  const [tab, setTab] = useState<SettingsTab>('nodes');
  if (!isAdmin()) {
    return <div className="border border-gray-200 bg-white px-5 py-10 text-center text-sm text-gray-500">设置仅管理员可见。</div>;
  }
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">设置</h1>
        <p className="mt-1 text-xs text-gray-500">管理 AI 节点的模型与提示词、模型与搜索服务、平台数据字典。</p>
      </header>
      <div className="flex border-b border-gray-200">
        <TabButton active={tab === 'nodes'} onClick={() => setTab('nodes')} icon={<Settings2 className="h-4 w-4" />}>AI 节点</TabButton>
        <TabButton active={tab === 'models'} onClick={() => setTab('models')} icon={<Server className="h-4 w-4" />}>模型与搜索</TabButton>
        <TabButton active={tab === 'dictionary'} onClick={() => setTab('dictionary')} icon={<Database className="h-4 w-4" />}>数据字典</TabButton>
      </div>
      {tab === 'dictionary' ? <IndustryDictionary /> : <AiSettings tab={tab} />}
    </div>
  );
}

function AiSettings({ tab }: { tab: 'nodes' | 'models' }) {
  const [data, setData] = useState<ModelConfigSettingsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await modelConfig.settingsPage());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取 AI 设置失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error || '读取 AI 设置失败'} onRetry={load} />;

  // 搜索与 OCR 是外部 HTTP 服务，不是可绑定到 AI 节点的模型。
  const selectableModels = data.providers.filter(
    (model) => model.is_active && !['search', 'ocr'].includes(model.provider_type),
  );

  if (tab === 'models') {
    return (
      <ModelSection
        providers={data.providers}
        nodes={data.nodes}
        directKeyAvailable={Boolean(data.capabilities.direct_key_encryption_configured)}
        onRefresh={load}
      />
    );
  }
  return (
    <NodeList
      nodes={data.nodes}
      models={selectableModels}
      variableLabels={data.prompt_variable_labels}
      onRefresh={load}
    />
  );
}
