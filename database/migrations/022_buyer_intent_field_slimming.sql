-- 买家需求字段精简 —— 阶段 A：加列、回填、删孤儿列。旧列一律保留。
--
-- 本单同时做两件互相咬合的事：需求字段精简，与新建的反向检索 skill。
-- 精简的依据正是「反向检索不需要这些结构化字段」：买家库规模足够小
-- （42 主体 / 52 需求，预期长到 200），业务匹配可以把全部买家的业务原文
-- 一次性交给 LLM 判断，不需要结构化字段参与。方案见
-- 《买家需求字段精简与反向检索方案0828.md》。
--
-- ============ 为什么必须两阶段 ============
--
-- 本文件**只加不删**（4 个孤儿列除外）。真正的 drop 另开迁移，等 Railway
-- 全部服务跑上阶段 A 代码之后再做 —— 与 0727 的 recommendation_status、
-- 0814 的级别改造同一节奏（总纲 2.4）。
--
-- 理由是爆炸半径实测很大：industries_json 被 34 个文件引用、intent_summary 26 个、
-- region_constraints_json 24 个。一次 drop 22 列，任何一处投影漏改都会让整个
-- 需求列表页 500，而且是 preDeploy 迁移跑完之后才炸 —— 那时数据已经没了。
--
-- 「退役」在阶段 A 的含义是**改注册表标志位**，不是删列：
-- writable_by 去掉 parse，字段就从 field_contract_json 消失、模型再也看不到、
-- extracted_action 的 apply 白名单同步收缩，而列还在、存量数据还在、人工仍可编辑。
-- 改回来是一行。
--
-- ============ 例外：4 个孤儿列在这一批直接删 ============
--
-- acceptable_control_paths_json / budget_min_yuan / budget_max_yuan /
-- relocation_target_regions_json 不在指标注册表里，前端不显示、初筛不用、
-- 深评不读，但 buyer_intent_parse.py 每次解析都在写它们。它们的消费方全是
-- 机械的投影清单（各约 7 个文件），半径可控，所以不必等阶段 B。
-- 四列都没有索引，也没有出现在任何 check 约束里，drop 是干净的。
--
-- ============ 本文件的两条硬规则 ============
--
-- 一、注释里不能出现分号。自制 splitter（backend/app/migration_sql.py）按分号
--     切语句，注释里的分号会切坏语句、部署直接挂（有过事故，见 AGENTS.md）。
--
-- 二、有既有 CHECK 约束的表，同一约束涉及的多列必须在同一条 UPDATE 里改完。
--     0818 出过事故：buyer_intent_check（股比 min 小于等于 max）在分两条 UPDATE
--     时中间态炸掉，整个 preDeploy 回滚、部署阻断，而 CI 空库跑不出来（没有数据）。
--     本文件回填的五个新列都不参与任何既有约束，所以逐条 UPDATE 是安全的 ——
--     但下一个动这张表的人要先确认这一点再拆语句。

-- ===== 一、新建五列 =====
--
-- 三个业务字段照抄迁移 020 给买家主体做过的那次（industries_json +
-- industry_l2_json 到 business_tags_json）：行业字典只有 16 个一级行业，
-- 接不住买家的细分主业。
--
-- **但代价与主体侧不同，必须写清楚**：买家主体能用自由标签，是因为它从来
-- 不跨侧匹配（注册表里 buyer_party 的 screening 一律 False，主体没有另一侧）。
-- 买家需求**有另一侧** —— industries_json 曾是正向初筛唯一的行业硬条件，
-- 对手方是 seller_target.industry_pairs_json.l1。跨侧匹配需要共享词表，
-- 这是行业字典存在的唯一理由。所以本次合并同时意味着
-- **正向初筛不再有行业条件**，这不是副作用，是同一个判断的必然结果。
--
-- 支持这么做的实测数据：买家需求人均只填 1.25 个一级行业、二级行业只有 21%
-- 有值，而信息主要落在**不参与匹配的** industry_primary(92%) /
-- industry_secondary(73%) 两个原文列里。行业字典今天已经没在承担业务匹配。
--
-- 地区两列去掉了 region_constraints_json 的 effect 三态，保留省市区三级。
-- required 与 preferred 的区别（「必须在广东」对「优先广东」）交给
-- region_scope_summary 原话承载 —— 那是【召】类字段，12 个字，
-- 语气它表达得比枚举好。排除地区从 effect='excluded' 拆成独立列，
-- 语义写在列名里。贯穿本方案的原则是：语气和强度归文本，阈值和枚举归字段。
alter table buyer_intent
  add column if not exists intent_business_tags_json jsonb not null default '[]'::jsonb,
  add column if not exists intent_business_summary text,
  add column if not exists excluded_business_text text,
  add column if not exists acceptable_regions_json jsonb not null default '[]'::jsonb,
  add column if not exists excluded_regions_json jsonb not null default '[]'::jsonb;

