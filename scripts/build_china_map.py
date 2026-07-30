"""Turn a province GeoJSON into the SVG paths the dashboard map renders.

Run offline and commit the output; the frontend never parses GeoJSON at
runtime.  Doing the projection and simplification here is what lets the map
ship without a charting library: the browser only ever sees ~34 `<path d>`
strings.

    python scripts/build_china_map.py <china_provinces.geojson>

Source of the input: DataV.GeoAtlas full province boundary
(`https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json`), which carries
Taiwan and the South China Sea islands — both are required on any map of China
published here, so neither is optional and neither may be dropped to save size.

The South China Sea features go into a separate inset path (the conventional
bottom-right box) rather than the main extent: drawn inline they stretch the
map to twice its height and shrink the mainland provinces the dashboard is
actually about.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# Albers equal-area conic, the standard projection for national maps of China.
# Equal-area matters here: the map is a choropleth, so a projection that
# inflates the northern provinces would visually inflate their share too.
LON_0 = 105.0
LAT_0 = 35.0
PHI_1 = 25.0
PHI_2 = 47.0

# Rings entirely below this latitude belong to the inset. The Hainan mainland
# island starts at 18.1°N and Sansha's islands all sit below 17°N, so this
# splits one province's geometry across the two boxes without a name list.
INSET_MAX_LAT = 17.8

MAIN_SIZE = 1000.0
INSET_HEIGHT = 300.0
# Douglas-Peucker tolerance in output units. 0.35 keeps every province outline
# recognisable at the sizes the panel renders while dropping ~75% of vertices.
TOLERANCE = 0.35
DECIMALS = 1

_N = (math.sin(math.radians(PHI_1)) + math.sin(math.radians(PHI_2))) / 2
_C = math.cos(math.radians(PHI_1)) ** 2 + 2 * _N * math.sin(math.radians(PHI_1))
_RHO_0 = math.sqrt(_C - 2 * _N * math.sin(math.radians(LAT_0))) / _N


def project(lon: float, lat: float) -> tuple[float, float]:
    theta = _N * math.radians(lon - LON_0)
    rho = math.sqrt(_C - 2 * _N * math.sin(math.radians(lat))) / _N
    return rho * math.sin(theta), _RHO_0 - rho * math.cos(theta)


def rings_of(geometry: dict) -> list[list[list[float]]]:
    """Flatten Polygon/MultiPolygon into rings, holes included.

    Holes are kept and the paths are rendered with `fill-rule: evenodd`;
    dropping them would paint Beijing and Tianjin over with Hebei's colour.
    """
    kind = geometry["type"]
    coordinates = geometry["coordinates"]
    if kind == "Polygon":
        return list(coordinates)
    if kind == "MultiPolygon":
        return [ring for polygon in coordinates for ring in polygon]
    raise ValueError(f"unsupported geometry {kind}")


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative so a long coastline cannot blow the stack."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        ax, ay = points[start]
        bx, by = points[end]
        dx, dy = bx - ax, by - ay
        span = math.hypot(dx, dy)
        best_index, best_distance = -1, tolerance
        for index in range(start + 1, end):
            px, py = points[index]
            if span == 0:
                distance = math.hypot(px - ax, py - ay)
            else:
                distance = abs(dy * px - dx * py + bx * ay - by * ax) / span
            if distance > best_distance:
                best_index, best_distance = index, distance
        if best_index != -1:
            keep[best_index] = True
            stack.append((start, best_index))
            stack.append((best_index, end))
    return [point for point, kept in zip(points, keep) if kept]


def to_path(rings: list[list[tuple[float, float]]]) -> str:
    parts: list[str] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        commands = [f"M{ring[0][0]:.{DECIMALS}f} {ring[0][1]:.{DECIMALS}f}"]
        commands.extend(f"L{x:.{DECIMALS}f} {y:.{DECIMALS}f}" for x, y in ring[1:])
        parts.append("".join(commands) + "Z")
    return "".join(parts)


def fit(
    groups: list[list[list[tuple[float, float]]]],
    *,
    height: float,
) -> tuple[list[list[list[tuple[float, float]]]], float, float]:
    flat = [point for group in groups for ring in group for point in ring]
    min_x = min(x for x, _ in flat)
    max_x = max(x for x, _ in flat)
    min_y = min(y for _, y in flat)
    max_y = max(y for _, y in flat)
    scale = height / (max_y - min_y)
    width = (max_x - min_x) * scale
    # Projected y grows northward; SVG y grows downward, hence the flip.
    placed = [
        [[((x - min_x) * scale, (max_y - y) * scale) for x, y in ring] for ring in group]
        for group in groups
    ]
    return placed, width, height


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    source = json.loads(Path(argv[1]).read_text(encoding="utf-8"))

    main_groups: list[list[list[tuple[float, float]]]] = []
    names: list[tuple[str, str]] = []
    inset_rings: list[list[tuple[float, float]]] = []

    for feature in source["features"]:
        name = str(feature["properties"].get("name") or "").strip()
        adcode = str(feature["properties"].get("adcode") or "")
        province_rings: list[list[tuple[float, float]]] = []
        for ring in rings_of(feature["geometry"]):
            projected = [project(float(point[0]), float(point[1])) for point in ring]
            if max(point[1] for point in ring) < INSET_MAX_LAT or not name:
                inset_rings.append(projected)
            else:
                province_rings.append(projected)
        if province_rings:
            main_groups.append(province_rings)
            names.append((adcode, name))

    main_placed, main_width, main_height = fit(main_groups, height=MAIN_SIZE * 0.62)
    inset_placed, inset_width, inset_height = fit([inset_rings], height=INSET_HEIGHT)

    provinces = []
    for (adcode, name), rings in zip(names, main_placed):
        path = to_path([simplify(ring, TOLERANCE) for ring in rings])
        provinces.append((adcode, name, path))

    inset_path = to_path([simplify(ring, TOLERANCE * 0.5) for ring in inset_placed[0]])

    lines = [
        "// 由 scripts/build_china_map.py 从 DataV.GeoAtlas 省级边界生成，请勿手改。",
        "// 重新生成：python scripts/build_china_map.py <china_provinces.geojson>",
        "//",
        "// 含台湾省与南海诸岛（九段线在 nanhaiPath，按惯例画在右下角插图框内）。",
        "",
        "export interface ProvinceShape {",
        "  /** 行政区划代码，与省名一起用于匹配后端返回的省份统计。 */",
        "  adcode: string;",
        "  name: string;",
        "  d: string;",
        "}",
        "",
        f"export const mapViewBox = '0 0 {main_width:.1f} {main_height:.1f}';",
        f"export const nanhaiViewBox = '0 0 {inset_width:.1f} {inset_height:.1f}';",
        "",
        "export const provinceShapes: ProvinceShape[] = [",
    ]
    for adcode, name, path in provinces:
        lines.append(f"  {{ adcode: '{adcode}', name: '{name}', d: '{path}' }},")
    lines.append("];")
    lines.append("")
    lines.append(f"export const nanhaiPath = '{inset_path}';")
    lines.append("")

    output = Path("frontend/src/features/dashboard/chinaMap.ts")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    total = sum(len(path) for _, _, path in provinces) + len(inset_path)
    print(f"{output}: {len(provinces)} provinces, path data {total / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
