import { Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import type { RelationBoardCard } from '../../types/api';
import { relationStatusClass, relationStatusLabel } from '../relations/relationLabels';
import {
  cardActivityDays,
  cardPath,
  cardStaleDays,
  counterpartLabel,
  counterpartNameOf,
  subjectNameOf,
  type BoardView,
} from './boardBuckets';

/**
 * 看板卡片：一条关系，固定 4 行——主体 / 买家 / 对手方 / 状态（D3）。
 * 两个视角行序严格对称，只有第一行和第三行换人。
 *
 * nested 变体用于折叠摞展开后的内层卡：摞头已经承担了主体名，这里省掉第一行。
 */
export default function RelationCard({
  card,
  view,
  nested = false,
}: {
  card: RelationBoardCard;
  view: BoardView;
  nested?: boolean;
}) {
  const staleDays = cardStaleDays(card);
  const activityDays = cardActivityDays(card);

  return (
    <Link
      to={cardPath(card, view)}
      className={
        nested
          ? 'block border-l-2 border-gray-200 py-1.5 pl-2.5 pr-1 hover:border-brand-400 hover:bg-brand-50/40'
          : 'block border border-gray-200 bg-white px-2.5 py-2 hover:border-brand-400'
      }
      title={`${subjectNameOf(card, view)} × ${card.buyer_name || '-'}`}
    >
      {nested ? null : (
        <p className="truncate text-xs font-medium text-gray-900">{subjectNameOf(card, view)}</p>
      )}
      <p className="mt-0.5 truncate text-[11px] text-gray-600">
        <span className="mr-1 text-gray-400">买家</span>
        {card.buyer_name || '-'}
      </p>
      <p className="mt-0.5 truncate text-[11px] text-gray-600">
        <span className="mr-1 text-gray-400">{counterpartLabel(view)}</span>
        {counterpartNameOf(card, view)}
      </p>
      <div className="mt-1 flex items-center justify-between gap-1">
        <span className={`shrink-0 px-1.5 py-0.5 text-[11px] ${relationStatusClass(card.status)}`}>
          {relationStatusLabel(card.status)}
        </span>
        {staleDays !== null ? (
          <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-amber-600">
            <AlertTriangle className="h-2.5 w-2.5" />
            {staleDays}天无动态
          </span>
        ) : (
          <span className="shrink-0 text-[11px] text-gray-400">
            {activityDays === null ? '' : activityDays === 0 ? '今天' : `${activityDays}天前`}
          </span>
        )}
      </div>
    </Link>
  );
}
