import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Sparkles,
  MessageSquarePlus,
  Search as SearchIcon,
  UserRound,
  AlertCircle,
  FileText,
  Clock,
  Loader2,
  Trash2,
  Download,
  RefreshCw,
  ExternalLink,
} from 'lucide-react';
import { relations, sellerTargets, updateLogs } from '../lib/api';
import type {
  BuyerSellerRelation,
  RelationEvent,
  SellerTarget,
  TargetAttachmentItem,
  TargetFollowUp,
  UpdateLog,
} from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';
import {
  sellerTargetDisplayStatus,
  sellerTargetDisplayStatusClass,
  sellerTargetDisplayStatusLabel,
  sellerTargetStatusClass,
  sellerTargetStatusLabel,
} from '../lib/sellerTargetStatus';
import { fieldLabel, sourceTypeLabel, valueLabel } from '../lib/fieldLabels';

type Tab = 'info' | 'attachments' | 'relations' | 'history';

export default function TargetDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [target, setTarget] = useState<SellerTarget | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('info');
  const [logs, setLogs] = useState<UpdateLog[]>([]);
  const [relationItems, setRelationItems] = useState<BuyerSellerRelation[]>([]);
  const [relationEvents, setRelationEvents] = useState<RelationEvent[]>([]);
  const [followUps, setFollowUps] = useState<TargetFollowUp[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [lifecycleSaving, setLifecycleSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    sellerTargets.get(id)
      .then(setTarget)
      .catch(() => navigate('/targets'))
      .finally(() => setLoading(false));
    Promise.all([
      updateLogs.list({ entity_type: 'seller_target', entity_id: id }),
      relations.list({ seller_target_id: id, limit: 50 }),
      relations.listEvents({ seller_target_id: id, limit: 50 }),
      sellerTargets.followUps(id),
    ])
      .then(([nextLogs, nextRelations, nextEvents, nextFollowUps]) => {
        setLogs(nextLogs);
        setRelationItems(nextRelations);
        setRelationEvents(nextEvents);
        setFollowUps(nextFollowUps);
      })
      .catch(() => {});
  }, [id, navigate]);

  // Poll while a business-update parse is running so status/summary/follow-up
  // changes show up without a manual refresh.
  const parsing = target?.information_status === 'parsing' || target?.information_status === 'researching';
  useEffect(() => {
    if (!id || !parsing) return;
    const timer = window.setInterval(() => {
      sellerTargets
        .get(id)
        .then((fresh) => {
          setTarget(fresh);
          if (fresh.information_status !== 'parsing' && fresh.information_status !== 'researching') {
            Promise.all([
              updateLogs.list({ entity_type: 'seller_target', entity_id: id }),
              sellerTargets.followUps(id),
            ])
              .then(([nextLogs, nextFollowUps]) => {
                setLogs(nextLogs);
                setFollowUps(nextFollowUps);
              })
              .catch(() => {});
          }
        })
        .catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
  }, [id, parsing]);

  const handleLifecycleChange = async (value: string) => {
    if (!target || value === target.lifecycle_status) return;
    setLifecycleSaving(true);
    try {
      const updated = await sellerTargets.update(target.id, { lifecycle_status: value });
      setTarget(updated);
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新交易状态失败');
    } finally {
      setLifecycleSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!target) return null;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'info', label: '基本信息' },
    { key: 'attachments', label: '附件与证据' },
    { key: 'relations', label: '跟进记录' },
    { key: 'history', label: '更新记录' },
  ];

  return (
    <div className="space-y-5">
      {/* Breadcrumb + actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/targets" className="p-1.5 text-gray-400 hover:text-gray-600">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-lg font-semibold text-gray-900">{target.target_name}</h1>
            <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
              {target.industry_primary && <span>{target.industry_primary}</span>}
              {target.headquarter_province && <span>· {target.headquarter_province}{target.headquarter_city || ''}</span>}
              {target.current_net_profit_yuan && <span>· 利润{formatYuan(target.current_net_profit_yuan)}</span>}
              {target.asking_price_yuan && <span>· 报价{formatYuan(target.asking_price_yuan)}*</span>}
              <DisplayStatusBadge target={target} />
              <StatusBadge status={target.information_status} type="information" />
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={target.lifecycle_status}
            onChange={(event) => handleLifecycleChange(event.target.value)}
            disabled={lifecycleSaving}
            title="交易状态：已售出/已停售的标的会自动退出推荐候选池"
            className="px-2 py-1.5 text-sm border border-gray-200 text-gray-700 bg-white outline-none hover:border-brand-500 focus:border-brand-600 disabled:opacity-50"
          >
            <option value="active">在售中</option>
            <option value="sold">已售出</option>
            <option value="off_market">已停售</option>
          </select>
          <button
            onClick={() => setDrawerOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            录入更新
          </button>
          <Link
            to={`/recommendations?mode=target-to-buyer&targetId=${target.id}`}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5" />
            推荐买家
          </Link>
        </div>
      </div>

      {/* Tabs + Content + Sidebar */}
      <div className="grid grid-cols-12 gap-5">
        {/* Main content */}
        <div className="col-span-8">
          <div className="bg-white border border-gray-200">
            <div className="flex items-center border-b border-gray-100 px-5">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab.key
                      ? 'border-brand-600 text-brand-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="p-5">
              {activeTab === 'info' && <InfoTab target={target} />}
              {activeTab === 'attachments' && <AttachmentsTab targetId={target.id} />}
              {activeTab === 'relations' && (
                <FollowUpsTab
                  targetId={target.id}
                  followUps={followUps}
                  onChanged={setFollowUps}
                  relationItems={relationItems}
                  relationEvents={relationEvents}
                />
              )}
              {activeTab === 'history' && <HistoryTab logs={logs} />}
            </div>
          </div>
        </div>

        {/* Right sidebar */}
        <div className="col-span-4 space-y-4">
          <div className="bg-white border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
              自动更新待复核
            </h3>
            <p className="text-xs text-gray-400">暂无待复核项</p>
          </div>
          <div className="bg-white border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">信息缺口</h3>
            <div className="space-y-1.5 text-xs text-gray-600">
              {!target.can_consolidate || target.can_consolidate === 'unknown' ? (
                <p>- 是否可并表</p>
              ) : null}
              {!target.can_control || target.can_control === 'unknown' ? (
                <p>- 是否可控股</p>
              ) : null}
              {!target.current_revenue_yuan ? <p>- 营收</p> : null}
              {!target.current_net_profit_yuan ? <p>- 利润</p> : null}
              {!target.valuation_yuan ? <p>- 估值</p> : null}
              {target.can_consolidate && target.can_consolidate !== 'unknown' &&
               target.can_control && target.can_control !== 'unknown' &&
               target.current_revenue_yuan && target.current_net_profit_yuan && target.valuation_yuan && (
                <p className="text-emerald-600">信息完善</p>
              )}
            </div>
          </div>
        </div>
      </div>

      <BusinessUpdateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        defaultTargetId={target.id}
        defaultTargetName={target.target_name}
        onSuccess={() => {
          if (id) sellerTargets.get(id).then(setTarget).catch(() => {});
        }}
      />
    </div>
  );
}

