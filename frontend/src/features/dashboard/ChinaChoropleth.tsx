import { useMemo, useState } from 'react';
import { mapViewBox, nanhaiPath, nanhaiViewBox, provinceShapes } from './chinaMap';
import { EMPTY_TIER, PROVINCE_TIERS, buildProvinceLookup, tierOf } from './distribution';
import type { DistributionTier } from './distribution';
import type { TargetProvinceCount } from '../../types/api';

interface Props {
  provinces: TargetProvinceCount[];
  unknownCount: number;
  /** 分档表按指标各配一份：标的与买家的量级差一倍，共用一张表会让买家图全落最浅档。 */
  tiers?: DistributionTier[];
  /** 悬停提示与「未填省份」文案里的量词，标的是「个」、买家是「家」。 */
  unit?: string;
  unknownLabel?: string;
  /** 无障碍标签；两张图叠在一页时读屏要能区分。 */
  ariaLabel?: string;
}

const INSET_SCALE = 0.55;
const INSET_GAP = 10;

function sizeOf(viewBox: string): { width: number; height: number } {
  const [, , width, height] = viewBox.split(' ').map(Number);
  return { width, height };
}

/**
 * 省级分档地图，纯 SVG，无图表库。
 *
 * 路径来自 `chinaMap.ts`（scripts/build_china_map.py 离线生成），含台湾省；
 * 南海诸岛与九段线画在右下角插图框内——两者都是中国地图的必备要素。
 *
 * 插图不用绝对定位叠在地图上：主图的 viewBox 是按省界紧贴裁出来的，右下角
 * 正好是台湾，浮层会把它盖住。这里改为把画布向右扩出一块空白再放插图，
 * 谁也不压谁。
 */
export default function ChinaChoropleth({
  provinces,
  unknownCount,
  tiers = PROVINCE_TIERS,
  unit = '个',
  unknownLabel = '未填省份',
  ariaLabel = '省级分布地图，含台湾省与南海诸岛',
}: Props) {
  const [hovered, setHovered] = useState<{ name: string; count: number } | null>(null);

  const lookup = useMemo(
    () => buildProvinceLookup(provinces, provinceShapes.map((shape) => shape.name)),
    [provinces],
  );

  const shapes = useMemo(
    () =>
      provinceShapes.map((shape) => {
        const count = lookup.countOf(shape.name);
        return { ...shape, count, tier: tierOf(count, tiers) };
      }),
    [lookup, tiers],
  );

  const main = sizeOf(mapViewBox);
  const inset = sizeOf(nanhaiViewBox);
  const insetWidth = inset.width * INSET_SCALE;
  const insetHeight = inset.height * INSET_SCALE;
  const canvasWidth = main.width + INSET_GAP + insetWidth;
  const insetX = main.width + INSET_GAP;
  const insetY = main.height - insetHeight;

  return (
    // 地图独占一整行时不能让 SVG 铺满：中国地图接近方形，1400px 宽会按比例
    // 拉到一千多像素高。给「图 + 图例」这一整块一个居中的最大宽度，
    // 两侧留白就成了版面的一部分，而不是被硬压扁的图。
    <div className="mx-auto w-full max-w-[880px]">
      <div className="relative">
        <svg
          viewBox={`0 0 ${canvasWidth} ${main.height}`}
          className="block w-full"
          role="img"
          aria-label={ariaLabel}
          onMouseLeave={() => setHovered(null)}
        >
          {shapes.map((shape) => (
            <path
              key={shape.adcode}
              d={shape.d}
              fill={shape.tier.fill}
              stroke={shape.tier.stroke}
              strokeWidth={0.8}
              strokeLinejoin="round"
              fillRule="evenodd"
              className="transition-[filter] hover:brightness-95"
              onMouseEnter={() => setHovered({ name: shape.name, count: shape.count })}
            >
              <title>{`${shape.name} ${shape.count} ${unit}`}</title>
            </path>
          ))}

          <g transform={`translate(${insetX} ${insetY})`}>
            <rect
              x={-4}
              y={-4}
              width={insetWidth + 8}
              height={insetHeight + 8}
              fill="#FFFFFF"
              stroke="#9CA3AF"
              strokeWidth={1}
            />
            <g transform={`scale(${INSET_SCALE})`}>
              <path
                d={nanhaiPath}
                fill={EMPTY_TIER.fill}
                stroke="#6B7280"
                strokeWidth={2.4}
                strokeLinejoin="round"
                fillRule="evenodd"
              />
            </g>
            <text
              x={insetWidth / 2}
              y={insetHeight - 2}
              textAnchor="middle"
              className="fill-gray-400"
              style={{ fontSize: 11 }}
            >
              南海诸岛
            </text>
          </g>
        </svg>

        {hovered ? (
          <p className="pointer-events-none absolute left-0 top-0 bg-gray-900/85 px-2 py-1 text-xs text-white">
            {hovered.name} · {hovered.count} {unit}
          </p>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {[...tiers].reverse().concat(EMPTY_TIER).map((tier) => (
          <span key={tier.label} className="flex items-center gap-1.5 text-[11px] text-gray-500">
            <span
              className="inline-block h-2.5 w-4 border"
              style={{ backgroundColor: tier.fill, borderColor: tier.stroke }}
            />
            {tier.label}
          </span>
        ))}
        {unknownCount > 0 ? (
          <span className="text-[11px] text-gray-400">
            {unknownLabel} {unknownCount} {unit}
          </span>
        ) : null}
      </div>

      {lookup.unmatched.length > 0 ? (
        <p className="mt-2 text-[11px] text-gold-700">
          {lookup.unmatched.length} 个省份取值与底图对不上，未计入着色：
          {lookup.unmatched.map((item) => item.province).join('、')}
        </p>
      ) : null}
    </div>
  );
}
