# P0/P1 修复与调研 Agent 完善开发总结

> 用途：供另一个 AI 对本轮开发进行交叉检查。  
> 项目：Match-MA（FastAPI + PostgreSQL/raw SQL + React/TypeScript）  
> 整理日期：2026-07-21  
> 本轮最终部署提交：`c87208113f04d5e7795a2ebea4d82a8c55cfe9ae`

## 1. 本轮范围与相关提交

本轮主要处理三件事：修复附件解析闭环（P0）、补齐行业维度写回（P1）、让匹配画像能够由附件和调研 Agent 生成并带证据落库。

| 提交 | 内容 |
| --- | --- |
| `d047161` | 建立六栏匹配画像、画像 API/前端和深评读取能力 |
| `133edd3` | 建立可插拔搜索供应商、Tavily 适配、搜索设置页、实体锚点和调研建议表 |
| `d3cfafe` | P0：修复附件解析、动作应用和前端状态闭环 |
| `f8ae342` | P1：补齐 `industry_l1/industry_l2` 的推导、写回、回滚和历史回填 |
| `eb7bf57` | 实现附件画像写入和可执行的标的调研 Agent |
| `ba148e1` | 收紧画像内容，避免融资/估值及财务股东污染定性画像 |
| `2599965` | “业务与产品”改用受约束的业务摘要生成 |
| `c872081` | 拒绝“未详/未知/信息不足”等低信息占位摘要 |

## 2. P0：附件解析闭环修复

### 原问题

创建标的并上传附件后，后台任务可能显示成功，但标的基本信息、推荐状态和部分解析状态仍为空。主要原因是模型输出字段名与后端动作 Schema 不完全一致，以及无效/未应用动作的状态被错误地当成成功。

### 已修改

- 在 `business_update.py` 中兼容模型常见别名：
  - `action` → `action_type`
  - `target` → `target_entity_type`
  - `target_id` → `target_entity_id`
- Schema 校验不通过时不再伪装为成功；无法自动应用的动作保留为 `pending_review`。
- 附件、OCR、专用解析器、动作落库、标的状态回写的状态链路已接通。
- Trace 改为记录真实专用节点名，便于定位具体解析节点。
- 修复前端解析状态展示以及相关 TypeScript/Lint 问题。
- 增加附件/OCR 回归测试，覆盖别名归一化、无效 Schema 和状态写回。

主要文件：

- `backend/app/jobs/handlers/business_update.py`
- `backend/app/jobs/handlers/seller_target_parse.py`
- `backend/app/jobs/handlers/traces.py`
- `frontend/src/features/targets/presentation.tsx`
- `tests/test_attachment_ocr.py`

## 3. P1：行业维度写回修复

### 根因结论

生产行业字典并不缺失：已有 15 个有效 L1、156 个有效 L2。问题是专用更新解析没有把 `industry_l1`、`industry_l2` 纳入规范化和动作应用白名单，因此模型即使给出行业信息，也无法形成推荐可用的标准行业维度。

### 已修改

- 可从 `industry_primary/industry_secondary` 归一化并推导 `industry_l1/industry_l2`。
- 动作白名单、应用、快照和回滚链路均支持 L1/L2。
- 行业 Prompt 字典读取为空时，使用完整 15 类 L1 作为兜底，不再退化成只有“其他”。
- 新增迁移 `046_backfill_seller_industry_l1.sql`，回填已有标的缺失的 L1。
- 同步新增 Alembic 版本 `20260721_0046_backfill_seller_industry_l1.py`。
- 增加行业层级、附件解析和标的解析测试。

生产样本中，原始模型没有直接输出 L1/L2，后端仍成功推导并写入：

```text
industry_l1 = 医药与健康
industry_l2 = 医疗器械
```

主要文件：

- `backend/app/jobs/handlers/business_update.py`
- `backend/app/jobs/handlers/common.py`
- `backend/app/services/extracted_action_apply.py`
- `backend/app/services/industry_taxonomy.py`
- `database/migrations/046_backfill_seller_industry_l1.sql`
- `tests/test_industry_taxonomy_levels.py`

## 4. 匹配画像完善

