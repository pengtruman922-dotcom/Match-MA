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

    # 两个城市群都要展开：只认前缀会把珠三角整个丢掉，而丢掉的地区在筛选里表现为
    # 「这些标的进不来」，界面上看不出来。
    assert [item["province"] for item in constraints] == [
        "上海市", "江苏省", "浙江省", "安徽省", "广东省",
    ]
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

    生产里那两条就是这么来的：一条裸字符串数组 `["四川省","云南省"]`，一条
    `{"raw_text":"长三角、珠三角区域","constraint_type":"soft"}`。筛选按
    `->>'province'` 取值，两条都取不出东西 —— **存了等于没存，且看不出来**。

    0901 起地区住在方案表上（`required_regions_json`），所以要守的写路径变了：
    新建需求那条不再写地区列（它退役了），方案的新增与修改才是入口。
    """
    import inspect

    from backend.app.api.routes import buyer_intents as module

    # 方案的新建与修改共用同一个归一：两条路各写一份的表现是「谁填的」决定
    # 值长什么样 —— 顾问敲「江苏」，解析写「江苏省」，而 SQL 只认后者。
    normalized = inspect.getsource(module.BuyerIntentScenarioWrite.normalized)
    assert "normalize_buyer_regions" in normalized, "方案写入没归一地域"
    for route in (module.create_buyer_intent_scenario, module.update_buyer_intent_scenario):
        assert "payload.normalized()" in inspect.getsource(route), (
            f"{route.__name__} 绕过了归一，脏形状会直接落进初筛要读的那一列"
        )
    # 需求侧的更新路径仍然可能改到存量地区列（阶段 A 列还在），继续守。
    update = inspect.getsource(module.update_buyer_intent)
    assert "normalize_buyer_regions" in update, "更新路径没归一地域"


def test_two_clusters_in_one_string_both_expand() -> None:
    """真实数据里一格常常写着「长三角、珠三角区域」（生产里就有这一条）。

    只按前缀匹配会把珠三角整个丢掉，而丢掉的地区在筛选里表现为「这些标的进不来」，
    界面上看不出来 —— 与漏掉一个门槛是同一类静默收窄。
    """
    from backend.app.services.region_dictionary import expand_region_group

    provinces = expand_region_group("长三角、珠三角区域")

    assert provinces == ("上海市", "江苏省", "浙江省", "安徽省", "广东省")


def test_an_overlapping_cluster_name_is_not_counted_twice() -> None:
    """「粤港澳大湾区」里含「粤港澳」和「大湾区」，最长优先并吃掉已匹配片段。"""
    from backend.app.services.region_dictionary import expand_region_group

    provinces = expand_region_group("粤港澳大湾区")

    assert provinces == ("广东省", "香港特别行政区", "澳门特别行政区")
    assert len(provinces) == len(set(provinces)), "同一个省不该出现两次"


def test_a_plain_province_is_not_treated_as_a_cluster() -> None:
    from backend.app.services.region_dictionary import expand_region_group

    assert expand_region_group("广东省") == ()
    assert expand_region_group("") == ()
    assert expand_region_group(None) == ()


# -- 0828：两个平铺数组取代 region_constraints_json ------------------------


def test_the_flat_regions_carry_no_effect() -> None:
    """可接受与排除拆成两列之后，语义写在列名里，元素里不再有 effect。

    强弱（「必须在广东」对「优先广东」）交给 region_scope_summary 的原话 ——
    语气和强度归文本，阈值和枚举归字段。
    """
    from backend.app.services.region_dictionary import normalize_buyer_regions

    regions, pending = normalize_buyer_regions(
        [{"province": "广东省", "effect": "required"}, {"province": "江苏省", "city": "苏州市"}],
        field="acceptable_regions_json",
    )

    assert regions == [{"province": "广东省"}, {"province": "江苏省", "city": "苏州市"}]
    assert all("effect" not in region for region in regions)
    assert pending == []


def test_the_flat_regions_share_the_cluster_table_with_the_old_column() -> None:
    """大区展开放在代码里而不是提示词里：提示词里的表每次调用都要模型照抄一遍，
    改词表要发新版本，而且模型可能漏抄。两个归一函数共用同一份 REGION_GROUPS。
    """
    from backend.app.services.region_dictionary import normalize_buyer_regions

    regions, _ = normalize_buyer_regions([{"province": "长三角"}], field="acceptable_regions_json")

    assert [region["province"] for region in regions] == ["上海市", "江苏省", "浙江省", "安徽省"]


def test_a_cluster_expansion_drops_the_city() -> None:
    """说「长三角的苏州」是自相矛盾的输入。

    把市套到展开出来的四个省上会造出「上海市苏州市」这种筛不到东西的组合，
    而且不报错 —— 存了等于没存。
    """
    from backend.app.services.region_dictionary import normalize_buyer_regions

    regions, _ = normalize_buyer_regions(
        [{"province": "长三角", "city": "苏州市"}], field="acceptable_regions_json"
    )

    assert all("city" not in region for region in regions)


def test_an_unmappable_region_goes_to_pending_not_to_the_bin() -> None:
    """归一不出来的地区**不能直接丢**：丢掉的地区在筛选里表现为
    「这些标的进不来」，界面上看不出来。所以转成待确认项让人来判。
    """
    from backend.app.services.region_dictionary import normalize_buyer_regions

    regions, pending = normalize_buyer_regions(
        [{"province": "江苏省"}, {"province": "火星"}], field="excluded_regions_json"
    )

    assert regions == [{"province": "江苏省"}]
    assert len(pending) == 1
    assert pending[0]["field"] == "excluded_regions_json"


def test_unrestricted_terms_produce_an_empty_array() -> None:
    """「全国 / 不限」不是一个约束，是**没有**约束 —— 空数组就是它的表达。

    原话仍然留在 region_scope_summary 里给人看，这里丢掉不算信息损失。
    """
    from backend.app.services.region_dictionary import normalize_buyer_regions

    regions, pending = normalize_buyer_regions(
        [{"province": "全国"}, {"province": "不限"}], field="acceptable_regions_json"
    )

    assert regions == []
    assert pending == []