-- ===== 二、回填 =====
--
-- 回填只是把旧内容搬过来，**口径没有重定义**。intent_business_summary 的新口径
-- 是「必须写清要买什么样的业务」（它是反向检索首轮筛选唯一读的东西），
-- 那要靠上线新版 buyer_intent_normalizer 之后批量重跑解析来收敛。

-- 业务标签：三个数组去重合并。照抄 020 给 buyer_party 做的那次。
-- industry_focus_tags_json 一起并进来：它装的「字典外细分方向」恰恰是
-- 自由标签最该有的内容。
update buyer_intent
set intent_business_tags_json = (
  select coalesce(jsonb_agg(tag_name order by tag_name), '[]'::jsonb)
  from (
    select distinct btrim(candidate.value) as tag_name
    from jsonb_array_elements_text(
      case when jsonb_typeof(buyer_intent.industries_json) = 'array' then buyer_intent.industries_json else '[]'::jsonb end
      || case when jsonb_typeof(buyer_intent.industry_l2_json) = 'array' then buyer_intent.industry_l2_json else '[]'::jsonb end
      || case when jsonb_typeof(buyer_intent.industry_focus_tags_json) = 'array' then buyer_intent.industry_focus_tags_json else '[]'::jsonb end
    ) as candidate(value)
    where nullif(btrim(candidate.value), '') is not null
  ) as tags
)
where intent_business_tags_json = '[]'::jsonb;

-- 业务说明：旧摘要 + 两个行业原文列拼成一段。
-- 两个原文列是本次最值钱的存量（92% / 73% 有值），它们此前**不参与任何匹配**，
-- 只做解析溯源 —— 现在它们成了业务匹配的主材料，所以必须带前缀搬过来，
-- 让人和模型都看得出这一行讲的是什么。concat_ws 自动跳过 NULL。
update buyer_intent
set intent_business_summary = nullif(
      concat_ws(
        E'\n',
        nullif(btrim(coalesce(intent_summary, '')), ''),
        case
          when nullif(btrim(coalesce(industry_primary, '')), '') is not null
            then '行业方向：' || btrim(industry_primary)
        end,
        case
          when nullif(btrim(coalesce(industry_secondary, '')), '') is not null
            then '细分方向：' || btrim(industry_secondary)
        end
      ),
      ''
    )
where intent_business_summary is null;

-- 排除方向：数组元素拼成顿号分隔的自由文本。
-- with ordinality 保序，否则同一条需求每次跑出来的顺序不定。
update buyer_intent
set excluded_business_text = (
  select string_agg(btrim(term.value), '、' order by term.ord)
  from jsonb_array_elements_text(
    case when jsonb_typeof(buyer_intent.excluded_industries_json) = 'array' then buyer_intent.excluded_industries_json else '[]'::jsonb end
  ) with ordinality as term(value, ord)
  where nullif(btrim(term.value), '') is not null
)
where excluded_business_text is null
  and jsonb_typeof(excluded_industries_json) = 'array'
  and jsonb_array_length(excluded_industries_json) > 0;

