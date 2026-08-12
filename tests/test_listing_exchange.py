"""上市地从「境内/境外」换成具体交易所之后，四条线必须一致。

判据见 平台优化方案/标的指标体系二轮施工单0807.md §1.3：旧枚举在生产里完全空转
（买家侧 44 个需求全 NULL，标的侧 16 个有值且全是 domestic），换枚举零数据损失。
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.app.api.routes.buyer_intents import ListingMarketRegion
from backend.app.jobs.handlers.common import _normalize_listing_market_region
from backend.app.registry.indicators import indicator_by_column
from backend.app.services.recommendation_conditions import _LISTING_MARKET_REGION_VALUES

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "database/migrations/016_indicator_system_round_two.sql"

EXCHANGES = {"sse", "szse", "bse", "hkex", "nyse", "nasdaq", "other", "unknown"}


def test_both_sides_share_one_closed_list() -> None:
    for entity in ("seller_target", "buyer_intent"):
        options = indicator_by_column(entity, "listing_market_region").enum_options or ()
        assert {value for value, _ in options} == EXCHANGES, f"{entity} 的上市地闭集不一致"
    # 买家 API 的 Literal 与对话条件契约都不能自己抄一份。
    assert set(ListingMarketRegion.__args__) == EXCHANGES
    assert _LISTING_MARKET_REGION_VALUES == EXCHANGES


def test_every_option_has_a_chinese_label() -> None:
    # 用户要求前端显示中文。标的信息页走注册表的 enum_options 出中文，
    # 所以标签缺失会直接显示成英文 value。
    options = indicator_by_column("seller_target", "listing_market_region").enum_options or ()
    for value, label in options:
        assert re.search(r"[一-鿿]", label), f"{value} 没有中文标签"


def test_stock_code_suffixes_decide_the_exchange() -> None:
    assert _normalize_listing_market_region("600519.SH") == "sse"
    assert _normalize_listing_market_region("002273.SZ") == "szse"
    assert _normalize_listing_market_region("430047.BJ") == "bse"
    assert _normalize_listing_market_region("00700.HK") == "hkex"


def test_chinese_exchange_names_are_recognized() -> None:
    assert _normalize_listing_market_region("上交所") == "sse"
    assert _normalize_listing_market_region("上海证券交易所科创板") == "sse"
    assert _normalize_listing_market_region("深圳证券交易所") == "szse"
    assert _normalize_listing_market_region("创业板") == "szse"
    assert _normalize_listing_market_region("北交所") == "bse"
    assert _normalize_listing_market_region("港股") == "hkex"
    assert _normalize_listing_market_region("纳斯达克") == "nasdaq"
    assert _normalize_listing_market_region("纽交所") == "nyse"
    assert _normalize_listing_market_region("其他交易所") == "other"


def test_ambiguous_and_legacy_wording_falls_to_unknown() -> None:
    """猜错比不知道更糟：买家的上市地要求是 eq 比较，猜错会把对的标的筛掉。

    「A股」跨三个交易所，「主板」跨两个，「境内/境外」是旧枚举的残留 ——
    它们都推不出唯一答案。
    """
    for wording in ("A股", "主板", "境内", "境外", "海外", "美股", "", None, "随便什么"):
        assert _normalize_listing_market_region(wording) == "unknown", wording


def test_migration_clears_values_that_cannot_be_upgraded() -> None:
    """domestic 反推不出交易所，只能置空；但股票代码后缀能推的必须推。

    这段推导是迁移里唯一保住数据的地方，删掉它 16 行全部变 NULL。
    """
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "update buyer_intent" in sql and "listing_market_region = null" in sql
    for suffix, code in (("%.SH", "sse"), ("%.SZ", "szse"), ("%.BJ", "bse"), ("%.HK", "hkex")):
        assert f"like '{suffix}' then '{code}'" in sql, f"{suffix} 的推导丢了"
    # 新约束必须两侧都重建，否则一侧写入会被 DB 拒。
    assert sql.count("chk_seller_target_listing_market_region") == 2
    assert sql.count("chk_buyer_intent_listing_market_region") == 2
