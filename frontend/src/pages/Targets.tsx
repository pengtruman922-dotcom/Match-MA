import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent, ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  Building2,
  FileText,
  Image,
  Loader2,
  MessageSquarePlus,
  Paperclip,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { attachments, businessUpdates, sellerTargets } from '../lib/api';
import type { AttachmentUploadPolicy, SellerTarget, SellerTargetCreate } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';

export default function Targets() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<SellerTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [updateDrawer, setUpdateDrawer] = useState<{ open: boolean; targetId?: string; targetName?: string }>({ open: false });
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchTargets = useCallback((q?: string) => {
    setLoading(true);
    sellerTargets.list({ q: q || undefined, limit: 50 })
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchTargets();
  }, [fetchTargets]);

  useEffect(() => {
    if (searchParams.get('action') === 'new') {
      setShowCreateModal(true);
      const next = new URLSearchParams(searchParams);
      next.delete('action');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleSearch = () => {
    fetchTargets(searchQuery);
  };

  const handleDelete = async (item: SellerTarget) => {
    if (!window.confirm(`确认删除标的「${item.target_name}」？删除后不会出现在列表和推荐候选里。`)) return;
    setDeletingId(item.id);
    try {
      await sellerTargets.delete(item.id);
      fetchTargets(searchQuery);
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-5">
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

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && handleSearch()}
            placeholder="搜索标的名称、主体或摘要..."
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

      <div className="bg-white border border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-max min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="sticky left-0 z-20 w-[220px] bg-gray-50 text-left px-4 py-3 font-medium text-gray-600">标的名称</th>
                <th className="w-20 max-w-20 text-left px-3 py-3 font-medium text-gray-600">标的主体</th>
                <th className="w-[110px] text-center px-4 py-3 font-medium text-gray-600">推荐状态</th>
                <th className="w-[92px] text-left px-4 py-3 font-medium text-gray-600">类型</th>
                <th className="w-[96px] text-left px-4 py-3 font-medium text-gray-600">上市状态</th>
                <th className="w-[150px] text-left px-4 py-3 font-medium text-gray-600">行业</th>
                <th className="w-[130px] text-left px-4 py-3 font-medium text-gray-600">地区</th>
                <th className="w-[130px] text-right px-4 py-3 font-medium text-gray-600">价格</th>
                <th className="w-[110px] text-left px-4 py-3 font-medium text-gray-600">价格时间</th>
                <th className="w-[120px] text-right px-4 py-3 font-medium text-gray-600">净利润</th>
                <th className="w-[110px] text-left px-4 py-3 font-medium text-gray-600">财务期间</th>
                <th className="w-[92px] text-right px-4 py-3 font-medium text-gray-600">负债率</th>
                <th className="w-[120px] text-left px-4 py-3 font-medium text-gray-600">出售比例</th>
                <th className="w-[76px] text-center px-4 py-3 font-medium text-gray-600">控股</th>
                <th className="w-[76px] text-center px-4 py-3 font-medium text-gray-600">并表</th>
                <th className="w-[110px] text-center px-4 py-3 font-medium text-gray-600">信息状态</th>
                <th className="sticky right-0 z-20 w-[210px] bg-gray-50 text-left px-4 py-3 font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr>
                  <td colSpan={17} className="px-4 py-8 text-center">
                    <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto" />
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={17} className="px-4 py-8 text-center text-gray-400">暂无标的数据</td>
                </tr>
              ) : (
                items.map((item) => (
                  <TargetRow
                    key={item.id}
                    item={item}
                    onOpenUpdateDrawer={() => setUpdateDrawer({ open: true, targetId: item.id, targetName: item.target_name })}
                    onDelete={() => handleDelete(item)}
                    deleting={deletingId === item.id}
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
          onCreated={() => { setShowCreateModal(false); fetchTargets(searchQuery); }}
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
  onOpenUpdateDrawer,
  onDelete,
  deleting,
}: {
  item: SellerTarget;
  onOpenUpdateDrawer: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const subject = getSubjectDisplay(item);
  const industry = [item.industry_primary, item.industry_secondary].filter(Boolean).join(' / ') || '-';
  const region = [item.headquarter_province, item.headquarter_city].filter(Boolean).join(' ') || '-';
  const price = getPreferredPrice(item);
  const priceDisplay = price ? `${formatYuan(price.value)}${price.kind === 'asking' ? '*' : ''}` : '-';
  const priceTitle = price
    ? `${price.kind === 'asking' ? '报价' : '估值'}：${formatYuan(price.value)}${price.kind === 'asking' ? '（明确报价）' : ''}`
    : '';
  const ratioText = formatTransferRatio(item);

  return (
    <tr className="group hover:bg-brand-50/30 transition-colors">
      <td className="sticky left-0 z-10 bg-white px-4 py-3 group-hover:bg-brand-50">
        <ClampedLink to={`/targets/${item.id}`} value={item.target_name} className="font-medium text-gray-900 hover:text-brand-600 transition-colors" />
        {item.business_summary && <ClampedText value={item.business_summary} className="mt-1 text-xs text-gray-400" />}
      </td>
      <td className="w-20 max-w-20 px-3 py-3 text-gray-600"><ClampedText value={subject} /></td>
      <td className="px-4 py-3 text-center"><StatusBadge status={item.recommendation_status} type="recommendation" /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={formatTargetType(item.target_type)} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={formatListedStatus(item.listed_status)} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={industry} /></td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={region} /></td>
      <td className="px-4 py-3 text-right text-gray-700 font-mono" title={priceTitle}>{priceDisplay}</td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={price?.date || '-'} /></td>
      <td className="px-4 py-3 text-right text-gray-600 font-mono">
        {item.current_net_profit_yuan ? formatYuan(item.current_net_profit_yuan) : '-'}
      </td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={item.financial_period_label || '-'} /></td>
      <td className="px-4 py-3 text-right text-gray-600 font-mono">{formatPercent(item.current_debt_ratio)}</td>
      <td className="px-4 py-3 text-gray-600"><ClampedText value={ratioText} /></td>
      <td className="px-4 py-3 text-center"><YesNoBadge value={item.can_control} /></td>
      <td className="px-4 py-3 text-center"><YesNoBadge value={item.can_consolidate} /></td>
      <td className="px-4 py-3 text-center"><StatusBadge status={item.information_status} type="information" /></td>
      <td className="sticky right-0 z-10 bg-white px-4 py-3 group-hover:bg-brand-50">
        <div className="flex items-center gap-1 whitespace-nowrap">
          <button
            onClick={onOpenUpdateDrawer}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-white transition-colors"
          >
            <MessageSquarePlus className="w-3 h-3" />
            更新
          </button>
          <Link
            to={`/recommendations?mode=target-to-buyer&targetId=${item.id}`}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-600 hover:bg-white transition-colors"
          >
            <Sparkles className="w-3 h-3" />
            推荐买家
          </Link>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
          >
            {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
            删除
          </button>
        </div>
      </td>
    </tr>
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

function YesNoBadge({ value }: { value: string | null }) {
  const normalized = value || 'unknown';
  const labelMap: Record<string, string> = {
    yes: '是',
    likely: '可能',
    no: '否',
    unknown: '未知',
  };
  const colorMap: Record<string, string> = {
    yes: 'bg-emerald-50 text-emerald-700',
    likely: 'bg-blue-50 text-blue-700',
    no: 'bg-gray-100 text-gray-600',
    unknown: 'bg-gray-100 text-gray-500',
  };
  return <span className={`text-xs px-2 py-0.5 font-medium ${colorMap[normalized] || colorMap.unknown}`}>{labelMap[normalized] || normalized}</span>;
}

function ClampedText({ value, className = '' }: { value: string; className?: string }) {
  return <span title={value === '-' ? undefined : value} className={`line-clamp-2 break-words ${className}`}>{value}</span>;
}

function ClampedLink({ to, value, className = '' }: { to: string; value: string; className?: string }) {
  return (
    <Link to={to} title={value} className={`line-clamp-2 break-words ${className}`}>
      {value}
    </Link>
  );
}

function formatYuan(val: string | number): string {
  const num = Number(val);
  if (!Number.isFinite(num)) return '-';
  const sign = num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${sign}${Math.round(abs / 10000)}万`;
  if (Number.isInteger(num)) return String(num);
  return String(Number(num.toFixed(2)));
}

function formatPercent(val: string | null): string {
  if (!val) return '-';
  const raw = Number(val);
  if (!Number.isFinite(raw)) return '-';
  const percentage = raw > 0 && raw <= 1 ? raw * 100 : raw;
  return `${Number(percentage.toFixed(1))}%`;
}

function formatTargetType(type: string | null): string {
  const map: Record<string, string> = {
    company: '公司',
    equity_package: '股权包',
    business_unit: '业务单元',
    asset_package: '资产包',
    project: '项目',
    other: '其他',
  };
  return type ? map[type] || type : '-';
}

function formatListedStatus(status: string | null): string {
  if (status === 'listed') return '已上市';
  if (status === 'unlisted' || status === 'pre_ipo') return '未上市';
  return '未知';
}

function getSubjectDisplay(item: SellerTarget): string {
  const subject = item.target_subject_name?.trim();
  if (item.target_type === 'company' && (!subject || subject === item.target_name)) return '同标的';
  return subject || '-';
}

function getPreferredPrice(item: SellerTarget): { kind: 'asking' | 'valuation'; value: string; date: string | null } | null {
  if (item.asking_price_yuan) return { kind: 'asking', value: item.asking_price_yuan, date: item.asking_price_date };
  if (item.valuation_yuan) return { kind: 'valuation', value: item.valuation_yuan, date: item.valuation_date };
  return null;
}

function formatTransferRatio(item: SellerTarget): string {
  if (item.transfer_ratio_text) return item.transfer_ratio_text;
  if (item.transfer_ratio_min && item.transfer_ratio_max) return `${formatRatio(item.transfer_ratio_min)}-${formatRatio(item.transfer_ratio_max)}`;
  if (item.transfer_ratio_min) return `>=${formatRatio(item.transfer_ratio_min)}`;
  if (item.transfer_ratio_max) return `<=${formatRatio(item.transfer_ratio_max)}`;
  return '-';
}

function formatRatio(value: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return `${Number(num.toFixed(1))}%`;
}

type CreateTargetForm = {
  targetName: string;
  targetType: string;
  targetSubjectName: string;
  industry: string;
  region: string;
  askingPrice: string;
  askingPriceDate: string;
  supplement: string;
};

const DEFAULT_CREATE_FORM: CreateTargetForm = {
  targetName: '',
  targetType: 'company',
  targetSubjectName: '',
  industry: '',
  region: '',
  askingPrice: '',
  askingPriceDate: '',
  supplement: '',
};

function CreateTargetModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [form, setForm] = useState<CreateTargetForm>(DEFAULT_CREATE_FORM);
  const [saving, setSaving] = useState(false);
  const [duplicates, setDuplicates] = useState<SellerTarget[]>([]);
  const [nameWarning, setNameWarning] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPolicyLoading(true);
    attachments
      .uploadPolicy()
      .then((policy) => {
        if (!cancelled) setUploadPolicy(policy);
      })
      .catch((err) => {
        if (!cancelled) setPolicyError(err instanceof Error ? err.message : '读取上传规则失败');
      })
      .finally(() => {
        if (!cancelled) setPolicyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const name = form.targetName.trim();
    if (name.length < 2) {
      setDuplicates([]);
      setNameWarning(name.length === 1 ? '名称过短，建议补充公司全称或地区' : '');
      return;
    }

    const timer = window.setTimeout(() => {
      setNameWarning('');
      sellerTargets
        .list({ q: name, limit: 5 })
        .then((results) => setDuplicates(results.filter((item) => item.target_name !== name)))
        .catch(() => {});
    }, 300);

    return () => window.clearTimeout(timer);
  }, [form.targetName]);

  function updateForm<K extends keyof CreateTargetForm>(key: K, value: CreateTargetForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleFileSelect(event: ChangeEvent<HTMLInputElement>) {
    const incoming = Array.from(event.target.files || []);
    event.target.value = '';
    if (!incoming.length) return;

    const nextFiles = [...selectedFiles];
    const errors: string[] = [];
    const maxFiles = uploadPolicy?.max_files_per_business_update || 10;
    const maxBytes = uploadPolicy?.max_upload_bytes || 25 * 1024 * 1024;

    for (const file of incoming) {
      if (nextFiles.length >= maxFiles) {
        errors.push(`单次业务更新最多上传 ${maxFiles} 个附件。`);
        break;
      }
      if (file.size > maxBytes) {
        errors.push(`${file.name} 超过 ${formatBytes(maxBytes)}。`);
        continue;
      }
      if (nextFiles.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) {
        continue;
      }
      nextFiles.push(file);
    }

    setSelectedFiles(nextFiles);
    setFileError(errors[0] || null);
  }

  function removeFile(index: number) {
    setSelectedFiles((files) => files.filter((_, itemIndex) => itemIndex !== index));
    setFileError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetName = form.targetName.trim();
    if (!targetName) return;

    const askingPriceYuan = parseMoneyToYuan(form.askingPrice);
    if (form.askingPrice.trim() && askingPriceYuan === undefined) {
      setSubmitError('报价格式暂无法识别，请使用 5000万、1.2亿 或完整数字。');
      return;
    }

    setSaving(true);
    setSubmitError(null);
    try {
      const region = parseRegion(form.region);
      const payload: SellerTargetCreate = {
        target_name: targetName,
        target_type: form.targetType,
        target_subject_name: normalizeOptional(form.targetSubjectName),
        industry_primary: normalizeOptional(form.industry),
        headquarter_province: region.province,
        headquarter_city: region.city,
        asking_price_yuan: askingPriceYuan,
        asking_price_date: normalizeOptional(form.askingPriceDate),
        business_summary: normalizeOptional(form.supplement),
      };

      const created = await sellerTargets.create(payload);
      const shouldParse = selectedFiles.length > 0 || form.supplement.trim().length > 0;
      if (shouldParse) {
        const rawText = buildCreateTargetRawText(form, payload);
        if (selectedFiles.length > 0) {
          const formData = new FormData();
          formData.set('raw_text', rawText);
          formData.set('input_type', 'mixed');
          formData.set('auto_process', 'true');
          formData.set('process_after_ocr', 'true');
          formData.set('include_attachment_text', 'true');
          formData.set('bound_seller_target_ids', JSON.stringify([created.id]));
          formData.set(
            'metadata_json',
            JSON.stringify({
              source: 'frontend_target_create_modal',
              create_payload: payload,
              bound_seller_target_ids: [created.id],
            })
          );
          selectedFiles.forEach((file) => formData.append('files', file));
          await businessUpdates.upload(formData);
        } else {
          const update = await businessUpdates.create({
            raw_text: rawText,
            input_type: 'text',
            bound_seller_target_ids: [created.id],
            metadata_json: {
              source: 'frontend_target_create_modal',
              create_payload: payload,
            },
          });
          await businessUpdates.process(update.id);
        }
      }
      onCreated();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="新建标的" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
          <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
          <p className="leading-relaxed">
            可以先填简要信息，再粘贴大段材料或上传附件。若正式文件识别到更完整的标的名称、主体名称或行业分类，解析结果会优先采用正式材料。
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="标的名称" required>
            <input
              type="text"
              value={form.targetName}
              onChange={(event) => updateForm('targetName', event.target.value)}
              className="input"
              placeholder="例如：拼哒出行项目"
              autoFocus
            />
            {nameWarning && <p className="text-xs text-amber-600 mt-1">{nameWarning}</p>}
          </Field>
          <Field label="类型">
            <select value={form.targetType} onChange={(event) => updateForm('targetType', event.target.value)} className="input">
              <option value="company">公司</option>
              <option value="project">项目</option>
              <option value="asset_package">资产包</option>
              <option value="business_unit">业务单元</option>
              <option value="equity_package">股权包</option>
              <option value="other">其他</option>
            </select>
          </Field>
          <Field label="标的主体">
            <input
              type="text"
              value={form.targetSubjectName}
              onChange={(event) => updateForm('targetSubjectName', event.target.value)}
              className="input"
              placeholder="公司整体可留空，系统显示为同标的"
            />
          </Field>
          <Field label="行业">
            <input
              type="text"
              value={form.industry}
              onChange={(event) => updateForm('industry', event.target.value)}
              className="input"
              placeholder="可选，留空由系统解析"
            />
          </Field>
          <Field label="地区">
            <input
              type="text"
              value={form.region}
              onChange={(event) => updateForm('region', event.target.value)}
              className="input"
              placeholder="例如：浙江 杭州；可留空"
            />
          </Field>
          <Field label="报价">
            <input
              type="text"
              value={form.askingPrice}
              onChange={(event) => updateForm('askingPrice', event.target.value)}
              className="input"
              placeholder="例如：10亿、5000万"
            />
          </Field>
          <Field label="报价时间">
            <input
              type="text"
              value={form.askingPriceDate}
              onChange={(event) => updateForm('askingPriceDate', event.target.value)}
              className="input"
              placeholder="例如：2025年一季度、2026-06"
            />
          </Field>
        </div>

        <Field label="补充内容">
          <textarea
            value={form.supplement}
            onChange={(event) => updateForm('supplement', event.target.value)}
            className="input min-h-[150px] resize-y leading-relaxed"
            placeholder="可粘贴聊天记录、项目介绍、财务摘要或其他大段文本。"
          />
        </Field>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">附件/截图</label>
          <div className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-600">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 text-gray-800 font-medium">
                <Upload className="w-4 h-4 text-brand-600" />
                上传图片、PDF、Office 或文本附件
              </div>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="shrink-0 bg-white border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-brand-300 hover:text-brand-700"
              >
                选择文件
              </button>
            </div>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} />
            <UploadPolicyCard policy={uploadPolicy} loading={policyLoading} error={policyError} />
            <SelectedFiles files={selectedFiles} onRemove={removeFile} />
            {fileError && <InlineWarning message={fileError} />}
          </div>
        </div>

        {duplicates.length > 0 && (
          <div className="border border-amber-200 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-800">疑似重复</p>
            {duplicates.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-3 text-xs">
                <span className="text-gray-700 line-clamp-2">
                  {item.target_name} · {item.headquarter_province || '未知'} · {item.industry_primary || '未知'}
                </span>
                <Link to={`/targets/${item.id}`} className="text-brand-600 hover:text-brand-700 font-medium shrink-0" onClick={onClose}>
                  更新它
                </Link>
              </div>
            ))}
          </div>
        )}

        {submitError && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>}

        <div className="flex items-center justify-between gap-3 pt-2">
          <p className="text-xs text-gray-400">
            {selectedFiles.length > 0 || form.supplement.trim()
              ? '创建后会自动进入解析队列，解析结果可在更新记录复核。'
              : '仅创建基础标的，不触发解析。'}
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700 hover:border-gray-300 transition-colors">
              取消
            </button>
            <button type="submit" disabled={saving || !form.targetName.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-50 inline-flex items-center gap-2">
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {saving ? '创建中...' : duplicates.length > 0 ? '仍然新建' : selectedFiles.length > 0 || form.supplement.trim() ? '创建并解析' : '创建'}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function UploadPolicyCard({
  policy,
  loading,
  error,
}: {
  policy: AttachmentUploadPolicy | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        正在读取上传规则...
      </div>
    );
  }

  if (error) return <InlineWarning message={error} />;
  if (!policy) return <p className="mt-3 text-xs text-gray-400">上传规则暂不可用。</p>;

  const image = policy.image_policy.constraints;
  const pdf = policy.pdf_policy.text_detection;
  const doc2xStatus = policy.pdf_policy.scanned_pdf.doc2x_configured ? '已配置' : '未配置';

  return (
    <div className="mt-3 space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <PolicyStat label="单文件上限" value={`${policy.max_upload_mb} MB`} />
        <PolicyStat label="附件数量" value={`${policy.max_files_per_business_update} 个/次`} />
        <PolicyStat label="图片数量" value={`${image.max_count_per_business_update} 张/次`} />
      </div>
      <div className="grid grid-cols-1 gap-2 text-xs">
        <PolicyLine
          icon={Image}
          title="截图 / 图片"
          body={`支持 ${image.supported_types.join('、')}；不走 OCR，直接交给多模态模型；会压缩到最长边 ${image.model_preprocess_max_side_px}px。`}
        />
        <PolicyLine
          icon={FileText}
          title="PDF"
          body={`前 ${pdf.sample_page_limit} 页累计文本不少于 ${pdf.min_total_chars_for_text_pdf} 字按文本 PDF 本地解析；扫描件走 Doc2X 异步 OCR（${doc2xStatus}）。`}
        />
      </div>
    </div>
  );
}

function SelectedFiles({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  if (!files.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {files.map((file, index) => (
        <div key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center justify-between gap-3 bg-white border border-gray-200 px-3 py-2">
          <div className="min-w-0 flex items-center gap-2">
            <Paperclip className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-gray-800">{file.name}</p>
              <p className="text-[11px] text-gray-400">{formatBytes(file.size)}</p>
            </div>
          </div>
          <button type="button" onClick={() => onRemove(index)} className="shrink-0 text-xs text-gray-400 hover:text-red-600">
            移除
          </button>
        </div>
      ))}
    </div>
  );
}

function InlineWarning({ message }: { message: string }) {
  return (
    <div className="mt-3 flex items-start gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function PolicyStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border border-gray-200 px-3 py-2">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function PolicyLine({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) {
  return (
    <div className="flex gap-2 bg-white border border-gray-200 px-3 py-2">
      <Icon className="w-3.5 h-3.5 text-brand-600 mt-0.5 shrink-0" />
      <div>
        <p className="font-medium text-gray-800">{title}</p>
        <p className="mt-0.5 text-gray-500 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white border border-gray-200 shadow-lg w-full max-w-3xl mx-4 max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white z-10">
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

function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label} {required && <span className="text-brand-600">*</span>}
      </label>
      {children}
    </div>
  );
}

function parseMoneyToYuan(value: string): number | undefined {
  const text = value.trim();
  if (!text) return undefined;
  const normalized = text.replace(/[,，\s]/g, '').replace(/人民币|CNY|RMB/gi, '');
  const match = normalized.match(/^(\d+(?:\.\d+)?)(亿元|亿|万元|万|元)?$/);
  if (!match) return undefined;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return undefined;
  const unit = match[2] || '元';
  if (unit === '亿元' || unit === '亿') return amount * 100000000;
  if (unit === '万元' || unit === '万') return amount * 10000;
  return amount;
}

function parseRegion(value: string): { province?: string; city?: string } {
  const text = value.trim();
  if (!text) return {};
  const parts = text.split(/[\s,，/／-]+/).filter(Boolean);
  if (parts.length >= 2) return { province: parts[0], city: parts.slice(1).join(' ') };
  return { province: text };
}

function normalizeOptional(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed || undefined;
}

function buildCreateTargetRawText(form: CreateTargetForm, payload: SellerTargetCreate): string {
  const lines = [
    '【新建标的初始输入】',
    `标的名称：${payload.target_name}`,
    `类型：${formatTargetType(payload.target_type || 'company')}`,
    form.targetSubjectName.trim() ? `标的主体：${form.targetSubjectName.trim()}` : null,
    form.industry.trim() ? `行业：${form.industry.trim()}` : null,
    form.region.trim() ? `地区：${form.region.trim()}` : null,
    form.askingPrice.trim() ? `报价：${form.askingPrice.trim()}` : null,
    form.askingPriceDate.trim() ? `报价时间：${form.askingPriceDate.trim()}` : null,
    '',
    '解析要求：如果附件或正式文件识别到更完整的标的名称、主体名称、一级/二级行业、行业标签或地区，请以正式材料为准，可以覆盖上述初始输入；行业和地区字段请输出中文。不要臆造材料中没有的信息。',
  ].filter((line): line is string => line !== null);

  if (form.supplement.trim()) {
    lines.push('', '【补充内容】', form.supplement.trim());
  }

  return lines.join('\n');
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}