### 此前画像为空的原因

此前只有 `entity_profile_section` 表、手工编辑界面以及深评读取逻辑；附件解析流程从未向画像表写数据，所以即使附件包含相关内容，六栏匹配画像仍为空。

### 当前实现

附件在同一次 LLM 解析中输出结构化 `profile_sections_json`，后端按标的 ID 解析并写入以下六栏：

1. 业务与产品（`business_product`）
2. 产业链位置与行业地位（`chain_position`）
3. 技术与团队能力（`tech_team`）
4. 经营质量（`ops_quality`）
5. 交易属性与配合度（`deal_terms`）
6. 出售诉求与风险缺口（`sell_intent_risk`）

画像写入规则：

- 用户上传附件视为一手来源；通过校验的画像可以标记为 `auto_accepted`。
- 每个栏目保存来源、证据摘录、日期和置信度；无证据的栏目保持缺失，不强行补全。
- 深评只读取 `accepted` 或 `auto_accepted` 的画像。
- 融资额、估值等信息不会被写入交易画像。
- 财务股东不会被误当成技术/经营团队。
- “未详”“未知”“信息不足”等低信息摘要不能用于填画像。
- OCR 文本仅存在空格差异时，仍允许保留可核验的短证据摘录。
- “业务与产品”使用解析后的受约束业务摘要，避免直接复制附件中无边界的长段内容。

生产附件“苏州中析生物信息有限公司.txt”验证结果：成功形成 5/6 个画像栏目；没有证据的栏目保持空缺，来源、摘录和置信度均成功落库。测试标的在验证后已软删除。

主要文件：

- `backend/app/jobs/handlers/business_update.py`
- `backend/app/services/profile_sections.py`
- `backend/app/api/routes/profile_sections.py`
- `frontend/src/features/targets/ProfileSectionsPanel.tsx`
- `tests/test_profile_sections.py`

## 5. 调研 Agent 完善

### 搜索与执行能力

- 增加可插拔搜索供应商机制和 Tavily 适配器，并在设置页增加搜索供应商配置界面。
- 支持单个标的调研和一次最多 50 个标的的批量调研。
- 调研任务分三组检索：
  - 业务产品、产业链、行业地位
  - 技术、专利、团队、产能、资质
  - 经营、客户、股权、交易、出售、风险
- 调研结果既可形成六栏画像建议，也可形成标准结构化字段建议。

### 实体锚定与证据约束

- 支持的强锚点：统一社会信用代码、官网域名。
- 支持的组合锚点：法定名称 + 独立的注册地或法人。
- 公司名称中自带的地区词不能再次充当独立地区锚点，降低同名公司串线概率。
- 每条结论必须引用可信 `evidence_ref`，同时保存来源 URL、标题和证据摘录。
- 无公网信息时记录 `no_public_information`，并设置 30 天后可重试，不生成虚假建议。

### 冲突处理和人工复核

调研结果按四种关系分类：

- `consistent`：与现有信息一致
- `supplement`：补充现有缺失信息
- `temporal_update`：不同时点的新信息
- `same_period_conflict`：同一时期相互冲突

处理规则：

- 高权威且满足锚定/证据要求的画像补充可自动采纳。
- 普通网页来源、结构化字段和冲突信息进入 `pending_review`。
- 前端支持查看证据并“确认”或“忽略”建议。
- 确认结构化字段后，写入应用日志和字段来源，保留审计链。

新增 API（均位于 `/api/v1/research`）：

- `POST /seller-targets/{seller_target_id}`：发起单个调研
- `POST /seller-targets`：批量发起调研
- `GET /seller-targets/{seller_target_id}/status`：查询调研状态
- `GET /proposals`：查询调研建议
- `POST /proposals/{proposal_id}/accept`：确认建议
- `POST /proposals/{proposal_id}/reject`：忽略建议

主要文件：

- `backend/app/api/routes/research.py`
- `backend/app/jobs/handlers/research.py`
- `backend/app/services/research_anchor.py`
- `backend/app/services/search_service.py`
- `backend/app/services/search_providers/`
- `frontend/src/features/settings/SearchProviderSection.tsx`
- `frontend/src/features/targets/ProfileSectionsPanel.tsx`
- `tests/test_research_agent.py`
- `tests/test_research_anchor.py`

