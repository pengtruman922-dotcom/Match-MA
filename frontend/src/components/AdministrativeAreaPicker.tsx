import { areaList } from '@vant/area-data';

export interface AdministrativeAreaValue {
  province: string;
  city?: string;
  district?: string;
}

const areaEntries = {
  province: Object.entries(areaList.province_list),
  city: Object.entries(areaList.city_list),
  district: Object.entries(areaList.county_list),
};

function areaCode(entries: Array<[string, string]>, name?: string): string {
  return entries.find(([, label]) => label === name)?.[0] || '';
}

export default function AdministrativeAreaPicker({
  value,
  onChange,
}: {
  value: AdministrativeAreaValue;
  onChange: (value: AdministrativeAreaValue) => void;
}) {
  const provinceCode = areaCode(areaEntries.province, value.province);
  const cityCode = areaCode(areaEntries.city, value.city);
  const cityOptions = areaEntries.city.filter(([code]) => !provinceCode || code.slice(0, 2) === provinceCode.slice(0, 2));
  const districtOptions = areaEntries.district.filter(([code]) => !cityCode || code.slice(0, 4) === cityCode.slice(0, 4));

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <select value={value.province} onChange={(event) => onChange({ province: event.target.value })} className="border border-gray-200 bg-white px-2 py-1.5 text-xs">
        <option value="">省（可不填）</option>
        {areaEntries.province.map(([code, name]) => <option key={code} value={name}>{name}</option>)}
      </select>
      <select value={value.city || ''} onChange={(event) => onChange({ province: value.province, city: event.target.value || undefined })} disabled={!value.province} className="border border-gray-200 bg-white px-2 py-1.5 text-xs disabled:bg-gray-100">
        <option value="">市（可不填）</option>
        {cityOptions.map(([code, name]) => <option key={code} value={name}>{name}</option>)}
      </select>
      <select value={value.district || ''} onChange={(event) => onChange({ ...value, district: event.target.value || undefined })} disabled={!value.city} className="border border-gray-200 bg-white px-2 py-1.5 text-xs disabled:bg-gray-100">
        <option value="">区/县（可不填）</option>
        {districtOptions.map(([code, name]) => <option key={code} value={name}>{name}</option>)}
      </select>
    </div>
  );
}
