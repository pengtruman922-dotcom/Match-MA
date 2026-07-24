import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent, FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Loader2, Upload } from 'lucide-react';
import { attachments, businessUpdates, sellerTargets } from '../../lib/api';
import type { AttachmentUploadPolicy, SellerTarget, SellerTargetCreate } from '../../types/api';
import Modal, { Field } from '../../components/Modal';
import { InlineWarning, SelectedFiles, UploadPolicyCard } from '../../components/UploadArea';
import { formatBytes } from '../../lib/format';
import { formatTargetType } from './presentation';

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

export default function CreateTargetModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
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
        .then((response) => setDuplicates(response.items.filter((item) => item.target_name !== name)))
        .catch(() => {});
    }, 300);

    return () => window.clearTimeout(timer);
  }, [form.targetName]);

  function updateForm<K extends keyof CreateTargetForm>(key: K, value: CreateTargetForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function addFiles(incoming: File[]) {
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

  function handleFileSelect(event: ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files || []));
    event.target.value = '';
  }

  function handleFileDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    addFiles(Array.from(event.dataTransfer.files || []));
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
      const shouldParse = selectedFiles.length > 0 || form.supplement.trim().length > 0;
      const payload: SellerTargetCreate = {
        target_name: targetName,
        target_type: form.targetType,
        target_subject_name: normalizeOptional(form.targetSubjectName),
        recommendation_status: 'not_recommendable',
        information_status: shouldParse ? 'parsing' : 'normal',
        industry_l1: normalizeOptional(form.industry),
        industry_pairs_json: normalizeOptional(form.industry) ? [{ l1: normalizeOptional(form.industry)! }] : [],
        location_province: region.province,
        location_city: region.city,
        asking_price_yuan: askingPriceYuan,
        asking_price_date: normalizeOptional(form.askingPriceDate),
      };

      const created = await sellerTargets.create(payload);
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
    <Modal title="新建标的" onClose={onClose} wide>
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
              placeholder="可留空；解析后如与标的相同会直接显示同名主体"
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
          <div
            className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-600 transition-colors hover:border-brand-300 hover:bg-brand-50/40"
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleFileDrop}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 text-gray-800 font-medium">
                <Upload className="w-4 h-4 text-brand-600" />
                拖拽文件到这里，或上传图片、PDF、Office、文本附件
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
                  {item.target_name} · {item.location_province || '未知'} · {item.industry_l1 || '未知'}
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
    '解析要求：如果附件或正式文件识别到更完整的标的名称、主体名称、一级/二级行业、行业标签或地区，请以正式材料为准，可以覆盖上述初始输入；行业和地区字段请输出中文。不要臆造材料中没有的信息。业务摘要（business_summary）请用一两句话概括标的主营业务与核心亮点，不要照抄或粘贴原文。',
  ].filter((line): line is string => line !== null);

  if (form.supplement.trim()) {
    lines.push('', '【补充内容】', form.supplement.trim());
  }

  return lines.join('\n');
}
