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
  const [checkingDedup, setCheckingDedup] = useState(false);
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

  const createBuyerIntent = async (buyerPartyId: string | null, buyerName: string) => {
    setSaving(true);
    setSubmitError(null);
    try {
      const materialText = form.raw_requirement_text.trim();
      const shouldParse = selectedFiles.length > 0 || materialText.length > 0;
      const rawText = buildBuyerIntakeRawText(buyerName, materialText);
      const resolvedBuyerPartyId = buyerPartyId || (await buyerParties.create({ buyer_name: buyerName })).id;
      const createdIntent = await buyerIntents.create({
        buyer_party_id: resolvedBuyerPartyId,
        intent_name: defaultBuyerIntentName(buyerName),
        raw_requirement_text: shouldParse ? rawText : undefined,
      });

      if (shouldParse) {
        if (selectedFiles.length > 0) {
          const formData = new FormData();
          formData.set('raw_text', rawText);
          formData.set('input_type', 'mixed');
          // 新建买家需求只走 buyer_intent_parse（语义解析 + 规范化）。
          // business_update 在这里仅承载附件/OCR，不能再触发通用业务更新抽取，
          // 否则同一份材料会被两条链分别写一次。
          formData.set('auto_process', 'false');
          formData.set('process_after_ocr', 'false');
          formData.set('include_attachment_text', 'true');
          formData.set('auto_parse_linked_objects', 'true');
          formData.set('parse_entity_types', JSON.stringify(['buyer_intent']));
          formData.set('bound_buyer_intent_ids', JSON.stringify([createdIntent.id]));
          formData.set(
            'metadata_json',
            JSON.stringify({
              source: 'frontend_buyer_create_modal',
              buyer_party_id: resolvedBuyerPartyId,
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const buyerName = form.buyer_name.trim();
    if (!buyerName || saving || checkingDedup) return;

    setCheckingDedup(true);
    setSubmitError(null);
    try {
      const response = await buyerParties.dedupCheck({ q: buyerName });
      if (response.matches.length > 0) {
        setDedupCheck(response);
        return;
      }
      await createBuyerIntent(null, buyerName);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '买家查重失败，请稍后重试');
    } finally {
      setCheckingDedup(false);
    }
  };

  const closeDedupConfirmation = () => {
    if (saving) return;
    setDedupCheck(null);
    setSubmitError(null);
  };

  return (
    <>
      <Modal title="新建买家需求" onClose={onClose}>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
            <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
            <p className="leading-relaxed">
              一次录入一个买家的一项并购需求。需求创建后独立推荐和推进；同一买家的基础信息可以复用。
            </p>
          </div>

          <Field label="买家名称 *">
            <input
              type="text"
              value={form.buyer_name}
              onChange={(e) => {
                updateForm('buyer_name', e.target.value);
                setDedupCheck(null);
              }}
              placeholder="例如：北控集团、杭州某上市公司"
              className="input w-full"
              autoFocus
            />
          </Field>

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
            <button type="submit" disabled={saving || checkingDedup || !form.buyer_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-2">
              {(saving || checkingDedup) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {checkingDedup ? '查重中...' : saving ? '创建中...' : selectedFiles.length > 0 || form.raw_requirement_text.trim() ? '创建需求并解析' : '创建需求'}
            </button>
          </div>
        </div>
        </form>
      </Modal>

      {dedupCheck && dedupCheck.matches.length > 0 && (
        <Modal title="发现疑似重复买家" onClose={closeDedupConfirmation} wide>
          <div className="space-y-4">
            <div className="border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              系统在全库中发现以下疑似重复买家。你可以复用已有买家创建本次需求，也可以继续新建买家。
            </div>
            <div className="space-y-2">
              {dedupCheck.matches.map((match) => (
                <div key={match.id} className="flex items-center justify-between gap-4 border border-gray-200 bg-white px-4 py-3">
                  <div className="min-w-0 text-sm text-gray-800">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="font-medium">{match.buyer_name}</span>
                      {match.legal_name && <span className="text-xs text-gray-500">法律主体：{match.legal_name}</span>}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-500">
                      <span>负责人：{match.owner_name || '未指派'}</span>
                      <span>匹配：{dedupMatchLabel(match.match_type)}</span>
                      <span>状态：{buyerPartyStatusLabel(match.status)}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void createBuyerIntent(match.id, match.buyer_name)}
                    disabled={saving}
                    className="shrink-0 border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:border-brand-400 hover:bg-brand-100 disabled:opacity-50"
                  >
                    使用并创建
                  </button>
                </div>
              ))}
            </div>

            {submitError && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>}

            <div className="flex justify-end gap-2 border-t border-gray-100 pt-4">
              <button type="button" onClick={closeDedupConfirmation} disabled={saving} className="px-4 py-2 text-sm border border-gray-200 text-gray-700 disabled:opacity-50">取消</button>
              <button
                type="button"
                onClick={() => void createBuyerIntent(null, form.buyer_name.trim())}
                disabled={saving}
                className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-2"
              >
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {saving ? '创建中...' : '新建买家并创建'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

function buyerPartyStatusLabel(status: string): string {
  if (status === 'active') return '活跃';
  if (status === 'archived') return '已归档';
  if (status === 'merged') return '已合并';
  return status;
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
