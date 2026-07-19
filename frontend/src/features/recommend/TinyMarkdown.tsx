import type { ReactNode } from 'react';

/** Minimal markdown renderer for report previews (headings, lists, bold). */
export default function TinyMarkdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  let listItems: string[] = [];
  let key = 0;

  const flushList = () => {
    if (!listItems.length) return;
    blocks.push(
      <ul key={`list-${key += 1}`} className="my-1.5 list-disc space-y-0.5 pl-5">
        {listItems.map((item, index) => (
          <li key={index}>{renderInline(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const listMatch = /^[-*]\s+(.*)$/.exec(trimmed);
    if (listMatch) {
      listItems.push(listMatch[1]);
      continue;
    }
    flushList();
    const headingMatch = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const cls = level === 1
        ? 'mt-3 text-base font-bold text-gray-900'
        : level === 2
          ? 'mt-3 text-sm font-bold text-gray-900'
          : 'mt-2 text-sm font-semibold text-gray-800';
      blocks.push(<p key={`h-${key += 1}`} className={cls}>{renderInline(headingMatch[2])}</p>);
      continue;
    }
    if (!trimmed) {
      blocks.push(<div key={`sp-${key += 1}`} className="h-1.5" />);
      continue;
    }
    blocks.push(<p key={`p-${key += 1}`} className="leading-relaxed">{renderInline(trimmed)}</p>);
  }
  flushList();

  return <div className="text-sm text-gray-700">{blocks}</div>;
}

function renderInline(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  if (parts.length === 1) return text;
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}
