import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, Pencil, X } from 'lucide-react';
import { profileSections } from '../../lib/api';
import type { ProfileSection, ProfileSectionsResponse } from '../../types/api';

const STATUS_LABELS: Record<ProfileSection['info_status'], string> = {
  filled: '已填写',
  not_found: '暂无信息',
  not_applicable: '不适用',
};

/**
 * 匹配画像：深评真正读的那一层。结构化字段答不了"是不是链主、团队怎么样"，
 * 这六栏就是给这类判断准备的，未填的栏目同时是调研任务清单。
 */
export default function ProfileSectionsPanel({
  entityType,
  entityId,
}: {
  entityType: 'seller_target' | 'buyer_intent';
  entityId: string;
}) {
  const [data, setData] = useState<ProfileSectionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await profileSections.list(entityType, entityId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载画像失败');
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId]);

  useEffect(() => {
    void load();
  }, [load]);

  const currentByCode = new Map<string, ProfileSection>();
  for (const section of data?.sections || []) {
    if (!currentByCode.has(section.section_code)) currentByCode.set(section.section_code, section);
  }

  const save = async (code: string, infoStatus: ProfileSection['info_status']) => {
    setSaving(true);
    try {
      await profileSections.write(entityType, entityId, {
        section_code: code,
        info_status: infoStatus,
        content_text: infoStatus === 'filled' ? draft : null,
      });
      setEditing(null);
      setDraft('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 border border-gray-200 bg-white px-4 py-3 text-xs text-gray-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        加载匹配画像…
      </div>
    );
  }

  return (
    <div className="border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-900">匹配画像</h2>
        {data && (
          <span className="text-xs text-gray-400">
            已填 {data.coverage.filled_sections.length}/{data.section_catalog.length}
            {data.coverage.missing_sections.length > 0 && `　待补：${data.coverage.missing_sections.join('、')}`}
          </span>
        )}
      </div>
      {error && <p className="border-b border-red-100 bg-red-50 px-4 py-1.5 text-xs text-red-600">{error}</p>}
      <div className="divide-y divide-gray-100">
        {(data?.section_catalog || []).map((entry) => {
          const section = currentByCode.get(entry.code);
          const isEditing = editing === entry.code;
          return (
            <div key={entry.code} className="px-4 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-gray-700">{entry.label}</span>
                {!isEditing && (
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(entry.code);
                      setDraft(section?.content_text || '');
                    }}
                    className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
                  >
                    <Pencil className="h-3 w-3" />
                    {section ? '编辑' : '填写'}
                  </button>
                )}
              </div>
              {isEditing ? (
                <div className="mt-1.5 space-y-1.5">
                  <textarea
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    rows={3}
                    className="w-full border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-brand-600"
                    placeholder="只写结构化字段装不下的定性判断，财务数字留在字段里"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={saving || !draft.trim()}
                      onClick={() => void save(entry.code, 'filled')}
                      className="inline-flex items-center gap-1 bg-brand-600 px-2.5 py-1 text-xs text-white disabled:opacity-40"
                    >
                      <Check className="h-3 w-3" />
                      保存
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void save(entry.code, 'not_found')}
                      className="border border-gray-200 px-2.5 py-1 text-xs text-gray-600 disabled:opacity-40"
                      title="明确记录为暂无信息，深评据此知道这是缺口而非不相关"
                    >
                      标为暂无信息
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void save(entry.code, 'not_applicable')}
                      className="border border-gray-200 px-2.5 py-1 text-xs text-gray-600 disabled:opacity-40"
                    >
                      不适用
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(null)}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ) : (
                <p className={`mt-0.5 text-xs ${section ? 'text-gray-600' : 'text-gray-300'}`}>
                  {section
                    ? section.info_status === 'filled'
                      ? section.content_text
                      : `（${STATUS_LABELS[section.info_status]}）`
                    : '未填写'}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
