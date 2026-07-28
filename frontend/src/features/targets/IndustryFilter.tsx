import { useEffect, useMemo, useState } from 'react';
import CascadeFilter, { childrenOf, withCounts } from '../../components/CascadeFilter';
import { meta } from '../../lib/api';
import type { IndustryOptionsResponse, SellerTargetCountedOption } from '../../types/api';

export interface IndustrySelection {
  l1: string;
  l2: string;
}

/**
 * 一级 → 二级行业, sourced from the industry dictionary.
 *
 * The dictionary is the same one the information page edits against, so a
 * target classified into a rarely-used 赛道 is still reachable. Selecting only
 * a level-1 category is a first-class case: the backend matches any pair whose
 * l1 hits, which is what "看整个商贸与消费" means.
 */
export default function IndustryFilter({
  value,
  options,
  onChange,
}: {
  value: IndustrySelection;
  options: SellerTargetCountedOption[] | undefined;
  onChange: (next: IndustrySelection) => void;
}) {
  const [dictionary, setDictionary] = useState<IndustryOptionsResponse>({ l1: [], l2: [] });

  useEffect(() => {
    let cancelled = false;
    meta
      .industryOptions()
      .then((response) => {
        if (!cancelled) setDictionary(response);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const l1Options = useMemo(
    () => withCounts(dictionary.l1.map((item) => item.term), options),
    [dictionary.l1, options],
  );

  const l2Options = useMemo(() => {
    if (!value.l1) return [];
    const terms = dictionary.l2.filter((item) => item.l1 === value.l1).map((item) => item.term);
    return withCounts(terms, childrenOf(options, value.l1));
  }, [dictionary.l2, options, value.l1]);

  const summary = [value.l1, value.l2].filter(Boolean).join(' / ') || '全部';

  return (
    <CascadeFilter
      label="行业"
      summary={summary}
      onClear={() => onChange({ l1: '', l2: '' })}
      levels={[
        {
          placeholder: '一级行业',
          options: l1Options,
          value: value.l1,
          searchable: true,
          onChange: (l1) => onChange({ l1, l2: '' }),
        },
        {
          placeholder: '二级行业',
          options: l2Options,
          value: value.l2,
          disabled: !value.l1,
          searchable: true,
          onChange: (l2) => onChange({ ...value, l2 }),
        },
      ]}
    />
  );
}