-- 地区：按 effect 拆成两个平铺数组，jsonb_strip_nulls 去掉空层级。
--
-- 只填省 = 全省命中，填到市 = 只匹配那个市，三级逐级独立生效。
-- 空数组 = 不限（不是「没有可接受地区」）—— 这个约定在反向检索里尤其要紧，
-- 反向把空当成「不满足」会让一半以上的买家当场消失。
--
-- jsonb_typeof 的守卫不是多余的：生产里躺着一条
-- {"raw_text":"长三角、珠三角区域","constraint_type":"soft"}，
-- 它是对象不是数组，jsonb_array_elements 碰上会在运行时报错、
-- 整次 preDeploy 迁移挂掉。
update buyer_intent
set acceptable_regions_json = coalesce(
      (
        select jsonb_agg(distinct region.value)
        from jsonb_array_elements(
          case when jsonb_typeof(buyer_intent.region_constraints_json) = 'array' then buyer_intent.region_constraints_json else '[]'::jsonb end
        ) as rc(elem)
        cross join lateral (
          select jsonb_strip_nulls(jsonb_build_object(
            'province', nullif(btrim(coalesce(rc.elem->>'province', '')), ''),
            'city', nullif(btrim(coalesce(rc.elem->>'city', '')), ''),
            'district', nullif(btrim(coalesce(rc.elem->>'district', '')), '')
          )) as value
        ) as region
        where coalesce(rc.elem->>'effect', 'preferred') <> 'excluded'
          and region.value <> '{}'::jsonb
      ),
      '[]'::jsonb
    )
where acceptable_regions_json = '[]'::jsonb;

update buyer_intent
set excluded_regions_json = coalesce(
      (
        select jsonb_agg(distinct region.value)
        from jsonb_array_elements(
          case when jsonb_typeof(buyer_intent.region_constraints_json) = 'array' then buyer_intent.region_constraints_json else '[]'::jsonb end
        ) as rc(elem)
        cross join lateral (
          select jsonb_strip_nulls(jsonb_build_object(
            'province', nullif(btrim(coalesce(rc.elem->>'province', '')), ''),
            'city', nullif(btrim(coalesce(rc.elem->>'city', '')), ''),
            'district', nullif(btrim(coalesce(rc.elem->>'district', '')), '')
          )) as value
        ) as region
        where coalesce(rc.elem->>'effect', 'preferred') = 'excluded'
          and region.value <> '{}'::jsonb
      ),
      '[]'::jsonb
    )
where excluded_regions_json = '[]'::jsonb;

-- ===== 三、形状约束与索引 =====
--
-- 三个 jsonb 列只加形状约束，**不加元素级闭集** —— 业务标签是自由标签，
-- 加闭集就等于把行业字典换个名字请回来，那正是本单要下线的东西。
-- 地区两列的元素是省市区对象，也没有可枚举的闭集。
--
-- GIN 索引照抄 idx_buyer_party_business_tags，访问模式相同
-- （列表页 filter-options 的标签聚合与 `?` 包含查询）。
alter table buyer_intent
  drop constraint if exists chk_buyer_intent_business_tags_json,
  drop constraint if exists chk_buyer_intent_acceptable_regions_json,
  drop constraint if exists chk_buyer_intent_excluded_regions_json;

alter table buyer_intent
  add constraint chk_buyer_intent_business_tags_json
  check (jsonb_typeof(intent_business_tags_json) = 'array'),
  add constraint chk_buyer_intent_acceptable_regions_json
  check (jsonb_typeof(acceptable_regions_json) = 'array'),
  add constraint chk_buyer_intent_excluded_regions_json
  check (jsonb_typeof(excluded_regions_json) = 'array');

create index if not exists idx_buyer_intent_business_tags
  on buyer_intent using gin (intent_business_tags_json)
  where deleted_at is null;

-- ===== 四、删四个孤儿列 =====
--
-- 它们从来没有进过指标注册表，所以既没有中文名、也没有可写来源声明、
-- 更没有对手方 —— 但解析每次都在写。这是「写进去了没人读」的纯负债：
-- 每写一次就要模型判一次「这里有没有这个信息」，而判出来的结果谁也不看。
--
-- 与阶段 B 的区别在于消费方的形状：这四列的读取方全是机械的投影清单
-- （SELECT 列表、Pydantic 模型、前端类型与标签表），一次改完看得见摸得着。
-- 而 industries_json 那一批的读取方带着业务逻辑（字典归一、角标、初筛 SQL），
-- 那些必须先让代码稳定运行一轮再删。
alter table buyer_intent
  drop column if exists acceptable_control_paths_json,
  drop column if exists budget_min_yuan,
  drop column if exists budget_max_yuan,
  drop column if exists relocation_target_regions_json;
