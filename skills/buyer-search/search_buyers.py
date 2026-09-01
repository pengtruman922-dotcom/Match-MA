"""买家检索 —— 为一个标的找可能的买家，供 wegent 等外部 Agent 调用。

设计要点（改动前先读）：

1. **业务匹配不走结构化字段，走全量文本 + LLM 判断。** 买家库规模足够小
   （2026-08-27 实测 42 个主体 / 52 条需求，预期长到 200），业务卡片按数据齐全
   的那几条算约 600 字/条，200 个买家约 12 万字 ≈ 90k token，一次调用装得下。
   这是整个方案成立的唯一前提，其余判决都从它推导。
   所以接口一**没有行业/关键词参数** —— 那不是遗漏，是设计。

2. **空值方向和正向是反的，这是最容易写错的一处。**
   正向筛选里「买家没提这条」= 不带这个条件、天然无害。
   反向筛选里如果把 NULL 当成「不满足」，一半以上的买家会当场消失。
   所以接口三的每一条数值/枚举条件都是「字段为空 或 条件成立」，
   并且返回里如实区分「明确符合」与「买家没提过」—— 这是两个结论。

3. **省略空字段时，两类缺失含义相反。** 买家自身的事实（业务说明、市值、营收）
   缺失 = 没录、未知；买家需求的门槛（最低营收、可接受地区）缺失 =
   买家没提这个门槛 = **不构成障碍**，是正面信号。
   返回结构把两者分成 `买家信息` 与 `收购需求` 两个块，就是为了让这个区分
   在数据形状上成立，而不是只写在文档里。

4. **联系人三件套与运营备注永不返回。** contact_name / contact_info_json /
   our_contact_name 只能来自非公开渠道；notes 是运营备注，注册表明确标了
   「不进任何推荐上下文」。这一条是业务规则，不是可配置项。

5. **同名主体是真实数据。** 「北大健康」在生产库里有 3 个主体 / 4 条需求。
   按名称召回时返回全部候选让调用方消歧，不合并、不只取第一个。

6. **凭证优先用专用账号换 JWT，不要用静态管理员令牌。** 后者不过期、权限全开、
   还是登录系统的恢复通道，不该发进外部运行环境。优先级见 README。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API_BASE = "https://match-ma-production.up.railway.app/api/v1"

# 闸门。**这是第六处独立实现**（总纲 §2.4 记着另外五处），与标的侧 skill 一样
# 是过渡实现：闸门最终应该回到服务端。漏改一处不报错，表现是「E 级的还在被推荐」。
EXCLUDED_INTENT_GRADE = "E"
EXCLUDED_INTENT_STATUS = "closed"
REQUIRED_PARTY_STATUS = "active"

# 一次拉全库要翻几页。上游 limit 上限 200。
PAGE_SIZE = 200
MAX_PAGES = 10

# 接口三的硬上限。超出时返回命中总数并提示收窄，**不静默截断** ——
# 静默截断会让调用方以为「库里就这么多」，而实际是被砍掉的那批里有该推的。
FILTER_RESULT_LIMIT = 50

# brief 模式的截断长度。full 约 600 字/买家，brief 约 280 字/买家。
BRIEF_BUSINESS_CHARS = 120
BRIEF_INTENT_CHARS = 80

OWNERSHIP_LABELS = {"state_owned": "国企", "private": "私企", "foreign": "外企", "other": "其他"}
LISTED_LABELS = {"listed": "已上市", "unlisted": "未上市", "pre_ipo": "拟上市"}
EXCHANGE_LABELS = {
    "sse": "上交所", "szse": "深交所", "bse": "北交所",
    "hkex": "港交所", "nyse": "纽交所", "nasdaq": "纳斯达克", "other": "其他",
}
CAPABILITY_LABELS = {"yes": "是", "no": "否", "likely": "可能"}
TRANSACTION_LABELS = {
    "equity_transfer": "股权转让（老股）", "capital_increase": "增资扩股（新股）",
    "asset_purchase": "资产收购", "merger": "吸收合并", "other": "其他",
}
RISK_LABELS = {
    "litigation": "涉诉", "equity_frozen": "股权冻结",
    "enforcement": "被执行", "violation": "违规违法",
}
INTENT_STATUS_LABELS = {"active": "持续推荐", "paused": "暂停推荐"}

# `unknown` 不是 `null`，但判「这个字段有没有值」时两者必须等价 ——
# 多个枚举列在 DDL 里是 `not null default 'unknown'`。
EMPTY_TOKENS = {"", "unknown", "none", "null"}

# 零宽字符。生产里有一条记录名字带零宽不连字（`‌广州电缆有限公司…`），
# 精确名称匹配会**静默失败** —— 匹配前必须先洗掉。
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")

# 解析指令原文与重复附件段落的清洗。实测最长一条 raw_requirement_text 有 3746 字，
# 其中约 2000 字是同一附件出现两遍 —— 不清洗的话 50 条全量档会撑到 22 万字符。
_PARSE_INSTRUCTION = re.compile(
    r"(解析要求|提取要求|输出要求|请按以下|以下为附件内容|附件内容如下)[：:][^\n]*\n?",
)

_TOKEN_CACHE = Path(tempfile.gettempdir()) / "match_ma_buyer_skill_token.json"


# -- 凭证 -----------------------------------------------------------------


def _api_base() -> str:
    return os.environ.get("MATCH_MA_API_BASE", DEFAULT_API_BASE).rstrip("/")


def _auth_file_candidates() -> list[Path]:
    """按优先级列出凭证文件的查找位置。

    显式路径必须排第一：仓库相对回退只在本仓库布局下成立，把 skill 拷进别的
    沙箱之后它会指向一个不存在的目录，然后报成「没有凭证」——而真实原因是
    「找错地方了」。所以诊断里必须把找过哪些路径原样打出来。

    脚本同目录的 `auth.local.json` 排在第二位，是为了 wegent 这类**不能注入环境
    变量、沙箱又是临时的**的运行环境：那里唯一的持久存储就是 skill 目录本身。
    该文件里应当放**登录换来的 7 天 JWT，不要放账号密码**。用 `--issue-token` 生成。
    """
    candidates: list[Path] = []
    explicit = os.environ.get("MATCH_MA_AUTH_FILE")
    if explicit:
        candidates.append(Path(explicit))
    here = Path(__file__).resolve().parent
    candidates.append(here / "auth.local.json")
    candidates.append(here / ".match-ma-local-auth.json")
    candidates.append(Path.home() / ".match-ma-local-auth.json")
    candidates.append(Path.cwd() / ".match-ma-local-auth.json")
    candidates.append(Path(__file__).resolve().parents[2] / ".match-ma-local-auth.json")
    return candidates


def _read_auth_file() -> str | None:
    for path in _auth_file_candidates():
        try:
            if not path.is_file():
                continue
            token = json.loads(path.read_text(encoding="utf-8-sig")).get("token")
        except (OSError, ValueError):
            continue
        if token:
            return str(token).strip()
    return None


def _login(username: str, password: str) -> str:
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        _api_base() + "/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        token = str(json.loads(response.read())["access_token"])
    try:
        _TOKEN_CACHE.write_text(json.dumps({"token": token}), encoding="utf-8")
        os.chmod(_TOKEN_CACHE, 0o600)
    except OSError:
        pass  # 缓存失败不影响本次调用
    return token


def _token(*, force_refresh: bool = False) -> str:
    username = os.environ.get("MATCH_MA_USERNAME")
    password = os.environ.get("MATCH_MA_PASSWORD")
    if username and password:
        if not force_refresh:
            try:
                cached = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8")).get("token")
                if cached:
                    return str(cached)
            except (OSError, ValueError):
                pass
        return _login(username, password)

    static = os.environ.get("MATCH_MA_TOKEN")
    if static:
        return static.strip()

    file_token = _read_auth_file()
    if file_token:
        return file_token

    raise RuntimeError(
        "缺少凭证：请设置 MATCH_MA_USERNAME + MATCH_MA_PASSWORD（推荐，专用账号换 7 天 JWT，"
        "可单独停用），或 MATCH_MA_AUTH_FILE 指向凭证文件，或 MATCH_MA_TOKEN。"
        "运行 `python search_buyers.py --check` 可看已查找过的全部路径与完整诊断。"
    )


def _get(path: str, token: str, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(_api_base() + path, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 401:
            # 缓存的 JWT 过期是最常见的 401。这里如实抛出，由调用方决定是否重登；
            # 绝不能吞掉返回空列表 —— 那会被上游模型读成「库里没有这类买家」。
            raise PermissionError("买家库返回 401：凭证无效或已过期。") from error
        raise


def _get_all(path: str, token: str) -> list[dict[str, Any]]:
    """翻页取全量。上游 limit 上限 200，库规模下最多两三页。"""
    items: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        separator = "&" if "?" in path else "?"
        query = f"{path}{separator}limit={PAGE_SIZE}&offset={page * PAGE_SIZE}"
        try:
            payload = _get(query, token)
        except PermissionError:
            token = _token(force_refresh=True)  # 缓存的 JWT 过期，重登一次
            payload = _get(query, token)
        batch = payload.get("items") or []
        items.extend(batch)
        if len(batch) < PAGE_SIZE or len(items) >= int(payload.get("total") or 0):
            break
    return items


# -- 取值工具 -------------------------------------------------------------


def _clean(value: Any) -> str:
    return _ZERO_WIDTH.sub("", str(value or "")).strip()


def _blank(value: Any) -> bool:
    """空值判定。`unknown` 与 `null` 等价 —— 多个枚举列是 not null default 'unknown'。"""
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return not value
    return _clean(value).lower() in EMPTY_TOKENS


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    """丢掉空字段。实测省 21%~33% 体积。

    ⚠️ 这么做的前提是调用方知道「字段不存在」是什么意思，而**买家自身的事实**
    与**买家需求的门槛**含义正相反（见模块 docstring 第 3 条）。返回结构把两者
    分在 `买家信息` / `收购需求` 两个块里，这个区分才成立。
    """
    return {key: value for key, value in payload.items() if not _blank(value)}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str | None:
    """元 → 人读得懂的中文金额。模型不需要 12 位数字，需要量级。"""
    amount = _number(value)
    if amount is None:
        return None
    if abs(amount) >= 1e8:
        return f"{amount / 1e8:.2f}".rstrip("0").rstrip(".") + "亿"
    if abs(amount) >= 1e4:
        return f"{amount / 1e4:.0f}万"
    return f"{amount:.0f}元"


def _ratio(value: Any) -> str | None:
    number = _number(value)
    return None if number is None else f"{number:g}"


def _labels(values: Any, table: dict[str, str]) -> str | None:
    if not isinstance(values, list):
        return None
    named = [table.get(str(item), str(item)) for item in values if not _blank(item)]
    return "、".join(named) or None


def _region_text(regions: Any) -> str | None:
    """`[{province, city, district}]` → 「广东省、江苏省苏州市」。

    只拼**填到的**层级：补全成三级会让「只说了江苏省」看起来像「江苏省某个
    具体的市」，而模型会照着这个错的粒度判。
    """
    if not isinstance(regions, list) or not regions:
        return None
    parts: list[str] = []
    for item in regions:
        if not isinstance(item, dict):
            continue
        levels = [_clean(item.get(key)) for key in ("province", "city", "district")]
        # 直辖市的省与市同名，直接拼会变成「北京市北京市」。
        label = "".join(dict.fromkeys(level for level in levels if level))
        if label and label not in parts:
            parts.append(label)
    return "、".join(parts) or None


def _truncate(value: Any, limit: int) -> str | None:
    text = _clean(value)
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def _clean_requirement_text(value: Any, limit: int = 1200) -> str | None:
    """原始需求正文的清洗：去解析指令、去重复段落、限长。

    实测最长一条 3746 字，其中约 2000 字是同一附件出现了两遍。不清洗的话
    50 条全量档约 22 万字符 —— 光这一列就占掉大半。
    """
    text = _clean(value)
    if not text:
        return None
    text = _PARSE_INSTRUCTION.sub("", text)
    # 按空行分段去重：重复的附件 OCR 就是整段重复出现。
    seen: set[str] = set()
    kept: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        normalized = re.sub(r"\s+", "", block)
        if len(normalized) < 8:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        kept.append(block.strip())
    joined = "\n\n".join(kept).strip()
    if not joined:
        return None
    return joined if len(joined) <= limit else joined[:limit] + "…（已截断）"


# -- 闸门与索引 -----------------------------------------------------------


def _live_parties(parties: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(party.get("id")): party
        for party in parties
        if str(party.get("status") or "") == REQUIRED_PARTY_STATUS
    }


def _live_intents(intents: list[dict[str, Any]], parties: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """过闸门：E 级不进、结束推荐不进、主体非 active 不进。

    `paused`（暂停推荐）**保留但标注** —— 顾问要知道这条需求还在，只是暂时停了。
    """
    kept: list[dict[str, Any]] = []
    for intent in intents:
        if str(intent.get("intent_grade") or "") == EXCLUDED_INTENT_GRADE:
            continue
        if str(intent.get("status") or "") == EXCLUDED_INTENT_STATUS:
            continue
        if str(intent.get("buyer_party_id") or "") not in parties:
            continue
        kept.append(intent)
    return kept


def _load(token: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    parties = _live_parties(_get_all("/buyer-parties", token))
    intents = _live_intents(_get_all("/buyer-intents", token), parties)
    return parties, intents


# -- 三种返回形状 ---------------------------------------------------------


def _scenarios(intent: dict[str, Any]) -> list[dict[str, Any]]:
    """一条需求的全部方案。**业务方向与门槛只住在这里。**

    2026-09-01 之前 skill 完全不读方案，只读 buyer_intent 那一行。后果不是报错：
    生产里 8 条需求有分档，其中 2 条的门槛**只存在于方案里** —— 对它们这个
    工具会返回「这条需求没有提出任何硬门槛，不构成障碍」，把有门槛的买家报成
    库里最灵活的买家。错的方向恰好是最贵的那一边。
    """
    rows = intent.get("scenarios_json")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _scenario_label(index: int, total: int) -> str:
    """方案 0901 起没有名称（摘要就是标题），抬头用序号。

    单方案时不提「方案」二字：40/48 条需求只有一个方案，给它套一层分档的说法
    会让调用方以为还有别的档没给它看。
    """
    return "需求" if total <= 1 else f"方案 {index + 1}"


def _party_business(party: dict[str, Any], *, brief: bool) -> dict[str, Any]:
    """买家主体的【召】类字段：判业务匹配的核心材料。"""
    summary = party.get("business_summary")
    return _compact({
        "买家名称": _clean(party.get("buyer_name")),
        "业务标签": _labels(party.get("business_tags_json"), {}),
        "业务说明": _truncate(summary, BRIEF_BUSINESS_CHARS) if brief else _clean(summary),
    })


def _intent_business(intent: dict[str, Any], *, brief: bool) -> dict[str, Any]:
    """需求的【召】类字段：逐方案的自由文本，业务匹配全靠它们。"""
    scenarios = _scenarios(intent)
    payload: dict[str, Any] = _compact({"需求名称": _clean(intent.get("intent_name"))})
    blocks = []
    for index, scenario in enumerate(scenarios):
        summary = scenario.get("scenario_summary")
        blocks.append(_compact({
            "档": _scenario_label(index, len(scenarios)) if len(scenarios) > 1 else None,
            "业务标签": _labels(scenario.get("business_tags_json"), {}),
            "要买什么业务": _truncate(summary, BRIEF_INTENT_CHARS) if brief else _clean(summary),
            "排除方向": _clean(scenario.get("excluded_business_text")),
        }))
    blocks = [block for block in blocks if block]
    if len(blocks) == 1:
        payload.update(blocks[0])
    elif blocks:
        payload["方案"] = blocks
        payload["方案说明"] = "满足任意一个方案即算命中这条需求，逐个读、逐个判。"
    if str(intent.get("status") or "") == "paused":
        payload["状态"] = "暂停推荐（仍在库里，推荐前先跟顾问确认）"
    return payload


def _party_full(party: dict[str, Any]) -> dict[str, Any]:
    """买家主体全量。**联系人三件套与运营备注在这里被永久排除。**"""
    listed = str(party.get("listed_status") or "")
    # 市值与估值是一个展示位：上市看市值，未上市/拟上市看估值，unknown 有哪个显示哪个。
    money: dict[str, Any] = {}
    if listed == "listed" or not _blank(party.get("market_cap_yuan")):
        money["市值"] = _money(party.get("market_cap_yuan"))
        money["市值日期"] = _clean(party.get("market_cap_as_of"))
    if listed != "listed" or not _blank(party.get("valuation_yuan")):
        money["估值"] = _money(party.get("valuation_yuan"))
        money["估值时点"] = _clean(party.get("valuation_date"))
    return _compact({
        "id": str(party.get("id") or ""),
        "买家名称": _clean(party.get("buyer_name")),
        "曾用名与别名": _labels(party.get("aliases_json"), {}),
        "企业性质": OWNERSHIP_LABELS.get(str(party.get("ownership_type") or "")),
        "上市状态": LISTED_LABELS.get(listed),
        "上市地": EXCHANGE_LABELS.get(str(party.get("listing_exchange") or "")),
        "股票代码": _clean(party.get("stock_code")),
        "所在地": _region_text([{
            "province": party.get("location_province"),
            "city": party.get("location_city"),
            "district": party.get("location_district"),
        }]),
        "业务标签": _labels(party.get("business_tags_json"), {}),
        "业务说明": _clean(party.get("business_summary")),
        **_compact(money),
        "营收": _money(party.get("current_revenue_yuan")),
        "经营现金流": _money(party.get("current_operating_cash_flow_yuan")),
        "财务期间": _clean(party.get("financial_period_label")),
        "补充信息": _clean(party.get("supplementary_summary")),
    })


def _scenario_thresholds(scenario: dict[str, Any]) -> dict[str, Any]:
    return _compact({
        "最低营收": _money(scenario.get("min_revenue_yuan")),
        "最低净利润": _money(scenario.get("min_net_profit_yuan")),
        "PE 上限": _ratio(scenario.get("max_pe")),
        "估值下限": _money(scenario.get("min_valuation_yuan")),
        "估值上限": _money(scenario.get("max_valuation_yuan")),
        "市值下限": _money(scenario.get("min_market_cap_yuan")),
        "市值上限": _money(scenario.get("max_market_cap_yuan")),
        "上市状态": _labels(scenario.get("acceptable_listed_status_json"), LISTED_LABELS),
        "要求地区": _region_text(scenario.get("required_regions_json")),
    })


def _scenario_full(scenario: dict[str, Any], index: int, total: int) -> dict[str, Any]:
    """一个方案的完整档：业务方向与门槛**分成两块**，因为两者的缺失含义相反。"""
    thresholds = _scenario_thresholds(scenario)
    payload = _compact({
        "档": _scenario_label(index, total) if total > 1 else None,
        "业务方向": _compact({
            "业务标签": _labels(scenario.get("business_tags_json"), {}),
            "要买什么业务": _clean(scenario.get("scenario_summary")),
            "排除方向": _clean(scenario.get("excluded_business_text")),
        }),
        "门槛": thresholds,
        "其他要求": _clean(scenario.get("other_requirements_text")),
    })
    if not thresholds:
        # 一个门槛都没提 ≠ 信息不足。它是**最灵活的那批方案**，恰恰最该推。
        payload["门槛说明"] = "这个方案没有提出任何硬门槛，不构成障碍。"
    return payload


def _intent_full(intent: dict[str, Any]) -> dict[str, Any]:
    """需求全量档 = 容器信息 + 1..N 个各自完整的方案。

    0901 起需求本身只是容器（名称、级别、状态），业务方向与门槛全部住在方案里。
    「门槛整块为空 = 最灵活的买家」这条语义没变，但判定要看**全部方案都空**才算数
    —— 这正是 skill 不读方案时那个 bug 的成因。
    """
    scenarios = _scenarios(intent)
    blocks = [_scenario_full(scenario, index, len(scenarios)) for index, scenario in enumerate(scenarios)]
    payload = _compact({
        "id": str(intent.get("id") or ""),
        "需求名称": _clean(intent.get("intent_name")),
        "级别": _clean(intent.get("intent_grade")),
        "状态": INTENT_STATUS_LABELS.get(str(intent.get("status") or "")),
        "暂停原因": _clean(intent.get("pause_reason")),
        "待确认项": intent.get("needs_confirmation_json"),
        "原始需求": _clean_requirement_text(intent.get("raw_requirement_text")),
    })
    if len(blocks) == 1:
        payload.update(blocks[0])
    elif blocks:
        payload["方案"] = blocks
        payload["方案说明"] = "满足任意一个方案即算命中这条需求。不要把多个方案的门槛叠加起来判。"
    if not any(_scenario_thresholds(scenario) for scenario in scenarios):
        payload["门槛说明"] = "这条需求没有提出任何硬门槛，不构成障碍。"
    return payload


def _dossier(party: dict[str, Any], intents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "买家信息": _party_full(party),
        "收购需求": [_intent_full(intent) for intent in intents],
    }


# -- 接口一：全库业务原文 -------------------------------------------------


def search_buyers_business(detail: str = "full") -> dict[str, Any]:
    """全部在库买家的业务原文，供你逐条读、判业务匹配。

    **没有行业/关键词参数是刻意的。** 买家说的是「薄膜电容器」「线控底盘」这类
    细分方向，任何字典都接不住；库规模又小到可以整个读一遍。所以这里把材料
    全给你，判断由你做 —— 这一步没有 SQL 参与。
    """
    try:
        token = _token()
    except RuntimeError as error:
        return {"matched": 0, "returned": [], "error": str(error)}

    brief = str(detail).strip().lower() == "brief"
    parties, intents = _load(token)

    by_party: dict[str, list[dict[str, Any]]] = {}
    for intent in intents:
        by_party.setdefault(str(intent.get("buyer_party_id")), []).append(intent)

    cards: list[dict[str, Any]] = []
    for party_id, party in parties.items():
        party_intents = by_party.get(party_id) or []
        if not party_intents:
            # 没有在库需求的主体不返回：它没有「要买什么」，判不了业务匹配。
            continue
        cards.append({
            "buyer_party_id": party_id,
            **_party_business(party, brief=brief),
            "需求": [_intent_business(intent, brief=brief) for intent in party_intents],
        })

    cards.sort(key=lambda card: card.get("买家名称") or "")
    notes = [
        "这是全库业务原文，**没有做过任何业务筛选** —— 业务是否对口完全由你读文本判断。",
        "业务说明为空的买家不要从公司名猜业务，如实说「信息不足，无法判断」。",
        "同一家买家名下可能有多条需求，它们是不同的收购方向，分别判断。",
    ]
    if brief:
        notes.append(f"brief 模式：业务说明截断到 {BRIEF_BUSINESS_CHARS} 字、需求摘要 {BRIEF_INTENT_CHARS} 字。判不准时改用 detail=full。")
    return {"matched": len(cards), "returned": cards, "notes": notes}


# -- 接口二：按名称取全量档 -----------------------------------------------


def get_buyer(name: str | None = None, buyer_party_id: str | None = None) -> dict[str, Any]:
    """按名称（模糊，认别名）或 id 取买家全量档案。

    **名称命中多个时返回全部候选，不合并、不只取第一个。** 生产库里
    「北大健康」有 3 个主体 / 4 条需求 —— 那是真实的重复数据（或去重债），
    由调用方消歧，skill 不替它做决定。
    """
    try:
        token = _token()
    except RuntimeError as error:
        return {"matched": 0, "returned": [], "error": str(error)}

    parties, intents = _load(token)
    by_party: dict[str, list[dict[str, Any]]] = {}
    for intent in intents:
        by_party.setdefault(str(intent.get("buyer_party_id")), []).append(intent)

    if buyer_party_id:
        party = parties.get(_clean(buyer_party_id))
        if party is None:
            return {
                "matched": 0,
                "returned": [],
                "notes": [f"没有 id 为 {buyer_party_id} 的在库买家（也可能它已归档）。"],
            }
        return {"matched": 1, "returned": [_dossier(party, by_party.get(str(party["id"])) or [])]}

    keyword = _clean(name)
    if not keyword:
        return {"matched": 0, "returned": [], "notes": ["需要 name 或 buyer_party_id 之一。"]}

    # 零宽字符必须先洗掉再匹配：生产里有一条名字带零宽不连字，
    # 精确匹配会静默失败 —— 看起来就像「库里没有这家」。
    lowered = keyword.lower()
    hits: list[dict[str, Any]] = []
    for party in parties.values():
        haystack = [_clean(party.get("buyer_name"))]
        aliases = party.get("aliases_json")
        if isinstance(aliases, list):
            haystack.extend(_clean(alias) for alias in aliases)
        if any(lowered in item.lower() for item in haystack if item):
            hits.append(party)

    hits.sort(key=lambda party: (len(_clean(party.get("buyer_name"))), _clean(party.get("buyer_name"))))
    notes: list[str] = []
    if not hits:
        notes.append(f"买家库里没有名称或别名包含「{keyword}」的在库买家。不要据此推断这家公司不存在，只是不在库里。")
    elif len(hits) > 1:
        notes.append(
            f"「{keyword}」命中 {len(hits)} 个主体。**这是真实数据不是重复项**："
            "同名主体在生产库里确实存在，请按需求内容自行判断该用哪一个，或向用户说明有多条。"
        )
    return {
        "matched": len(hits),
        "returned": [_dossier(party, by_party.get(str(party["id"])) or []) for party in hits],
        **({"notes": notes} if notes else {}),
    }


# -- 接口三：按条件筛 -----------------------------------------------------


def _region_hit(regions: Any, province: str, city: str, district: str) -> bool:
    """标的地区是否命中数组里任一项。逐级独立：只填省 = 全省命中。"""
    if not isinstance(regions, list):
        return False
    for item in regions:
        if not isinstance(item, dict):
            continue
        levels = [
            (_clean(item.get("province")), province),
            (_clean(item.get("city")), city),
            (_clean(item.get("district")), district),
        ]
        if not any(wanted for wanted, _ in levels):
            continue
        if all(not wanted or wanted == actual for wanted, actual in levels):
            return True
    return False


def _scenario_checks(scenario: dict[str, Any], target: dict[str, Any]) -> list[tuple[str, bool, bool]]:
    """一个方案逐条门槛的判定，返回 (条件名, 买家提了没, 提了的话过没过)。

    ⚠️ **反向检索最大的陷阱在这里**：买家没提这条门槛时 `stated=False`，
    调用方必须把它读成「不构成障碍」而不是「不满足」。把 NULL 当成不满足，
    一半以上的买家会当场消失 —— 而消失的恰恰是最灵活、最该推的那批。
    """
    checks: list[tuple[str, bool, bool]] = []

    def numeric(label: str, threshold: Any, actual: Any, *, at_least: bool) -> None:
        limit = _number(threshold)
        if limit is None:
            checks.append((label, False, True))
            return
        value = _number(actual)
        if value is None:
            # 标的这一侧没给数：不能判它不达标，交给调用方看「未判定」。
            checks.append((label, True, True))
            return
        checks.append((label, True, value >= limit if at_least else value <= limit))

    numeric("最低营收", scenario.get("min_revenue_yuan"), target.get("revenue_yuan"), at_least=True)
    numeric("最低净利润", scenario.get("min_net_profit_yuan"), target.get("net_profit_yuan"), at_least=True)
    numeric("PE 上限", scenario.get("max_pe"), target.get("pe"), at_least=False)
    numeric("估值下限", scenario.get("min_valuation_yuan"), target.get("valuation_yuan"), at_least=True)
    numeric("估值上限", scenario.get("max_valuation_yuan"), target.get("valuation_yuan"), at_least=False)
    numeric("市值下限", scenario.get("min_market_cap_yuan"), target.get("market_cap_yuan"), at_least=True)
    numeric("市值上限", scenario.get("max_market_cap_yuan"), target.get("market_cap_yuan"), at_least=False)

    acceptable = scenario.get("acceptable_listed_status_json")
    listed = _clean(target.get("listed_status"))
    if not isinstance(acceptable, list) or not acceptable:
        checks.append(("上市状态", False, True))
    elif not listed:
        checks.append(("上市状态", True, True))
    else:
        checks.append(("上市状态", True, listed in {str(item) for item in acceptable}))

    province, city, district = (
        _clean(target.get("province")), _clean(target.get("city")), _clean(target.get("district")),
    )
    regions = scenario.get("required_regions_json")
    if not isinstance(regions, list) or not regions:
        # 空数组 = 不限，**不是**「没有要求地区」。
        checks.append(("要求地区", False, True))
    elif not (province or city or district):
        checks.append(("要求地区", True, True))
    else:
        checks.append(("要求地区", True, _region_hit(regions, province, city, district)))
    return checks


def _intent_checks(intent: dict[str, Any], target: dict[str, Any]) -> list[tuple[str, bool, bool]]:
    """整条需求的判定 —— **命中任意一个方案即算命中**。

    多方案是 OR，不是 AND。把三个方案的门槛叠加起来判，会让岭南商旅的「酒店」
    那一档凭空背上「粮油食品」那一档的营收与估值要求，而叠加不报错，
    表现只是「这个买家好像什么都不要」。

    返回的是**命中的那个方案**的判定表；一个都不命中时返回第一个方案的，
    让调用方看得到它差在哪。
    """
    scenarios = _scenarios(intent)
    if not scenarios:
        # 需求没有方案是不合法状态（迁移 023 给每条需求都生成了一个）。
        # 真遇到就当成「没提任何门槛」，那是这个数据形状下唯一诚实的读法。
        return []
    tables = [_scenario_checks(scenario, target) for scenario in scenarios]
    for table in tables:
        if all(passed for _, _, passed in table):
            return table
    return tables[0]


def _party_conditions_hit(party: dict[str, Any], filters: dict[str, Any]) -> bool:
    """买家自身条件。

    这是对买家事实的**显式筛选**：调用方传了条件，就必须有已知事实且命中；
    空值或 ``unknown`` 不算满足。结果过少时由上游 Agent 自主减少筛选条件重试，
    不能在这里把未知记录伪装成符合。
    """
    for key, column in (
        ("ownership_type", "ownership_type"),
        ("listed_status", "listed_status"),
        ("province", "location_province"),
        ("city", "location_city"),
        ("district", "location_district"),
    ):
        wanted = _clean(filters.get(key))
        if not wanted:
            continue
        actual = _clean(party.get(column))
        if _blank(actual) or actual != wanted:
            return False
    for key, column in (
        ("min_market_cap_yuan", "market_cap_yuan"),
        ("min_revenue_yuan", "current_revenue_yuan"),
    ):
        limit = _number(filters.get(key))
        if limit is None:
            continue
        value = _number(party.get(column))
        if value is None or value < limit:
            return False
    return True


def filter_buyers(
    ownership_type: str | None = None,
    listed_status: str | None = None,
    province: str | None = None,
    city: str | None = None,
    district: str | None = None,
    min_market_cap_yuan: float | None = None,
    min_revenue_yuan: float | None = None,
    target_revenue_yuan: float | None = None,
    target_net_profit_yuan: float | None = None,
    target_pe: float | None = None,
    target_market_cap_yuan: float | None = None,
    target_valuation_yuan: float | None = None,
    target_listed_status: str | None = None,
    target_province: str | None = None,
    target_city: str | None = None,
    target_district: str | None = None,
) -> dict[str, Any]:
    """按买家自身条件 + 标的事实反查需求门槛，返回全量档。

    `target_*` 是**这个标的的事实**，不是你想要的门槛 —— 代码拿它去比每条需求
    自己的门槛。买家没设那条门槛时一律通过，并在返回里标成「买家没提过」。
    """
    try:
        token = _token()
    except RuntimeError as error:
        return {"matched": 0, "returned": [], "error": str(error)}

    parties, intents = _load(token)
    party_filters = {
        "ownership_type": ownership_type,
        "listed_status": listed_status,
        "province": province,
        "city": city,
        "district": district,
        "min_market_cap_yuan": min_market_cap_yuan,
        "min_revenue_yuan": min_revenue_yuan,
    }
    target = {
        "revenue_yuan": target_revenue_yuan,
        "net_profit_yuan": target_net_profit_yuan,
        "pe": target_pe,
        "market_cap_yuan": target_market_cap_yuan,
        "valuation_yuan": target_valuation_yuan,
        "listed_status": target_listed_status,
        "province": target_province,
        "city": target_city,
        "district": target_district,
    }

    hits: list[tuple[dict[str, Any], dict[str, Any], dict[str, str]]] = []
    # 逐条件的 marginal：去掉这一条能多召回几家、其中多少只是买家没提过。
    marginal: dict[str, dict[str, int]] = {}
    for intent in intents:
        party = parties[str(intent.get("buyer_party_id"))]
        if not _party_conditions_hit(party, party_filters):
            continue
        checks = _intent_checks(intent, target)
        failed = [label for label, stated, passed in checks if stated and not passed]
        if not failed:
            verdicts = {
                label: ("明确符合" if stated else "买家没提过这个门槛，不构成障碍")
                for label, stated, _ in checks
            }
            hits.append((party, intent, verdicts))
        elif len(failed) == 1:
            # 只差这一条：去掉它就能召回。这是调用方放宽条件的唯一依据。
            bucket = marginal.setdefault(failed[0], {"去掉这条能多召回": 0})
            bucket["去掉这条能多召回"] += 1

    notes: list[str] = [
        "**「买家没提过这个门槛」= 不构成障碍，是正面信号**，不要读成「信息不足无法判断」——"
        "那样会把库里最灵活的那批买家全漏掉，而它们恰恰最该推。",
        "买家自身信息（业务说明、市值、营收）缺失才是「没录、未知」。两类缺失含义相反。",
    ]
    if marginal:
        notes.append(
            "只差一条就能命中的：" + "、".join(
                f"{label}（去掉能多召回 {counts['去掉这条能多召回']} 家）"
                for label, counts in sorted(marginal.items())
            )
        )
    if len(hits) > FILTER_RESULT_LIMIT:
        notes.append(
            f"命中 {len(hits)} 条需求，超过单次返回上限 {FILTER_RESULT_LIMIT} 条，"
            "已按买家名称返回前 50 条。**这不是全部** —— 请收窄条件后重试，"
            "或改用 search_buyers_business 先按业务方向缩小范围。"
        )
    if not hits:
        notes.append("该条件下没有命中的需求。检查一下 target_* 传的是不是这个标的的真实数字。")

    hits.sort(key=lambda row: (_clean(row[0].get("buyer_name")), _clean(row[1].get("intent_name"))))
    returned = [
        {
            "买家信息": _party_full(party),
            "收购需求": _intent_full(intent),
            "条件判定": verdicts,
        }
        for party, intent, verdicts in hits[:FILTER_RESULT_LIMIT]
    ]
    return {"matched": len(hits), "returned": returned, "notes": notes}


# -- Wegent 单工具兼容入口 -----------------------------------------------


def search_buyers(
    operation: str = "business",
    detail: str = "full",
    name: str | None = None,
    buyer_party_id: str | None = None,
    ownership_type: str | None = None,
    listed_status: str | None = None,
    province: str | None = None,
    city: str | None = None,
    district: str | None = None,
    min_market_cap_yuan: float | None = None,
    min_revenue_yuan: float | None = None,
    target_revenue_yuan: float | None = None,
    target_net_profit_yuan: float | None = None,
    target_pe: float | None = None,
    target_market_cap_yuan: float | None = None,
    target_valuation_yuan: float | None = None,
    target_listed_status: str | None = None,
    target_province: str | None = None,
    target_city: str | None = None,
    target_district: str | None = None,
) -> dict[str, Any]:
    """Wegent-compatible single tool entry point.

    Wegent's skill loader expects one ``tool.json`` object and a Python function
    with the same name.  Keep the three query shapes behind an explicit operation
    so the loader can expose one tool without changing their semantics.
    """
    op = str(operation or "business").strip().lower()
    if op in {"business", "search_buyers_business"}:
        return search_buyers_business(detail=detail)
    if op in {"get", "get_buyer"}:
        return get_buyer(name=name, buyer_party_id=buyer_party_id)
    if op in {"filter", "filter_buyers"}:
        return filter_buyers(
            ownership_type=ownership_type,
            listed_status=listed_status,
            province=province,
            city=city,
            district=district,
            min_market_cap_yuan=min_market_cap_yuan,
            min_revenue_yuan=min_revenue_yuan,
            target_revenue_yuan=target_revenue_yuan,
            target_net_profit_yuan=target_net_profit_yuan,
            target_pe=target_pe,
            target_market_cap_yuan=target_market_cap_yuan,
            target_valuation_yuan=target_valuation_yuan,
            target_listed_status=target_listed_status,
            target_province=target_province,
            target_city=target_city,
            target_district=target_district,
        )
    return {
        "matched": 0,
        "returned": [],
        "error": (
            f"不支持的 operation: {operation!r}。请使用 business、get 或 filter。"
        ),
    }


# -- 诊断与凭证 -----------------------------------------------------------


def _mask(value: str) -> str:
    return ("*" * 8) + value[-4:] if len(value) > 4 else "****"


def _token_expiry(token: str) -> str:
    """读出 JWT 的到期时间。只解 payload，不验签 —— 这里只是给人看。"""
    import base64
    import datetime

    try:
        payload_text = token.split(".")[1]
        payload_text += "=" * (-len(payload_text) % 4)
        expires_at = json.loads(base64.urlsafe_b64decode(payload_text))["exp"]
    except Exception:  # noqa: BLE001 —— 静态令牌不是 JWT，没有到期时间
        return "未知（这不像是 JWT，可能是静态管理员令牌）"
    return datetime.datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M")


def issue_token(*, show: bool = False) -> int:
    """登录换一个 7 天 JWT，直接写成脚本同目录的 auth.local.json。

    没有环境变量时会**交互式询问**账号密码（密码不回显）—— 让人手工拼环境变量
    是这个流程最容易卡住的一步，尤其在 PowerShell 和 bash 语法不同的时候。
    """
    import getpass

    username = os.environ.get("MATCH_MA_USERNAME")
    password = os.environ.get("MATCH_MA_PASSWORD")

    if not username or not password:
        print("生成买家检索 skill 的访问凭证（7 天有效）")
        print("")
        try:
            # isatty() 在部分包装过的终端里判断不准，所以直接试着读，读不到再报。
            username = username or input("Match-MA 用户名：").strip()
            password = password or getpass.getpass("密码（输入时不显示，输完回车）：")
        except (EOFError, KeyboardInterrupt):
            print("")
            print("这个终端读不到输入（或你取消了）。请在自己的 PowerShell / 终端里重跑，")
            print("或改为先设置环境变量 MATCH_MA_USERNAME 与 MATCH_MA_PASSWORD。")
            return 2

    if not username or not password:
        print("用户名或密码为空，已取消。")
        return 2

    try:
        token = _login(username, password)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            print("登录失败：用户名或密码不对。连续 5 次失败会锁定 5 分钟。")
        elif error.code == 429:
            print("登录失败：该用户名已被锁定，等 5 分钟后再试。")
        else:
            print(f"登录失败：HTTP {error.code}")
        return 2
    except OSError as error:
        print(f"连不上服务器：{error}")
        return 2

    target = Path(__file__).resolve().parent / "auth.local.json"
    target.write_text(json.dumps({"token": token}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass

    print("")
    print("已写入：" + str(target))
    print("令牌   ：" + _mask(token))
    print("到期   ：" + _token_expiry(token) + "  （过期前重跑本命令换一个）")
    print("")
    print("下一步：把整个 skill 目录（含 auth.local.json）上传到 wegent，")
    print("        然后在那边跑 `python search_buyers.py --check` 验证。")
    print("")
    print("这个文件是一份有效凭证：已被 .gitignore 排除，不要提交、不要贴进对话。")
    if show:
        print("")
        print("完整令牌（仅在需要手工粘贴时使用）：")
        print(token)
    return 0


def check() -> int:
    """诊断凭证、连通性与库规模。永远不打印完整令牌。"""
    print("API_BASE            : " + _api_base())
    for name in ("MATCH_MA_USERNAME", "MATCH_MA_AUTH_FILE"):
        print(f"{name:20s}: " + (os.environ.get(name) or "(未设置)"))
    for name in ("MATCH_MA_PASSWORD", "MATCH_MA_TOKEN"):
        value = os.environ.get(name)
        print(f"{name:20s}: " + (_mask(value) if value else "(未设置)"))
    print("凭证文件查找路径    :")
    for path in _auth_file_candidates():
        print(("    [命中] " if path.is_file() else "    [没有] ") + str(path))
    print("")
    try:
        token = _token()
    except RuntimeError as error:
        print("凭证解析失败        : " + str(error))
        return 2
    print("解析到的令牌        : " + _mask(token))
    try:
        parties, intents = _load(token)
    except Exception as error:  # noqa: BLE001 —— 诊断模式要把原因原样显示
        print(f"连通性              : 失败 —— {type(error).__name__}: {error}")
        return 2
    with_summary = sum(1 for party in parties.values() if not _blank(party.get("business_summary")))
    with_intent_summary = sum(
        1 for intent in intents
        if not _blank(intent.get("intent_business_summary") or intent.get("intent_summary"))
    )
    print("连通性              : 正常")
    print(f"在库买家主体        : {len(parties)} 家（过闸门后）")
    print(f"  其中有业务说明    : {with_summary} 家  ← 首轮筛只读这一栏，它是效果上限")
    print(f"在库需求            : {len(intents)} 条（E 级与已结束的已排除）")
    print(f"  其中有业务方向    : {with_intent_summary} 条")
    if with_summary * 2 < len(parties):
        print("")
        # Keep diagnostics ASCII-safe for Windows consoles using the GBK code page.
        print("[WARN] 超过一半的买家没有业务说明。首轮筛只读这一栏，缺它的买家判不出业务匹配 ——")
        print("   这种情况下要补的是**数据**，不是提示词。")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="买家库检索（为标的找买家）")
    parser.add_argument("--check", action="store_true", help="诊断凭证、连通性与库规模，不做检索")
    parser.add_argument("--issue-token", action="store_true", help="登录换一个 7 天 JWT 并写入同目录的 auth.local.json")
    parser.add_argument("--show", action="store_true", help="配合 --issue-token：把完整令牌也打印出来，供手工粘贴")
    parser.add_argument("--business", action="store_true", help="接口一：全库业务原文")
    parser.add_argument("--detail", default="full", choices=["full", "brief"], help="接口一的详略")
    parser.add_argument("--name", default=None, help="接口二：按名称取全量档（认别名，模糊匹配）")
    parser.add_argument("--buyer-party-id", default=None, help="接口二：按 id 取全量档")
    parser.add_argument("--filter", action="store_true", help="接口三：按条件筛")
    parser.add_argument("--ownership-type", default=None)
    parser.add_argument("--listed-status", default=None)
    parser.add_argument("--province", default=None)
    parser.add_argument("--city", default=None)
    parser.add_argument("--district", default=None)
    parser.add_argument("--target-revenue-yuan", type=float, default=None)
    parser.add_argument("--target-net-profit-yuan", type=float, default=None)
    parser.add_argument("--target-pe", type=float, default=None)
    parser.add_argument("--target-listed-status", default=None)
    parser.add_argument("--target-province", default=None)
    parser.add_argument("--target-city", default=None)
    parser.add_argument("--target-district", default=None)
    parser.add_argument("--min-market-cap-yuan", type=float, default=None)
    parser.add_argument("--min-revenue-yuan", type=float, default=None)
    parser.add_argument("--target-market-cap-yuan", type=float, default=None)
    parser.add_argument("--target-valuation-yuan", type=float, default=None)
    args = parser.parse_args()

    if args.issue_token:
        raise SystemExit(issue_token(show=args.show))
    if args.check:
        raise SystemExit(check())

    if args.name or args.buyer_party_id:
        result = get_buyer(name=args.name, buyer_party_id=args.buyer_party_id)
    elif args.filter:
        result = filter_buyers(
            ownership_type=args.ownership_type,
            listed_status=args.listed_status,
            province=args.province,
            city=args.city,
            district=args.district,
            min_market_cap_yuan=args.min_market_cap_yuan,
            min_revenue_yuan=args.min_revenue_yuan,
            target_revenue_yuan=args.target_revenue_yuan,
            target_net_profit_yuan=args.target_net_profit_yuan,
            target_pe=args.target_pe,
            target_market_cap_yuan=args.target_market_cap_yuan,
            target_valuation_yuan=args.target_valuation_yuan,
            target_listed_status=args.target_listed_status,
            target_province=args.target_province,
            target_city=args.target_city,
            target_district=args.target_district,
        )
    else:
        result = search_buyers_business(detail=args.detail)

    print(json.dumps(result, ensure_ascii=False, indent=2))
