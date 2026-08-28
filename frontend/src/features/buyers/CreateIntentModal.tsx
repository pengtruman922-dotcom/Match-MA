import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { AlertTriangle, Building2, Info, Loader2, Paperclip, Upload } from 'lucide-react';
import { attachments, businessUpdates, buyerParties, buyerIntents } from '../../lib/api';
import type { AttachmentUploadPolicy, BuyerPartyDedupCheck } from '../../types/api';
import Modal, { Field } from '../../components/Modal';
import { InlineWarning, UploadPolicyCard } from '../../components/UploadArea';
import { formatBytes } from '../../lib/format';
import { withTimeout } from '../../lib/utils';
import { UPLOAD_POLICY_TIMEOUT_MS } from './filters';
import { dedupMatchLabel } from './presentation';

/** 一份材料喂哪条链。默认两边都喂 —— 附件是多对多、OCR 按附件跑一次，「都用」几乎免费。 */
type MaterialUse = 'both' | 'intent' | 'party';

const MATERIAL_USE_LABEL: Record<MaterialUse, string> = {
  both: '都用',
  intent: '仅需求',
  party: '仅资料',
};

interface PickedFile {
  file: File;
  use: MaterialUse;
}

type BuyerIntakeForm = {
  buyer_name: string;
  raw_requirement_text: string;
};

const DEFAULT_BUYER_INTAKE_FORM: BuyerIntakeForm = {
  buyer_name: '',
  raw_requirement_text: '',
};

/**
 * 新建买家。
 *
 * 一次录入产出的是**一个买家 + 它的一条需求**，而匹配要同时用买家自身条件和它的
 * 要求 —— 所以两条 AI 链都在这里可选，默认都开。「不补买家资料」才是需要用户主动
 * 取消的那一侧：不补，这个买家就只有半边条件能进推荐，协同性类要求在深评那里只能
 * 判「无法判断」。
 */
