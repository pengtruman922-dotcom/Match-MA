import { useCallback, useEffect, useState } from 'react';
import { Download, Pencil, Plus, Upload } from 'lucide-react';
import { dataDictionaries } from '../../lib/api';
import type { IndustryDictionaryImportResult, IndustryDictionaryTerm } from '../../types/api';
import { Editor, Field, Grid, Loading, SaveButton, Status, Td, Th } from './shared';

export default function IndustryDictionary() {
  const [items, setItems] = useState<IndustryDictionaryTerm[]>([]);
  const [l1Options, setL1Options] = useState<IndustryDictionaryTerm[]>([]);
  const [q, setQ] = useState('');
  const [level, setLevel] = useState('');
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<IndustryDictionaryTerm | 'new' | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await dataDictionaries.industry({ q: q || undefined, level: level || undefined, include_inactive: true }));
    } catch (loadError) {
      alert(loadError instanceof Error ? loadError.message : '读取行业字典失败');
    } finally {
      setLoading(false);
    }
  }, [q, level]);

  const loadL1Options = useCallback(async () => {
    try {
      setL1Options(await dataDictionaries.industry({ level: 'l1', include_inactive: true }));
    } catch {
      setL1Options([]);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => { void loadL1Options(); }, [loadL1Options]);

  const toggle = async (item: IndustryDictionaryTerm) => {
    try {
      await dataDictionaries.updateIndustryTerm(item.id, { active: !item.active });
      await Promise.all([load(), loadL1Options()]);
    } catch (toggleError) {
      alert(toggleError instanceof Error ? toggleError.message : '更新状态失败');
    }
  };

  const downloadTemplate = async () => {
    try {
      const response = await dataDictionaries.industryImportTemplate();
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'industry_dictionary_template.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      alert(downloadError instanceof Error ? downloadError.message : '下载模板失败');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">行业字典</h2>
          <p className="mt-1 text-xs text-gray-500">维护一级、二级标准行业及其别名。改字典即时生效，Prompt 渲染时自动注入启用中的清单。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void downloadTemplate()} className="inline-flex items-center gap-1.5 border border-gray-300 px-3 py-2 text-sm text-gray-700"><Download className="h-4 w-4" />下载模板</button>
          <button type="button" onClick={() => setImporting(true)} className="inline-flex items-center gap-1.5 border border-gray-300 px-3 py-2 text-sm text-gray-700"><Upload className="h-4 w-4" />批量导入</button>
          <button type="button" onClick={() => setEditing('new')} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新增词条</button>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input className="input max-w-sm" placeholder="搜索标准行业或别名" value={q} onChange={(event) => setQ(event.target.value)} />
        <select className="input w-36" value={level} onChange={(event) => setLevel(event.target.value)}>
          <option value="">全部层级</option>
          <option value="l1">一级行业</option>
          <option value="l2">二级行业</option>
        </select>
      </div>
      <div className="overflow-x-auto border border-gray-200 bg-white">
        <table className="min-w-[920px] text-left text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500">
            <tr><Th>标准行业</Th><Th>层级</Th><Th>所属一级行业</Th><Th>别名</Th><Th>使用量</Th><Th>状态</Th><Th>操作</Th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? <tr><td colSpan={7}><Loading /></td></tr> : items.map((item) => (
              <tr key={item.id}>
                <Td><span className="font-medium text-gray-900">{item.term}</span></Td>
                <Td>{levelLabel(item.level)}</Td>
                <Td>{item.level === 'l1' ? '-' : item.parent_name || item.l1_name}</Td>
                <Td clamp><span title={item.aliases.map((alias) => alias.term).join('、')}>{item.aliases.filter((alias) => alias.active).map((alias) => alias.term).join('、') || '-'}</span></Td>
                <Td>{item.usage_count}</Td>
                <Td><Status active={item.active} /></Td>
                <Td>
                  <div className="flex items-center gap-3">
                    <button type="button" onClick={() => setEditing(item)} className="inline-flex items-center gap-1 text-xs text-brand-700"><Pencil className="h-3.5 w-3.5" />编辑</button>
                    <button type="button" onClick={() => void toggle(item)} className="text-xs text-gray-600">{item.active ? '停用' : '启用'}</button>
                  </div>
                </Td>
              </tr>
            ))}
            {!loading && items.length === 0 ? <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-400">没有符合条件的词条</td></tr> : null}
          </tbody>
        </table>
      </div>
      {editing ? <IndustryTermEditor term={editing === 'new' ? null : editing} l1Options={l1Options} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await Promise.all([load(), loadL1Options()]); }} /> : null}
      {importing ? <IndustryImportEditor onClose={() => setImporting(false)} onImported={async () => { setImporting(false); await Promise.all([load(), loadL1Options()]); }} /> : null}
    </div>
  );
}

