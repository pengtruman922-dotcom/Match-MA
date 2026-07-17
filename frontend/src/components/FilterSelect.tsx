import { useState } from 'react';
import { ChevronDown } from 'lucide-react';

export interface FilterOption {
  value: string;
  label: string;
  count: number;
}

export default function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: FilterOption[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectedOption = options.find((option) => option.value === value);
  const displayText = selectedOption ? selectedOption.label : '全部';

  return (
    <div className="relative w-[180px]">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        className="flex w-full items-center justify-between gap-2 border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-600 outline-none transition-colors hover:border-brand-300 focus:border-brand-600"
        title={`${label} ${displayText}`}
      >
        <span className="truncate">{label} {displayText}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+4px)] z-40 max-h-64 w-[220px] overflow-y-auto border border-gray-200 bg-white py-1 shadow-lg">
          <button
            type="button"
            onMouseDown={(event) => {
              event.preventDefault();
              onChange('');
              setOpen(false);
            }}
            className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-brand-50 ${!value ? 'text-brand-700' : 'text-gray-700'}`}
          >
            <span className="truncate">{label} 全部</span>
          </button>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onChange(option.value);
                setOpen(false);
              }}
              className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-brand-50 ${value === option.value ? 'text-brand-700' : 'text-gray-700'}`}
              title={option.label}
            >
              <span className="truncate">{option.label}</span>
              <span className="shrink-0 text-xs text-gray-400">{option.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