export default function CreateIntentModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [dedupCheck, setDedupCheck] = useState<BuyerPartyDedupCheck | null>(null);
  const [checkingDedup, setCheckingDedup] = useState(false);
  const [form, setForm] = useState<BuyerIntakeForm>(DEFAULT_BUYER_INTAKE_FORM);
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<PickedFile[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  // 两条链默认都开。联网单独一档：它要 5–10 分钟且花钱，得让人自己点。
  const [parseIntent, setParseIntent] = useState(true);
  const [fillParty, setFillParty] = useState(true);
  const [enableResearch, setEnableResearch] = useState(false);

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

  const materialText = form.raw_requirement_text.trim();
  const hasMaterial = materialText.length > 0 || selectedFiles.length > 0;
  // 没有任何材料时联网是买家资料唯一的信息来源，所以锁上而不是让人提交一个空跑。
  const researchForced = fillParty && !hasMaterial;
  const researchChecked = researchForced || enableResearch;
  const imageLimit = uploadPolicy?.image_policy.constraints.max_count_per_business_update ?? 5;
  const taskCount = (parseIntent && hasMaterial ? 1 : 0) + (fillParty ? 1 : 0);

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
      const duplicate = nextFiles.some(
        (item) => item.file.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified
      );
      if (duplicate) continue;
      nextFiles.push({ file, use: 'both' });
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

  function setFileUse(index: number, use: MaterialUse) {
    setSelectedFiles((files) => files.map((item, itemIndex) => (itemIndex === index ? { ...item, use } : item)));
  }

  const createBuyerIntent = async (buyerPartyId: string | null, buyerName: string) => {
    setSaving(true);
    setSubmitError(null);
    setWarning(null);
    // 自己新建的主体才回滚。复用已有主体时把它删掉是删别人的数据。
    let createdPartyId: string | null = null;
    try {
      const rawText = buildBuyerIntakeRawText(buyerName, materialText);
      let resolvedBuyerPartyId = buyerPartyId;
      if (!resolvedBuyerPartyId) {
        resolvedBuyerPartyId = (await buyerParties.create({ buyer_name: buyerName })).id;
        createdPartyId = resolvedBuyerPartyId;
      }

      const shouldParseIntent = parseIntent && hasMaterial;
      let createdIntentId: string;
      try {
        createdIntentId = (await buyerIntents.create({
          buyer_party_id: resolvedBuyerPartyId,
          intent_name: defaultBuyerIntentName(buyerName),
          raw_requirement_text: shouldParseIntent ? rawText : undefined,
        })).id;
      } catch (intentError) {
        // 需求没建成，刚建的主体就是个孤儿 —— 它挂 0 条需求，买家列表里根本看不见，
        // 只有下次查重才会冒出来。生产里已经积了 8 条这种空壳。
        if (createdPartyId) {
          await buyerParties.delete(createdPartyId).catch(() => {
            setWarning('需求创建失败，且刚建的买家主体没能清掉，请在买家详情里手动删除。');
          });
        }
        throw intentError;
      }

      // 到这里需求已经建好了。后面的解析/调研再失败也**不回滚** —— 那会把用户
      // 刚录的材料一起删掉，比「建好了但没解析」糟得多。改成把失败说清楚。
      const failures: string[] = [];
      // 需求那条链承载 use ∈ {both, intent}；主体那条链要 use ∈ {both, party}。
      // 「both」的文件只上传一次（走需求那条），主体侧靠 attachment_id 补一条链接
      // ——附件是独立表、link 是多对多、OCR 按附件跑一次，所以「都用」几乎免费。
      const intentFiles = shouldParseIntent ? selectedFiles.filter((item) => item.use !== 'party') : [];
      // 上传后按下标回填 id：uploaded_attachment_ids 与传入 files 同序。
      const idByFile = new Map<File, string>();

      if (intentFiles.length > 0) {
        try {
          const uploadedIds = await uploadIntentMaterials({
            files: intentFiles.map((item) => item.file),
            rawText,
            buyerName,
            buyerPartyId: resolvedBuyerPartyId,
            buyerIntentId: createdIntentId,
          });
          intentFiles.forEach((item, index) => {
            const id = uploadedIds[index];
            if (id) idByFile.set(item.file, id);
          });
        } catch (uploadError) {
          failures.push(`需求附件上传失败：${messageOf(uploadError)}`);
        }
      } else if (shouldParseIntent) {
        try {
          await buyerIntents.parse(createdIntentId, { raw_requirement_text: rawText });
        } catch (parseError) {
          failures.push(`需求解析没能发起：${messageOf(parseError)}`);
        }
      }

      if (fillParty) {
        try {
          const wanted = selectedFiles.filter((item) => item.use !== 'intent');
          const ids = wanted.map((item) => idByFile.get(item.file)).filter((id): id is string => Boolean(id));
          // 剩下的是需求那条链没传过的（use=party，或需求解析被关掉了）。
          const notUploaded = wanted.filter((item) => !idByFile.has(item.file)).map((item) => item.file);
          if (notUploaded.length) {
            const uploaded = await buyerParties.uploadMaterials(resolvedBuyerPartyId, notUploaded);
            ids.push(...uploaded.attachment_ids.map(String));
          }
          await buyerParties.parse(resolvedBuyerPartyId, {
            raw_text: materialText || null,
            attachment_ids: ids,
            enable_research: researchChecked,
            mode: 'fill',
          });
        } catch (partyError) {
          failures.push(`买家资料补全没能发起：${messageOf(partyError)}`);
        }
      }

      if (failures.length) {
        setWarning(`买家已创建，但${failures.join('；')}。可以在详情页重试。`);
      }
      onCreated();
    } catch (err) {
      setSubmitError(messageOf(err));
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
      <Modal title="新建买家" onClose={onClose}>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800 flex gap-2">
            <Building2 className="w-4 h-4 mt-0.5 shrink-0" />
            <p className="leading-relaxed">
              一次录入一个买家和它的一项并购需求。<strong>买家自己的资料和它的收购要求都会进推荐匹配</strong>，
              两边都补齐这个买家才算能用。
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

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-2">这次要做什么</label>
            <div className="space-y-2 border border-gray-200 px-3 py-2.5">
              <label className="flex items-start gap-2 text-sm text-gray-700">
                <input type="checkbox" className="mt-0.5 h-4 w-4" checked={parseIntent} onChange={(e) => setParseIntent(e.target.checked)} />
                <span>
                  解析并购需求
                  <span className="ml-1 text-xs text-gray-400">行业、地区、利润、股权、排除项</span>
                  {parseIntent && !hasMaterial ? <span className="ml-1 text-xs text-amber-700">没有材料，这项不会执行</span> : null}
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm text-gray-700">
                <input type="checkbox" className="mt-0.5 h-4 w-4" checked={fillParty} onChange={(e) => setFillParty(e.target.checked)} />
                <span>
                  补全买家自身资料
                  <span className="ml-1 text-xs text-gray-400">性质、上市、财务、业务标签</span>
                </span>
              </label>
              {fillParty ? (
                <label className="ml-6 flex items-start gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4"
                    checked={researchChecked}
                    disabled={researchForced}
                    onChange={(e) => setEnableResearch(e.target.checked)}
                  />
                  <span>
                    联网补全材料里没有的信息
                    <span className="ml-1 text-xs text-gray-500">约 5–10 分钟 · 计费</span>
                    {researchForced ? <span className="ml-1 text-xs text-amber-700">没有材料时这是唯一来源，已自动勾选。</span> : null}
                  </span>
                </label>
              ) : null}
              {!parseIntent && !fillParty ? (
                <p className="text-xs text-amber-700">两项都不选就只建一个空买家，它不会进入推荐。</p>
              ) : null}
            </div>
          </div>

          <Field label="材料">
            <textarea
              value={form.raw_requirement_text}
              onChange={(e) => updateForm('raw_requirement_text', e.target.value)}
              className="input min-h-[150px] resize-y leading-relaxed"
              placeholder={'可粘贴聊天记录、邮件、公司简介、投资偏好或访谈纪要 —— 需求和买家资料混在一起也没关系，两条链各取所需。\n示例：我们是广东省属food集团，旗下三个盐场。关注长三角医药健康资产，净利润2000万以上，优先控股并表。'}
            />
          </Field>

          <div>
            <div
              className="border border-dashed border-gray-300 bg-gray-50 px-4 py-3 text-sm text-gray-600 transition-colors hover:border-brand-300 hover:bg-brand-50/40"
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleFileDrop}
            >
              <div className="flex items-center gap-2">
                <Upload className="w-4 h-4 text-brand-600" />
                <span className="text-xs text-gray-600">拖拽文件到这里，或上传图片、PDF、Office、文本附件</span>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="ml-auto shrink-0 bg-white border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-brand-300 hover:text-brand-700"
                >
                  选择文件
                </button>
              </div>
              <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} />

              {selectedFiles.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {selectedFiles.map((item, index) => (
                    <div key={`${item.file.name}-${item.file.size}-${item.file.lastModified}`} className="flex items-center gap-2 bg-white border border-gray-200 px-3 py-2">
                      <Paperclip className="w-3.5 h-3.5 shrink-0 text-gray-400" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-gray-800">{item.file.name}</p>
                        <p className="text-[11px] text-gray-400">{formatBytes(item.file.size)}</p>
                      </div>
                      {/* 默认「都用」，改用途是可选动作而不是每次上传都得做的决定。 */}
                      <select
                        value={item.use}
                        onChange={(event) => setFileUse(index, event.target.value as MaterialUse)}
                        aria-label={`${item.file.name} 的用途`}
                        className="shrink-0 border border-gray-200 bg-white px-1.5 py-1 text-[11px] text-gray-600"
                      >
                        {(Object.keys(MATERIAL_USE_LABEL) as MaterialUse[]).map((value) => (
                          <option key={value} value={value}>{MATERIAL_USE_LABEL[value]}</option>
                        ))}
                      </select>
                      <button type="button" onClick={() => removeFile(index)} className="shrink-0 text-xs text-gray-400 hover:text-red-600">移除</button>
                    </div>
                  ))}
                </div>
              )}

              {/* 静默截断是这条链最容易骗人的地方，所以上限写在点击之前；其余规则收进 ⓘ。 */}
              <p className="mt-2 flex items-start gap-1 text-[11px] text-amber-700">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                拍照的图片单次最多 {imageLimit} 张，超出的不会进入解析且不会报错。年报这类多页材料请传 PDF。
              </p>
              <button
                type="button"
                onClick={() => setPolicyOpen((open) => !open)}
                className="mt-1 inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600"
              >
                <Info className="h-3 w-3" />
                {policyOpen ? '收起上传规则' : '上传规则'}
              </button>
              {policyOpen && <UploadPolicyCard policy={uploadPolicy} loading={policyLoading} error={policyError} />}
              {fileError && <InlineWarning message={fileError} />}
            </div>
          </div>

          {submitError && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>}
          {warning && <div className="border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{warning}</div>}

          <div className="flex items-center justify-between gap-3 pt-2">
            <p className="text-xs text-gray-400">
              {taskCount > 0 ? '创建后在后台跑，进度在需求详情里看。' : '仅创建买家与需求，不触发任何解析。'}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
              <button type="submit" disabled={saving || checkingDedup || !form.buyer_name.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-2">
                {(saving || checkingDedup) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {checkingDedup ? '查重中...' : saving ? '创建中...' : taskCount > 0 ? `创建并开始（${taskCount} 项）` : '仅创建'}
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

/** 需求侧的附件走 business_update：它承载 OCR 与正文抽取，返回的 id 可以再链给主体。 */
async function uploadIntentMaterials({
  files,
  rawText,
  buyerName,
  buyerPartyId,
  buyerIntentId,
}: {
  files: File[];
  rawText: string;
  buyerName: string;
  buyerPartyId: string;
  buyerIntentId: string;
}): Promise<string[]> {
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
  formData.set('bound_buyer_intent_ids', JSON.stringify([buyerIntentId]));
  formData.set(
    'metadata_json',
    JSON.stringify({
      source: 'frontend_buyer_create_modal',
      buyer_party_id: buyerPartyId,
      buyer_intent_id: buyerIntentId,
      buyer_name: buyerName,
    })
  );
  files.forEach((file) => formData.append('files', file));
  const created = await businessUpdates.upload(formData);
  // 与传入 files 同序，调用方靠下标把「都用」的那几个再链给主体。
  return created.uploaded_attachment_ids || [];
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败';
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