## 6. 生产配置与当前明确限制

已通过生产 API 配置（配置不在 Git 迁移中）：

- LLM 节点：`seller_target_researcher`
- 调研 Prompt：`v0.1.0`
- 附件解析 Prompt：`seller_target_update_parser v0.1.4`

当前明确未完成的外部配置：

- 生产 `/search-config/overview` 目前返回空列表，尚未配置 Tavily。
- 在搜索供应商配置完成前，调研入口会明确返回 HTTP 409，而不是生成无来源数据。
- 因此调研代码、队列和复核界面已经完成，但“真实公网搜索 → LLM 结论 → 建议确认”的生产端到端测试仍需在配置合法 Tavily Key 后执行。
- 本轮没有臆造、读取或写入任何 Tavily Key。

## 7. 测试与生产验证

已完成：

- Python 3.14：`393 passed`
- 前端 `npm run typecheck`：通过
- 前端 `npm run build`：通过
- 前端 `npm run lint`：0 error；18 个原有 warning
- Railway API、前端、OCR Worker、LLM Worker 均已运行到提交：`c87208113f04d5e7795a2ebea4d82a8c55cfe9ae`
- 生产附件解析、行业推导、画像落库和证据保存已做实际 API 验证。

本地复核命令：

```powershell
cd D:\Match-MA_v1.0
py -3.14 -m pytest -q
py -3.14 -m pytest -q tests/test_migration_sql.py tests/test_action_type_sync.py
cd frontend
npm run typecheck
npm run build
npm run lint
```

生产验证应从仓库根目录运行 `scripts/match_ma_api_tools.py`，认证信息从 `.match-ma-local-auth.json` 读取，不要把 token 写入代码或本文档。

保留用于审计的生产业务更新记录（均有 `test_data` 标记）：

- `a1a514e7-1e23-4893-bd54-1f4a1bcf6987`
- `7f6dc764-fafa-4bcb-bac7-a189e13f8f68`
- `2aee76f6-ca4d-4215-ace7-4048fee7d539`

## 8. 建议交叉检查的重点

请重点检查以下内容，并区分代码缺陷与“尚未配置 Tavily”造成的 409：

1. `profile_sections_json` 的 JSON 结构、标的 ID 绑定、证据摘录校验是否存在错位或越权写入风险。
2. 六栏画像的清洗规则是否会误删有效信息，尤其是团队、交易意愿、估值/融资边界和 OCR 文本差异。
3. `industry_primary/industry_secondary` 到 L1/L2 的推导，在多 L2、别名、无字典命中和“其他”场景是否稳定。
4. 调研实体锚点能否可靠隔离同名公司、集团母子公司、曾用名和名称中自带地区的公司。
5. `consistent/supplement/temporal_update/same_period_conflict` 的分类和自动采纳阈值是否符合业务预期。
6. 调研任务重复提交、Worker 重试、部分搜索失败时是否幂等，是否会产生重复建议或覆盖已人工确认的画像。
7. 接受/拒绝建议的团队与工作区权限、字段来源、操作日志、快照和回滚链是否完整。
8. 搜索结果正文抓取是否有超时、恶意页面、无效 URL、来源可信度和提示词注入防护问题。
9. 配置 Tavily 后补做生产端到端测试：单标的、批量、无结果、同名实体、同周期冲突和人工确认六类场景。
10. Prompt 版本通过设置页或 `/model-config/prompts` 管理，不要新增 Prompt seed 迁移；若修改输出字段，需同步检查后端解析和前端类型。

## 9. 本轮未做的事项

- 未设计或建设 Golden Set；由业务侧后续确定样本和判定标准。
- 未配置第三方搜索密钥。
- 未更改推荐深评为多阶段；仍遵循“一次深评、结构化输出、按标的 ID 回写”的方向。
- 未把“行业龙头、链主、技术团队、小而美”等定性条件下推到 SQL；这些条件仍应由画像和 LLM 深评处理。
