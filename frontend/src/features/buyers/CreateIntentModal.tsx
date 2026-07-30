import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { Building2, Loader2, Upload } from 'lucide-react';
import { attachments, businessUpdates, buyerParties, buyerIntents } from '../../lib/api';
import type { AttachmentUploadPolicy, BuyerPartyDedupCheck } from '../../types/api';
import Modal, { Field } from '../../components/Modal';
import { InlineWarning, SelectedFiles, UploadPolicyCard } from '../../components/UploadArea';
import { formatBytes } from '../../lib/format';
import { withTimeout } from '../../lib/utils';
import { UPLOAD_POLICY_TIMEOUT_MS } from './filters';
import { dedupMatchLabel } from './presentation';

type BuyerIntakeForm = {
  buyer_name: string;
  raw_requirement_text: string;
};

const DEFAULT_BUYER_INTAKE_FORM: BuyerIntakeForm = {
  buyer_name: '',
  raw_requirement_text: '',
};

export default function CreateIntentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [dedupCheck, setDedupCheck] = useState<BuyerPartyDedupCheck | null>(null);
  const [dedupChecked, setDedupChecked] = useState(false);
  const [checkingDedup, setCheckingDedup] = useState(false);
  const [selectedBuyerPartyId, setSelectedBuyerPartyId] = useState<string | null>(null);
  const [selectedBuyerName, setSelectedBuyerName] = useState<string | null>(null);
  const [form, setForm] = useState<BuyerIntakeForm>(DEFAULT_BUYER_INTAKE_FORM);
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (uploadPolicy) return;
    let cancelled = false;
    setPolicyError(null);
    setPolicyLoading(true);
    withTimeout(
      attachments.uploadPolicy(),
      UPLOAD_POLICY_TIMEOUT_MS,
      '读取上传规则超时，可先按默认规则继续选择附件'
    )
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
  }, [uploadPolicy]);

  function updateForm<K extends keyof BuyerIntakeForm>(key: K, value: BuyerIntakeForm[K]) {
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
        errors.push(`单次最多上传 ${maxFiles} 个附件。`);
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

  const handleDedupCheck = async () => {
    const buyerName = form.buyer_name.trim();
    if (!buyerName) return;
    setCheckingDedup(true);
    try {
      const response = await buyerParties.dedupCheck({ q: buyerName, limit: 5 });
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
    const buyerName = form.buyer_name.trim();
    if (!buyerName) return;

    setSaving(true);
    setSubmitError(null);
    try {
      const materialText = form.raw_requirement_text.trim();
      const shouldParse = selectedFiles.length > 0 || materialText.length > 0;
      const rawText = buildBuyerIntakeRawText(buyerName, materialText);
      const buyerPartyId = selectedBuyerPartyId
        || (await buyerParties.create({ buyer_name: buyerName })).id;
      const createdIntent = await buyerIntents.create({
        buyer_party_id: buyerPartyId,
        intent_name: defaultBuyerIntentName(buyerName),
        raw_requirement_text: shouldParse ? rawText : undefined,
      });

      if (shouldParse) {
        if (selectedFiles.length > 0) {
          const formData = new FormData();
          formData.set('raw_text', rawText);
          formData.set('input_type', 'mixed');
          formData.set('auto_process', 'true');
          formData.set('process_after_ocr', 'true');
          formData.set('include_attachment_text', 'true');
          formData.set('auto_parse_linked_objects', 'true');
          formData.set('parse_entity_types', JSON.stringify(['buyer_intent']));
          formData.set('bound_buyer_intent_ids', JSON.stringify([createdIntent.id]));
          formData.set(
            'metadata_json',
            JSON.stringify({
              source: 'frontend_buyer_create_modal',
              buyer_party_id: buyerPartyId,
              buyer_intent_id: createdIntent.id,
              buyer_name: buyerName,
            })
          );
          selectedFiles.forEach((file) => formData.append('files', file));
          await businessUpdates.upload(formData);
        } else {
          await buyerIntents.parse(createdIntent.id, { raw_requirement_text: rawText });
        }
      }
      onCreated();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  };

  const selectExistingBuyer = async (buyerName: string) => {
    setSubmitError(null);
    try {
      const suggestions = await buyerParties.suggestions({ q: buyerName, limit: 10 });
      const exact = suggestions.find((item) => item.buyer_name.trim().toLowerCase() === buyerName.trim().toLowerCase());
      if (!exact) throw new Error('当前账号无法选用这条买家记录');
      setSelectedBuyerPartyId(exact.id);
      setSelectedBuyerName(exact.buyer_name);
      updateForm('buyer_name', exact.buyer_name);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '选用已有买家失败');
    }
  };

  return (
    <Modal title="新建买家需求" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
          <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
          <p className="leading-relaxed">
            一次录入一个买家的一项并购需求。需求创建后独立推荐和推进；同一买家的基础信息可以复用。
          </p>
        </div>

        <Field label="买家名称 *">
          <div className="flex gap-2">
            <input
              type="text"
              value={form.buyer_name}
              onChange={(e) => {
                updateForm('buyer_name', e.target.value);
                setDedupChecked(false);
                setDedupCheck(null);
                setSelectedBuyerPartyId(null);
                setSelectedBuyerName(null);
              }}
              placeholder="例如：北控集团、杭州某上市公司"
              className="input flex-1"
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
            <p className="text-xs font-medium text-amber-700">发现相似买家，请确认是否重复录入：</p>
            {dedupCheck!.matches.map((match) => (
              <div key={`${match.buyer_name}-${match.match_type}`} className={`flex items-center justify-between gap-3 border px-3 py-2 text-sm ${selectedBuyerName === match.buyer_name ? 'border-brand-300 bg-white' : 'border-amber-100 bg-amber-50/50'}`}>
                <div className="text-gray-800">
                  <span className="font-medium">{match.buyer_name}</span>
                  {match.legal_name && <span className="text-xs text-gray-500"> · {match.legal_name}</span>}
                  <span className="ml-2 text-xs text-amber-700">负责人：{match.owner_name || '未指派'}</span>
                  <span className="ml-2 text-xs text-gray-500">匹配：{dedupMatchLabel(match.match_type)}</span>
                </div>
                <button type="button" onClick={() => void selectExistingBuyer(match.buyer_name)} className="shrink-0 border border-amber-300 bg-white px-2.5 py-1 text-xs text-amber-800">
                  {selectedBuyerName === match.buyer_name ? '已选用' : '使用该买家'}
                </button>
              </div>
            ))}
            <p className="text-xs text-amber-700">同一买家的不同需求可分别创建，并共享这条买家基础信息。</p>
          </div>
        )}
        {dedupChecked && !dedupCheck?.matches.length && (
          <p className="text-xs text-emerald-600">未发现同名买家。</p>
        )}

        <Field label="需求材料">
          <textarea
            value={form.raw_requirement_text}
            onChange={(e) => updateForm('raw_requirement_text', e.target.value)}
            className="input min-h-[170px] resize-y leading-relaxed"
            placeholder={'可粘贴买家的聊天记录、邮件、投资偏好或访谈纪要。\n建议包含：关注行业、地区范围、上市/非上市偏好、市值或估值、利润/PE/负债率、股权比例、交易方式、排除项。\n示例：关注长三角医药健康资产，净利润2000万以上，优先控股并表，不接受重大诉讼或执行风险。'}
          />
        </Field>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">附件/截图</label>
          <div
            className="border border-dashed border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-600 transition-colors hover:border-brand-300 hover:bg-brand-50/40"
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleFileDrop}
          >
            <div className="flex gap-2">
              <div className="flex items-center gap-2 text-gray-800 font-medium">
                <Upload className="w-4 h-4 text-brand-600" />
                拖拽文件到这里，或上传图片、PDF、Office、文本附件
              </div>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="ml-auto shrink-0 bg-white border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-brand-300 hover:text-brand-700"
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

        {submitError && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>}

        <div className="flex items-center justify-between gap-3 pt-2">
          <p className="text-xs text-gray-400">
            {selectedFiles.length > 0 || form.raw_requirement_text.trim()
              ? '创建后会自动进入解析队列，解析结果可在需求详情查看。'
              : '仅创建基础需求，不触发解析。'}
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
            <button type="submit" disabled={saving || !form.buyer_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-2">
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {saving ? '创建中...' : selectedFiles.length > 0 || form.raw_requirement_text.trim() ? '创建需求并解析' : '创建需求'}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function defaultBuyerIntentName(buyerName: string): string {
  const yearMonth = new Date().toISOString().slice(0, 7);
  return `${buyerName}-并购需求（${yearMonth}）`;
}

function buildBuyerIntakeRawText(buyerName: string, materialText: string): string {
  const lines = [
    '【新建买家及并购需求初始输入】',
    `买家名称：${buyerName}`,
    '',
    '解析要求：只提取买家意向字段（行业、地区、利润、市值/估值、PE、溢价、负债率、上市偏好、股权比例、交易方式、风险容忍和排除项）。不要生成或修改买家主体资料。行业和地区请输出中文，不要臆造材料中没有的信息。',
  ];

  if (materialText) {
    lines.push('', '【需求原文/补充材料】', materialText);
  }

  return lines.join('\n');
}
