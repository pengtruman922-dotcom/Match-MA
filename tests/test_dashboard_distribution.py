"""数据看板取数与底图的守护。

看板是**存量画像**：全库、不分交易状态、不按负责人过滤，且只输出计数。
这三条都是刻意的，也都是一次「顺手对齐其它端点」的重构就能悄悄改掉的，
所以在这里钉死。底图那部分盯的是「台湾省与南海诸岛不能掉」。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from backend.app.api.routes import stats as stats_route
from backend.app.main import app

REPO = Path(__file__).resolve().parents[1]
FEATURES = REPO / "frontend/src/features/dashboard"
MAP_MODULE = FEATURES / "chinaMap.ts"
CHOROPLETH = FEATURES / "ChinaChoropleth.tsx"
DASHBOARD_PAGE = REPO / "frontend/src/pages/Dashboard.tsx"

# 34 个省级行政区。少一个就是底图被换成了不合规的版本。
EXPECTED_PROVINCES = {
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省",
    "黑龙江省", "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省",
    "山东省", "河南省", "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省",
    "重庆市", "四川省", "贵州省", "云南省", "西藏自治区", "陕西省", "甘肃省",
    "青海省", "宁夏回族自治区", "新疆维吾尔自治区", "台湾省",
    "香港特别行政区", "澳门特别行政区",
}


def _source() -> str:
    return Path(stats_route.__file__).read_text(encoding="utf-8")


def _sql_only(source: str) -> str:
    """去掉文档字符串与注释，只留会真正执行的代码。

    不能用正则扒三引号——SQL 本身就写在 ``text(\"\"\"…\"\"\")`` 里，一起被扒掉
    就等于什么都没在检查（本文件第一版就是这么假绿的）。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            docstring = ast.get_docstring(node, clean=False)
            if docstring:
                source = source.replace(docstring, "")
    return re.sub(r"#[^\n]*", "", source)


def test_overview_endpoint_is_registered() -> None:
    """走 openapi 而不是 app.routes —— 这个 FastAPI 版本把 include_router 的结果
    包成 _IncludedRouter，路径要到生成 schema 时才展开，读 .routes 只会拿到 None。"""
    assert "/api/v1/stats/overview" in app.openapi()["paths"]


def test_overview_is_not_owner_scoped() -> None:
    """按负责人过滤会让大屏上每个人看到的图不一样，看板就不再是同一张盘子。"""
    code = _sql_only(_source())

    assert "owner_user_id" not in code
    assert "scope_user_id" not in code
    assert "owner_scope" not in code


def test_overview_counts_every_lifecycle_status() -> None:
    """已售出与已停售同样是存量的一部分；只留在售会让历史盘子凭空缩水。"""
    code = _sql_only(_source())

    assert "lifecycle_status" not in code
    assert "status = 'active'" not in code
    # 软删除仍然要排除——那是删掉的数据，不是卖掉的标的。
    # 六段查询：标的合计 / 标的省份 / 标的行业 / 营收分档 / 买家合计 / 买家省份。
    assert code.count("deleted_at is null") == 6


def test_overview_returns_counts_only() -> None:
    """看板会当着客户的面打开，任何名称都不能出现在响应里。"""
    code = _sql_only(_source())

    for column in ("target_name", "target_subject_name", "buyer_name", "intent_name"):
        assert column not in code

    selected = (
        set(re.findall(r'row\["(\w+)"\]', code))
        | set(re.findall(r'totals\["(\w+)"\]', code))
        | set(re.findall(r'buyer_totals\["(\w+)"\]', code))
    )
    assert selected == {
        "province", "l2", "count", "total", "province_unknown", "industry_unknown",
        "generated_at", "revenue_unknown", "bucket_index",
    }


def test_revenue_buckets_have_a_single_definition() -> None:
    """CASE 由 REVENUE_BUCKETS 生成：档位边界和中文名不能各存一份。"""
    case_sql = stats_route._revenue_bucket_case()

    uppers = [upper for _, _, upper in stats_route.REVENUE_BUCKETS if upper is not None]
    assert len(uppers) == len(stats_route.REVENUE_BUCKETS) - 1, "只有最后一档无上界"
    assert uppers == sorted(uppers), "档位上界必须递增"
    for index, upper in enumerate(uppers):
        assert f"when current_revenue_yuan < {upper} then {index}" in case_sql
    assert case_sql.endswith(f"else {len(stats_route.REVENUE_BUCKETS) - 1} end")


def test_empty_revenue_buckets_are_still_reported() -> None:
    """计数为 0 的档位必须出现：条形图缺一行会被读成「这一档不存在」。"""
    code = _sql_only(_source())

    assert "counted_buckets.get(index, 0)" in code


def test_industry_top_list_declares_what_it_left_out() -> None:
    """只画前 N 名时必须报出榜外数量，否则 top 10 会被当成全部。"""
    code = _sql_only(_source())

    assert "[:INDUSTRY_TOP_N]" in code
    assert "industry_other_count" in code
    assert stats_route.INDUSTRY_TOP_N > 0


def test_industry_is_counted_by_l2_per_target() -> None:
    """按二级行业统计，且一个标的在同一 L2 下重复出现只算一次。

    看板取 L2 而不是 L1：一级行业太粗，「制造与工业 20 个」读不出赛道。
    """
    code = _sql_only(_source())

    assert "pair ->> 'l2'" in code
    assert "select distinct" in code
    assert "seller_target.id as target_id" in code
    # L1 不再出现在取数里，只剩 L2。
    assert "'l1'" not in code


def test_buyer_province_panel_reads_the_party_location() -> None:
    """买家地图画的是买家主体所在地。

    买家意向的 `region_scope_summary`（想买哪里）是自由文本——生产样本形如
    「优先考虑长三角、珠三角区域具备扩产潜力的项目」——上不了地图；这里明确
    只用 buyer_party.region_province，避免以后被误当成需求地域图。
    """
    code = _sql_only(_source())

    assert "from buyer_party" in code
    assert "region_province" in code
    assert "region_scope_summary" not in code


def test_buyer_map_has_its_own_tier_table() -> None:
    """买家主体量级只有标的的一半，套标的阈值会让整张图全落最浅一档。"""
    source = (FEATURES / "distribution.ts").read_text(encoding="utf-8")
    page = DASHBOARD_PAGE.read_text(encoding="utf-8")

    assert "BUYER_PROVINCE_TIERS" in source
    assert "tiers={BUYER_PROVINCE_TIERS}" in page


def test_page_shows_two_maps_and_two_bar_panels() -> None:
    """2026-07-29 讨论后的版面：两张地图各占一行，两块条形图并排。"""
    source = DASHBOARD_PAGE.read_text(encoding="utf-8")

    for title in ("标的省级分布", "买家省级分布", "标的行业分布 top", "标的营收规模"):
        assert f'title="{title}"' in source
    # 讨论中明确去掉的三块
    assert "省份排行" not in source
    assert "供需" not in source
    assert "撮合关系状态" not in source
    assert "更新于" in source, "只保留更新时间，其余说明文字不上大屏"


def test_industry_panel_admits_the_dictionary_is_not_deduplicated() -> None:
    """二级行业字典里「食品 / 食品制造 / 食品加工」尚未合并，同一赛道会分散在多行。

    生产数据里这已经在发生（食品类 6 个标的散成 4 行），榜单因此是偏的。
    在页面上说出来，比让人以为 top 榜是准的强。去重工单见拆除验收单 §1.3。
    """
    source = DASHBOARD_PAGE.read_text(encoding="utf-8")

    assert "同义词未合并" in source


def test_map_carries_every_province_including_taiwan() -> None:
    source = MAP_MODULE.read_text(encoding="utf-8")
    names = set(re.findall(r"name: '([^']+)'", source))

    assert names == EXPECTED_PROVINCES
    assert "台湾省" in names


def test_map_carries_the_south_china_sea_inset() -> None:
    """南海诸岛与九段线是中国地图的必备要素，插图框不能是空路径。"""
    source = MAP_MODULE.read_text(encoding="utf-8")
    nanhai = re.search(r"nanhaiPath = '([^']*)'", source)

    assert nanhai is not None
    assert len(nanhai.group(1)) > 1000

    choropleth = CHOROPLETH.read_text(encoding="utf-8")
    assert "nanhaiPath" in choropleth
    assert "南海诸岛" in choropleth


def test_map_paths_are_well_formed_and_bounded() -> None:
    """每条 path 都必须闭合，且落在 viewBox 内——投影写错时这里先炸。"""
    source = MAP_MODULE.read_text(encoding="utf-8")
    view_box = re.search(r"mapViewBox = '0 0 ([\d.]+) ([\d.]+)'", source)
    assert view_box is not None
    width, height = float(view_box.group(1)), float(view_box.group(2))

    for name, path in re.findall(r"name: '([^']+)', d: '([^']+)'", source):
        assert path.startswith("M"), name
        assert path.endswith("Z"), name
        points = [
            (float(x), float(y)) for x, y in re.findall(r"[ML](-?[\d.]+) (-?[\d.]+)", path)
        ]
        assert points, name
        assert all(0 <= x <= width and 0 <= y <= height for x, y in points), name


def test_map_module_is_generated_not_hand_edited() -> None:
    header = MAP_MODULE.read_text(encoding="utf-8")[:400]

    assert "scripts/build_china_map.py" in header
    assert (REPO / "scripts/build_china_map.py").exists()


def test_dashboard_loads_the_basemap_lazily() -> None:
    """底图约 130 KB，只有这一页用；打进主包会让每个页面都陪着下载。"""
    source = DASHBOARD_PAGE.read_text(encoding="utf-8")

    assert "lazy(() => import('../features/dashboard/ChinaChoropleth'))" in source
    assert "Suspense" in source


def test_dashboard_shows_no_entity_names() -> None:
    source = DASHBOARD_PAGE.read_text(encoding="utf-8") + CHOROPLETH.read_text(encoding="utf-8")

    for token in ("target_name", "buyer_name", "intent_name", "sellerTargets", "buyerIntents"):
        assert token not in source
