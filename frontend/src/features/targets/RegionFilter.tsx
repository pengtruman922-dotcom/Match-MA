import { useMemo } from 'react';
import { areaList } from '@vant/area-data';
import CascadeFilter, { childrenOf, withCounts } from '../../components/CascadeFilter';
import type { SellerTargetCountedOption } from '../../types/api';

export interface RegionSelection {
  province: string;
  city: string;
  district: string;
}

const PROVINCE_ENTRIES = Object.entries(areaList.province_list) as Array<[string, string]>;
const CITY_ENTRIES = Object.entries(areaList.city_list) as Array<[string, string]>;
const COUNTY_ENTRIES = Object.entries(areaList.county_list) as Array<[string, string]>;

function codeOf(entries: Array<[string, string]>, name: string, parentPrefix = ''): string {
  return entries.find(([code, label]) => label === name && code.startsWith(parentPrefix))?.[0] || '';
}

/**
 * 省 → 市 → 区, filtering at whatever level the user picked.
 *
 * The option skeleton is the standard administrative division dictionary (the
 * same `@vant/area-data` the information page edits with), not the distinct
 * values present in the library — otherwise "整个广东省" would only be offered
 * when some target happened to have a blank city.
 */
export default function RegionFilter({
  value,
  options,
  onChange,
}: {
  value: RegionSelection;
  options: SellerTargetCountedOption[] | undefined;
  onChange: (next: RegionSelection) => void;
}) {
  const provinceOptions = useMemo(
    () => withCounts(PROVINCE_ENTRIES.map(([, name]) => name), options),
    [options],
  );

  const provinceCode = codeOf(PROVINCE_ENTRIES, value.province);
  const cityOptions = useMemo(() => {
    if (!value.province) return [];
    const names = CITY_ENTRIES.filter(([code]) => code.slice(0, 2) === provinceCode.slice(0, 2)).map(
      ([, name]) => name,
    );
    return withCounts(names, childrenOf(options, value.province));
  }, [options, provinceCode, value.province]);

  const cityCode = codeOf(CITY_ENTRIES, value.city, provinceCode.slice(0, 2));
  const districtOptions = useMemo(() => {
    if (!value.city) return [];
    const names = COUNTY_ENTRIES.filter(([code]) => code.slice(0, 4) === cityCode.slice(0, 4)).map(
      ([, name]) => name,
    );
    return withCounts(names, childrenOf(childrenOf(options, value.province), value.city));
  }, [cityCode, options, value.city, value.province]);

  const summary =
    [value.province, value.city, value.district].filter(Boolean).join(' ') || '全部';

  return (
    <CascadeFilter
      label="地区"
      summary={summary}
      onClear={() => onChange({ province: '', city: '', district: '' })}
      levels={[
        {
          placeholder: '省',
          options: provinceOptions,
          value: value.province,
          searchable: true,
          // Changing a level clears the ones below it, otherwise 广东省+杭州市
          // would silently return nothing.
          onChange: (province) => onChange({ province, city: '', district: '' }),
        },
        {
          placeholder: '市',
          options: cityOptions,
          value: value.city,
          disabled: !value.province,
          searchable: true,
          onChange: (city) => onChange({ ...value, city, district: '' }),
        },
        {
          placeholder: '区/县',
          options: districtOptions,
          value: value.district,
          disabled: !value.city,
          searchable: true,
          onChange: (district) => onChange({ ...value, district }),
        },
      ]}
    />
  );
}