function IndustryTermEditor({
  term,
  l1Options,
  onClose,
  onSaved,
}: {
  term: IndustryDictionaryTerm | null;
  l1Options: IndustryDictionaryTerm[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(term?.term || '');
  const [level, setLevel] = useState<'l1' | 'l2'>(term?.level || 'l2');
  const [parentId, setParentId] = useState(term?.parent_id || '');
  const [aliases, setAliases] = useState(term?.aliases.filter((alias) => alias.active).map((alias) => alias.term).join('、') || '');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) { alert('请填写标准行业名称。'); return; }
    if (level === 'l2' && !parentId) { alert('请选择所属一级行业。'); return; }
    const payload = { term: name.trim(), parent_id: level === 'l2' ? parentId : null, aliases: splitAliases(aliases) };
    setSaving(true);
    try {
      if (term) await dataDictionaries.updateIndustryTerm(term.id, payload);
      else await dataDictionaries.createIndustryTerm({ ...payload, level, active: true, sort_order: 0 });
      await onSaved();
    } catch (saveError) {
      alert(saveError instanceof Error ? saveError.message : '保存行业词条失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Editor title={term ? '编辑行业词条' : '新增行业词条'} onClose={onClose} footer={<SaveButton saving={saving} onClick={save} />}>
      <Grid>
        <Field label="层级">
          <select className="input" value={level} disabled={Boolean(term)} onChange={(event) => setLevel(event.target.value as 'l1' | 'l2')}>
            <option value="l1">一级行业</option>
            <option value="l2">二级行业</option>
          </select>
        </Field>
        <Field label="标准行业名称"><input className="input" value={name} disabled={term?.level === 'l1'} onChange={(event) => setName(event.target.value)} /></Field>
      </Grid>
      {level === 'l2' ? (
        <Field label="所属一级行业">
          <select className="input" value={parentId} onChange={(event) => setParentId(event.target.value)}>
            <option value="">请选择</option>
            {l1Options.map((item) => (
              <option key={item.id} value={item.id} disabled={!item.active && item.id !== parentId}>{item.term}{item.active ? '' : '（已停用）'}</option>
            ))}
          </select>
        </Field>
      ) : null}
      <Field label="别名" hint="别名不是分类层级，用于把常见说法映射到当前标准行业。">
        <textarea className="input min-h-24 resize-y" placeholder="多个别名用逗号、顿号或换行分隔" value={aliases} onChange={(event) => setAliases(event.target.value)} />
      </Field>
    </Editor>
  );
}

function IndustryImportEditor({ onClose, onImported }: { onClose: () => void; onImported: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<IndustryDictionaryImportResult | null>(null);
  const [loading, setLoading] = useState(false);

  const selectFile = async (selected: File | null) => {
    setFile(selected);
    setPreview(null);
    if (!selected) return;
    setLoading(true);
    try {
      setPreview(await dataDictionaries.importIndustry(selected, true));
    } catch (previewError) {
      alert(previewError instanceof Error ? previewError.message : '读取导入文件失败');
    } finally {
      setLoading(false);
    }
  };

  const apply = async () => {
    if (!file || !preview || preview.error_rows > 0) return;
    setLoading(true);
    try {
      const result = await dataDictionaries.importIndustry(file, false);
      alert(`导入完成：新增一级行业 ${result.created_l1} 条、二级行业 ${result.created_l2} 条、别名 ${result.created_aliases} 条。`);
      await onImported();
    } catch (applyError) {
      alert(applyError instanceof Error ? applyError.message : '导入行业字典失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Editor title="批量导入行业字典" onClose={onClose} footer={<SaveButton saving={loading} onClick={apply} label="确认导入" disabled={!preview || preview.error_rows > 0} />}>
      <label className="flex cursor-pointer items-center justify-center border border-dashed border-gray-300 px-4 py-8 text-sm text-gray-600">
        <Upload className="mr-2 h-4 w-4" />{file?.name || '选择 CSV 或 XLSX 文件'}
        <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(event) => void selectFile(event.target.files?.[0] || null)} />
      </label>
      {loading && !preview ? <Loading /> : null}
      {preview ? (
        <>
          <div className="flex gap-4 text-xs text-gray-600">
            <span>总计 {preview.total_rows}</span>
            <span className="text-emerald-700">可导入 {preview.ready_rows}</span>
            <span className={preview.error_rows ? 'text-red-600' : ''}>错误 {preview.error_rows}</span>
          </div>
          <div className="max-h-[50vh] overflow-auto border border-gray-200">
            <table className="min-w-[720px] text-left text-xs">
              <thead className="sticky top-0 bg-gray-50 text-gray-500"><tr><Th>行</Th><Th>一级行业</Th><Th>二级行业</Th><Th>别名</Th><Th>校验</Th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {preview.rows.map((row) => (
                  <tr key={row.row_number}>
                    <Td>{row.row_number}</Td>
                    <Td>{row.l1 || '-'}</Td>
                    <Td>{row.l2 || '-'}</Td>
                    <Td clamp>{row.aliases.join('、') || '-'}</Td>
                    <Td><span className={row.status === 'error' ? 'text-red-600' : 'text-emerald-700'}>{row.message}</span></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </Editor>
  );
}

function levelLabel(level: string) {
  return level === 'l1' ? '一级行业' : '二级行业';
}

function splitAliases(value: string): string[] {
  return Array.from(new Set(value.split(/[，、,;；\n]/).map((item) => item.trim()).filter(Boolean)));
}