function InfoTab({ target }: { target: SellerTarget }) {
  const groups = [
    {
      label: '身份',
      fields: [
        { label: '标的名称', value: target.target_name },
        { label: '标的主体', value: getSubjectDisplay(target) },
        { label: '类型', value: valueLabel('target_type', target.target_type) },
        { label: '上市状态', value: formatListedStatus(target.listed_status) },
      ],
    },
    {
      label: '行业业务',
      fields: [
        { label: '一级行业', value: target.industry_primary },
        { label: '二级行业', value: target.industry_secondary },
        { label: '业务摘要', value: target.business_summary },
      ],
    },
    {
      label: '财务',
      fields: [
        { label: '营收', value: target.current_revenue_yuan ? formatYuan(target.current_revenue_yuan) : null },
        { label: '利润', value: target.current_net_profit_yuan ? formatYuan(target.current_net_profit_yuan) : null },
      ],
    },
    {
      label: '估值交易',
      fields: [
        { label: '估值', value: target.valuation_yuan ? formatYuan(target.valuation_yuan) : null },
        { label: '估值时间', value: target.valuation_date },
        { label: '报价', value: target.asking_price_yuan ? formatYuan(target.asking_price_yuan) : null },
        { label: '报价时间', value: target.asking_price_date },
        { label: 'PE', value: target.pe_ratio ? Number(target.pe_ratio).toFixed(1) : null },
        { label: '出售比例', value: target.transfer_ratio_text || formatTransferRatio(target) },
        { label: '是否还卖', value: valueLabel('is_for_sale', target.is_for_sale) },
        { label: '可控股', value: valueLabel('can_control', target.can_control) },
        { label: '可并表', value: valueLabel('can_consolidate', target.can_consolidate) },
      ],
    },
    {
      label: '风险',
      fields: [
        { label: '风险摘要', value: target.risk_summary },
      ],
    },
  ];

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <div key={group.label}>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">{group.label}</h4>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2.5">
            {group.fields.map((field) => (
              <div key={field.label} className="flex items-baseline gap-2">
                <span className="text-xs text-gray-500 w-16 shrink-0">{field.label}</span>
                <span className="text-sm text-gray-800">{field.value || '-'}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function AttachmentsTab({ targetId }: { targetId: string }) {
  const [items, setItems] = useState<TargetAttachmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = () => {
    setLoading(true);
    setError(null);
    sellerTargets
      .attachments(targetId)
      .then((data) => setItems(data.items))
      .catch((err) => setError(err instanceof Error ? err.message : '附件读取失败'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, [targetId]);

  const handleDownload = async (item: TargetAttachmentItem) => {
    setDownloadingId(item.id);
    try {
      const response = await sellerTargets.downloadAttachment(targetId, item.id);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = item.file_name || 'attachment';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : '下载失败');
    } finally {
      setDownloadingId(null);
    }
  };

  const handleDelete = async (item: TargetAttachmentItem) => {
    if (!window.confirm('确认删除该材料？已入库的标的信息不会回滚。')) return;
    setDeletingId(item.id);
    try {
      await sellerTargets.deleteAttachment(targetId, item.id);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-gray-400">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />
        正在读取附件
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
        <p>{error}</p>
        <button onClick={refresh} className="mt-2 text-xs font-medium text-red-700 underline">
          重新加载
        </button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="text-center py-10">
        <FileText className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-500">暂无附件</p>
        <p className="text-xs text-gray-400 mt-1">新建标的或录入更新时上传的文件，会自动出现在这里。</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">共 {items.length} 个附件</p>
        <button
          onClick={refresh}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium border border-gray-200 text-gray-600 hover:border-brand-500 hover:text-brand-600"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          刷新
        </button>
      </div>

      <div className="divide-y divide-gray-100 border border-gray-100">
        {items.map((item) => (
          <AttachmentCard
            key={item.id}
            item={item}
            downloading={downloadingId === item.id}
            deleting={deletingId === item.id}
            onDownload={() => handleDownload(item)}
            onDelete={() => handleDelete(item)}
          />
        ))}
      </div>
    </div>
  );
}

function AttachmentCard({
  item,
  downloading,
  deleting,
  onDownload,
  onDelete,
}: {
  item: TargetAttachmentItem;
  downloading: boolean;
  deleting: boolean;
  onDownload: () => void;
  onDelete: () => void;
}) {
  const failed = item.display_status === 'failed';
  const latestJob = item.latest_job || {};
  const latestEvidence = item.latest_evidence || {};
  const relatedUpdate = item.related_business_updates[0] || {};
  const latestJobDebug = recordValue(latestJob.debug_ref);
  const evidencePage = stringValue(latestEvidence.page_no);
  const evidenceText = stringValue(latestEvidence.text_excerpt);
  const failedMessage =
    stringValue(latestJob.error_message) ||
    stringValue(item.latest_parsed_document?.error_message) ||
    firstString(item.parse_readiness.blocking_reasons) ||
    '解析失败，请查看失败任务。';

  return (
    <div className="px-4 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <FileText className="w-4 h-4 text-gray-400 shrink-0" />
            <p className="truncate text-sm font-medium text-gray-900">{item.file_name || '未命名附件'}</p>
            <AttachmentStatusBadge status={item.display_status} />
          </div>
          <p className="mt-1 text-xs text-gray-400">
            {item.file_type || item.mime_type || 'unknown'} · {formatBytes(item.file_size)} · 上传时间：
            {formatDateTime(item.uploaded_at)} · 上传人：{item.uploaded_by_name || '管理员'}
          </p>
          {item.link_type && <p className="mt-1 text-xs text-gray-400">来源：{attachmentLinkTypeLabel(item.link_type)}</p>}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onDownload}
            disabled={downloading}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium border border-gray-200 text-gray-600 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50"
          >
            {downloading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
            下载
          </button>
          <button
            onClick={onDelete}
            disabled={deleting}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium border border-gray-200 text-gray-500 hover:border-red-300 hover:text-red-600 disabled:opacity-50"
          >
            {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
            删除
          </button>
        </div>
      </div>

      {evidenceText && (
        <div className="mt-3 bg-gray-50 px-3 py-2.5">
          <p className="text-xs text-gray-400 mb-1">
            最新证据{evidencePage ? ` · 第 ${evidencePage} 页` : ''}
          </p>
          <p className="text-sm text-gray-700 line-clamp-3">{evidenceText}</p>
        </div>
      )}

      {failed && (
        <div className="mt-3 border border-red-100 bg-red-50 px-3 py-2.5">
          <p className="text-xs font-medium text-red-700">解析失败</p>
          <p className="mt-1 text-xs text-red-600 line-clamp-2">{failedMessage}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {stringValue(latestJobDebug.route) && (
              <Link to={stringValue(latestJobDebug.route)} className="inline-flex items-center gap-1 text-xs font-medium text-red-700 underline">
                <ExternalLink className="w-3 h-3" />
                查看失败任务
              </Link>
            )}
            {stringValue(relatedUpdate.review_route) && (
              <Link to={stringValue(relatedUpdate.review_route)} className="inline-flex items-center gap-1 text-xs font-medium text-red-700 underline">
                <ExternalLink className="w-3 h-3" />
                查看业务更新
              </Link>
            )}
            {item.debug_ref?.route && (
              <Link to={item.debug_ref.route} className="inline-flex items-center gap-1 text-xs font-medium text-red-700 underline">
                <ExternalLink className="w-3 h-3" />
                查看 Debug
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/*
function LegacyAttachmentsTab() {
  return (
    <div className="text-center py-10">
      <FileText className="w-8 h-8 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-400">附件解析功能后端开发中</p>
    </div>
  );
}

*/
function FollowUpsTab({
  targetId,
  followUps,
  onChanged,
  relationItems,
  relationEvents,
}: {
  targetId: string;
  followUps: TargetFollowUp[];
  onChanged: (next: TargetFollowUp[]) => void;
  relationItems: BuyerSellerRelation[];
  relationEvents: RelationEvent[];
}) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = () => sellerTargets.followUps(targetId).then(onChanged).catch(() => {});

  const handleDelete = async (followUp: TargetFollowUp) => {
    if (!window.confirm('确认删除这条跟进记录？')) return;
    setDeletingId(followUp.id);
    try {
      await sellerTargets.deleteFollowUp(targetId, followUp.id);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <section>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">跟进记录</h4>
        <p className="mb-3 text-xs text-gray-400">
          在「录入更新」里输入跟进动态（如：0730 推给广州工业投资控股集团，等待反馈），AI 解析后会自动按日期落到这里。
        </p>
        {followUps.length === 0 ? (
          <p className="text-sm text-gray-400">暂无跟进记录</p>
        ) : (
          <div className="space-y-2">
            {followUps.map((followUp) => (
              <div key={followUp.id} className="group flex items-start gap-3 border border-gray-100 px-3 py-2.5">
                <span className="text-xs text-gray-400 font-mono w-24 shrink-0 pt-0.5">{followUp.occurred_on}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{followUp.content}</p>
                  {followUp.related_buyer_parties.length > 0 && (
                    <p className="mt-1 flex flex-wrap gap-1">
                      {followUp.related_buyer_parties.map((buyer) => (
                        <Link
                          key={buyer.id}
                          to={`/buyers/${buyer.id}`}
                          className="inline-flex items-center gap-1 bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600 hover:bg-brand-50 hover:text-brand-700"
                        >
                          <UserRound className="w-2.5 h-2.5" />
                          {buyer.buyer_name}
                        </Link>
                      ))}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(followUp)}
                  disabled={deletingId === followUp.id}
                  className="shrink-0 p-1 text-gray-300 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-50"
                  title="删除跟进记录"
                >
                  {deletingId === followUp.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {relationItems.length === 0 && relationEvents.length === 0 ? (
        <p className="text-xs text-gray-400">推荐、接触、尽调等系统进展会自动沉淀在下方。</p>
      ) : (
        <RelationsTab relationItems={relationItems} relationEvents={relationEvents} />
      )}
    </div>
  );
}

function RelationsTab({
  relationItems,
  relationEvents,
}: {
  relationItems: BuyerSellerRelation[];
  relationEvents: RelationEvent[];
}) {
  if (relationItems.length === 0 && relationEvents.length === 0) {
    return (
      <div className="text-center py-10">
        <SearchIcon className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">暂无关系与跟进记录</p>
        <p className="text-xs text-gray-400 mt-1">推荐、接触、尽调和不感兴趣等进展会自动沉淀在这里</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {relationItems.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">当前关系</h4>
          <div className="space-y-2">
            {relationItems.map((relation) => (
              <div key={relation.id} className="border border-gray-100 px-3 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 flex items-center gap-1.5">
                      <UserRound className="w-3.5 h-3.5 text-gray-400" />
                      {relation.buyer_name || '未绑定买家'} / {relation.buyer_intent_name || '未命名意向'}
                    </p>
                    {relation.last_event_summary && (
                      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{relation.last_event_summary}</p>
                    )}
                  </div>
                  <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-700 shrink-0">
                    {relationStatusLabel(relation.status)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {relationEvents.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">跟进时间线</h4>
          <div className="space-y-2">
            {relationEvents.map((event) => (
              <div key={event.id} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
                <span className="text-xs text-gray-400 font-mono w-32 shrink-0">
                  {new Date(event.event_time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                </span>
                <div className="min-w-0">
                  <p className="text-sm text-gray-800">
                    {event.buyer_name || '未绑定买家'} / {event.buyer_intent_name || '未命名意向'}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {eventTypeLabel(event.event_type)}{event.title ? ` · ${event.title}` : ''}
                  </p>
                  {event.content && <p className="text-xs text-gray-600 mt-1">{event.content}</p>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function relationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    recommended: '已推荐',
    interested: '感兴趣',
    in_discussion: '沟通中',
    due_diligence: '尽调中',
    agreement: '协议阶段',
    deal_closed: '已成交',
    not_interested: '不感兴趣',
    paused: '暂停',
    lost: '失败',
  };
  return labels[status] || status;
}

function eventTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    recommended: '推荐',
    buyer_interested: '买家感兴趣',
    buyer_not_interested: '买家不感兴趣',
    meeting: '会议',
    call: '电话',
    material_sent: '发送资料',
    due_diligence_started: '启动尽调',
    agreement_discussion: '协议沟通',
    deal_closed: '成交',
    paused: '暂停',
    internal_note: '内部备注',
    other: '其他',
  };
  return labels[type] || type;
}

function HistoryTab({ logs }: { logs: UpdateLog[] }) {
  if (logs.length === 0) {
    return (
      <div className="text-center py-10">
        <Clock className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">暂无更新记录</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {logs.map((log) => (
        <div key={log.id} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
          <span className="text-xs text-gray-400 font-mono w-32 shrink-0">
            {new Date(log.applied_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
          </span>
          <div className="min-w-0">
            <span className="text-sm text-gray-700">
              {fieldLabel(log.entity_type, log.field_path)}: {valueLabel(log.field_path, log.old_value_json)} → {valueLabel(log.field_path, log.new_value_json)}
            </span>
            <span className="text-xs text-gray-400 ml-2">来源: {sourceTypeLabel(log.source_type)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function AttachmentStatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    parsed: '已解析',
    parsing: '解析中',
    failed: '解析失败',
    image_evidence: '图片证据',
    ready: '可解析',
    pending: '未解析',
  };
  const colors: Record<string, string> = {
    parsed: 'bg-emerald-50 text-emerald-700',
    parsing: 'bg-blue-50 text-blue-700',
    failed: 'bg-red-50 text-red-700',
    image_evidence: 'bg-purple-50 text-purple-700',
    ready: 'bg-amber-50 text-amber-700',
    pending: 'bg-gray-100 text-gray-600',
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 font-medium ${colors[status] || colors.pending}`}>
      {labels[status] || status}
    </span>
  );
}

function attachmentLinkTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    source_document: '直接上传',
    business_update_context: '业务更新',
  };
  return labels[value] || value;
}

function formatBytes(value: number | null | undefined): string {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return '-';
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function stringValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function firstString(value: unknown): string {
  if (!Array.isArray(value)) return '';
  const found = value.find((item) => typeof item === 'string' && item.trim());
  return found || '';
}

function StatusBadge({ status, type }: { status: string; type: 'recommendation' | 'information' }) {
  const colors = sellerTargetStatusClass(status, type);
  const label = sellerTargetStatusLabel(status, type);

  return <span className={`text-xs px-1.5 py-0.5 font-medium ${colors}`}>{label}</span>;
}

function DisplayStatusBadge({ target }: { target: SellerTarget }) {
  const displayStatus = sellerTargetDisplayStatus(target);
  return (
    <span className={`text-xs px-1.5 py-0.5 font-medium ${sellerTargetDisplayStatusClass(displayStatus)}`}>
      {sellerTargetDisplayStatusLabel(displayStatus)}
    </span>
  );
}

function formatYuan(val: string): string {
  const num = Number(val);
  if (!Number.isFinite(num)) return '-';
  const sign = num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${sign}${Math.round(abs / 10000)}万`;
  return String(num);
}

function formatListedStatus(status: string | null): string {
  if (status === 'listed') return '已上市';
  if (status === 'unlisted' || status === 'pre_ipo') return '未上市';
  return '未知';
}

function getSubjectDisplay(target: SellerTarget): string {
  const subject = target.target_subject_name?.trim();
  return subject || '-';
}

function formatTransferRatio(target: SellerTarget): string | null {
  if (target.transfer_ratio_min && target.transfer_ratio_max) {
    return `${formatRatio(target.transfer_ratio_min)}-${formatRatio(target.transfer_ratio_max)}`;
  }
  if (target.transfer_ratio_min) return `>=${formatRatio(target.transfer_ratio_min)}`;
  if (target.transfer_ratio_max) return `<=${formatRatio(target.transfer_ratio_max)}`;
  return null;
}

function formatRatio(value: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return `${Number(num.toFixed(1))}%`;
}
