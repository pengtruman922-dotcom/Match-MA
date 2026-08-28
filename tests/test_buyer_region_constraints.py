from backend.app.services.region_dictionary import normalize_buyer_region_constraints


def test_nationwide_region_means_no_constraint() -> None:
    constraints, pending = normalize_buyer_region_constraints(
        [{"province": "全国", "effect": "required"}]
    )

    assert constraints == []
    assert pending == []


def test_standard_regions_keep_individual_effects() -> None:
    constraints, pending = normalize_buyer_region_constraints(
        [
            {"province": "江苏", "effect": "required"},
            {"province": "上海市", "effect": "preferred"},
            {"province": "安徽", "effect": "excluded"},
        ]
    )

    assert constraints == [
        {"province": "江苏省", "effect": "required"},
        {"province": "上海市", "effect": "preferred"},
        {"province": "安徽省", "effect": "excluded"},
    ]
    assert pending == []


def test_unrecognized_region_is_isolated_for_confirmation() -> None:
    constraints, pending = normalize_buyer_region_constraints(
        [
            {"province": "浙江省", "effect": "preferred"},
            {"province": "某战略区域", "effect": "required", "evidence": "重点考虑某战略区域"},
        ]
    )

    assert constraints == [{"province": "浙江省", "effect": "preferred"}]
    assert pending[0]["field"] == "region_constraints_json"
    assert pending[0]["proposed_value"]["province"] == "某战略区域"


# =========================================================================
# 城市群与「不限」：顾问说地域时用的几乎都是这套词，而不是省名
# =========================================================================


def test_a_city_cluster_expands_into_the_provinces_it_covers() -> None:
    """契约只收省份，而生产 26 条只有文本的需求里提到长三角 7 次、华东/华中/西南各 2 次。

    不展开的话 agent 只有两条路：放弃（那 26 条），或者硬猜一个省 —— 后者更糟，
    「优选长三角」被写成「广东省」会让初筛把长三角的标的全挡掉。
    """
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    constraints, pending = normalize_buyer_region_constraints(
        [{"province": "长三角", "effect": "preferred"}]
    )

    assert [item["province"] for item in constraints] == ["上海市", "江苏省", "浙江省", "安徽省"]
    assert all(item["effect"] == "preferred" for item in constraints)
    assert pending == []


def test_the_longest_cluster_name_wins() -> None:
    """「粤港澳大湾区」必须先于「粤港澳」命中，否则按前缀匹配会丢掉一段词。"""
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    constraints, _ = normalize_buyer_region_constraints([{"province": "粤港澳大湾区"}])

    assert {item["province"] for item in constraints} == {
        "广东省", "香港特别行政区", "澳门特别行政区",
    }


def test_a_cluster_name_with_a_suffix_still_matches() -> None:
    """真实原文写的是「长三角区域」「华东地区」，不是光秃秃的词。"""
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    constraints, _ = normalize_buyer_region_constraints([{"province": "长三角区域"}])

    assert [item["province"] for item in constraints] == ["上海市", "江苏省", "浙江省", "安徽省"]


def test_every_cluster_expands_only_to_real_provinces() -> None:
    """展开出来的省份必须是闸门认得的那 34 个，否则筛选永远命不中。"""
    from backend.app.services.region_dictionary import PROVINCES, REGION_GROUPS

    unknown = sorted(
        {member for members in REGION_GROUPS.values() for member in members if member not in PROVINCES}
    )
    assert not unknown, f"这些不是标准省级名称：{unknown}"


def test_nationwide_is_no_constraint_rather_than_a_place() -> None:
    """「全国/不限」不是一个地域约束，是没有约束 —— 初筛里两者行为相同。

    所以丢掉是对的，不是信息损失：原话仍然留在 region_scope_summary 里给人看。
    """
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    for term in ("全国", "不限", "无地域限制", "不限注册地", "境内"):
        constraints, pending = normalize_buyer_region_constraints([{"province": term}])
        assert constraints == [], f"「{term}」不该落成一个省份约束"
        assert pending == [], f"「{term}」也不该进待确认 —— 它并不含糊"


def test_a_bare_string_array_is_rescued_instead_of_dropped() -> None:
    """生产里躺着 `["四川省","云南省","贵州省"]` 这种形状（华润医药）。

    以前 `if not isinstance(item, dict): continue` 会把整条地域要求静默丢掉，
    而初筛按 `rc->>'province'` 取值，取不出东西 —— 存了等于没存，且看不出来。
    """
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    constraints, _ = normalize_buyer_region_constraints(["四川省", "云南省", "贵州省"])

    assert [item["province"] for item in constraints] == ["四川省", "云南省", "贵州省"]


def test_raw_text_is_used_when_province_is_null() -> None:
    """另一条生产脏数据（中大高端装备）：模型用了另一套键名，province 是 null。"""
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    constraints, _ = normalize_buyer_region_constraints(
        [{"city": None, "province": None, "raw_text": "长三角、珠三角区域", "constraint_type": "soft"}]
    )

    # 「长三角、珠三角区域」按最长前缀命中长三角；珠三角那半截靠提示词分成两条给。
    assert [item["province"] for item in constraints] == ["上海市", "江苏省", "浙江省", "安徽省"]
    assert all(item["effect"] == "preferred" for item in constraints), "soft 应归一成 preferred"


def test_an_ordinary_province_is_untouched_by_the_cluster_layer() -> None:
    from backend.app.services.region_dictionary import normalize_buyer_region_constraints

    constraints, _ = normalize_buyer_region_constraints(
        [{"province": "广东", "effect": "required"}, {"province": "湖北省", "effect": "excluded"}]
    )

    assert constraints == [
        {"province": "广东省", "effect": "required"},
        {"province": "湖北省", "effect": "excluded"},
    ]


def test_the_rest_routes_normalize_regions_too() -> None:
    """解析 handler 归一了，REST 写入没归一 —— 于是脏形状直接落进初筛要读的那一列。

    生产里那两条就是这么来的。静态断言：两条写路径都必须过归一。
    """
    import inspect

    from backend.app.api.routes import buyer_intents as module

    # 新建走参数构造器，更新在自己函数里改 changes —— 两条路各自都要过归一。
    created = inspect.getsource(module._buyer_intent_params)
    assert "normalize_buyer_region_constraints" in created, "新建路径（参数构造器）没归一地域"
    assert "_buyer_intent_params" in inspect.getsource(module.create_buyer_intent), (
        "新建不再走参数构造器了，这条断言要跟着改"
    )
    update = inspect.getsource(module.update_buyer_intent)
    assert "normalize_buyer_region_constraints" in update, "更新路径没归一地域"
