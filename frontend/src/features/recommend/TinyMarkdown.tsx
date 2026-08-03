import type { ReactNode } from 'react';

type MarkdownTable = {
  header: string[];
  rows: string[][];
  nextIndex: number;
};

/** Safe renderer for the report Markdown subset shared with DOCX export. */
export default function TinyMarkdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  let listItems: string[] = [];
  let key = 0;

  const nextKey = (prefix: string) => `${prefix}-${key += 1}`;
  const flushList = () => {
    if (!listItems.length) return;
    blocks.push(
      <ul key={nextKey('list')} className="my-2 list-disc space-y-1 pl-5">
        {listItems.map((item, index) => (
          <li key={index}>{renderInline(item)}</li>
        ))}
      </ul>,
    );
    listItems = [];
  };

  let index = 0;
  while (index < lines.length) {
    const trimmed = lines[index].trim();
    const table = readTable(lines, index);
    if (table) {
      flushList();
      blocks.push(
        <div key={nextKey('table')} className="my-3 overflow-x-auto border border-gray-200 bg-white">
          <table className="w-full min-w-[640px] border-collapse text-left text-xs leading-relaxed">
            <thead className="bg-gray-100 text-gray-800">
              <tr>
                {table.header.map((cell, cellIndex) => (
                  <th key={cellIndex} className="border-b border-r border-gray-200 px-3 py-2 font-semibold last:border-r-0">
                    {renderInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="align-top even:bg-gray-50/70">
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="border-b border-r border-gray-100 px-3 py-2 last:border-r-0">
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      index = table.nextIndex;
      continue;
    }

    const listMatch = /^[-*]\s+(.*)$/.exec(trimmed);
    if (listMatch) {
      listItems.push(listMatch[1]);
      index += 1;
      continue;
    }

    flushList();
    const headingMatch = /^(#{1,3})\s+(.*)$/.exec(trimmed);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const cls = level === 1
        ? 'mb-2 mt-3 text-lg font-bold text-gray-900'
        : level === 2
          ? 'mb-1.5 mt-4 text-base font-bold text-gray-900'
          : 'mb-1 mt-3 text-sm font-semibold text-gray-800';
      blocks.push(<p key={nextKey('heading')} className={cls}>{renderInline(headingMatch[2])}</p>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith('>')) {
      blocks.push(
        <blockquote key={nextKey('quote')} className="my-2 border-l-2 border-brand-300 bg-brand-50/50 px-3 py-2 text-gray-600">
          {renderInline(trimmed.replace(/^>\s?/, ''))}
        </blockquote>,
      );
      index += 1;
      continue;
    }
    if (!trimmed || trimmed === '---' || trimmed === '***') {
      if (!trimmed) blocks.push(<div key={nextKey('space')} className="h-1" />);
      index += 1;
      continue;
    }
    blocks.push(<p key={nextKey('paragraph')} className="leading-relaxed">{renderInline(trimmed)}</p>);
    index += 1;
  }
  flushList();

  return <div className="text-sm text-gray-700">{blocks}</div>;
}

function readTable(lines: string[], start: number): MarkdownTable | null {
  if (start + 1 >= lines.length || !lines[start].includes('|') || !lines[start + 1].includes('|')) {
    return null;
  }
  const header = splitTableRow(lines[start]);
  const separator = splitTableRow(lines[start + 1]);
  if (!header.length || header.length > 4 || header.length !== separator.length) return null;
  if (!separator.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, '')))) return null;

  const rows: string[][] = [];
  let index = start + 2;
  while (index < lines.length && lines[index].includes('|')) {
    const row = splitTableRow(lines[index]);
    if (!row.length) break;
    rows.push(Array.from({ length: header.length }, (_, cellIndex) => row[cellIndex] || ''));
    index += 1;
  }
  return { header, rows, nextIndex: index };
}

function splitTableRow(line: string): string[] {
  const value = line.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '');
  const cells: string[] = [];
  let current = '';
  let escaped = false;
  for (const character of value) {
    if (escaped) {
      current += character;
      escaped = false;
    } else if (character === '\\') {
      escaped = true;
    } else if (character === '|') {
      cells.push(current.trim());
      current = '';
    } else {
      current += character;
    }
  }
  cells.push(current.trim());
  return cells;
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
