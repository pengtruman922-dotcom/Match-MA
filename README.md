# Match-MA

Match-MA 是面向内部咨询公司 / 中间方团队的并购标的与买家需求撮合管理平台草案项目。

计划 GitHub 仓库：<https://github.com/pengtruman922-dotcom/Match-MA>

## 当前文档

- `docs/domain_model_and_user_scenarios_v0.1.md`：领域模型与用户场景初稿。
- `docs/technical_research_v0.1.md`：候选池、检索、LLM 推荐、连续对话和部署架构调研。
- `docs/confirmed_product_and_tech_plan_v0.1.md`：截至当前已确认的产品与技术方案，包括新建标的、统一业务更新、买家管理和智能推荐流程。
- `docs/data_model_v0.1.md`：核心数据库表结构草案，包括标的、买家意向、买家-标的关系、推荐会话、附件证据和业务更新。
- `docs/phase1_field_scope_v0.1.md`：一期字段收敛草案，区分 `seller_target` / `buyer_intent` 的 P0/P1/P2 字段、constraint 规则和轻量证据策略。
- `docs/buyer_intent_constraint_whitelist_v0.1.md`：买家意向 constraint 白名单，定义一期允许的 field/operator/value_json/unknown_policy 和解析示例。
- `docs/risk_taxonomy_v0.1.md`：风险枚举与负面清单草案，定义 `risk_type`、`risk_status`、`severity`、风险写入和推荐过滤规则。
- `docs/postgres_schema_v0.1.md`：PostgreSQL schema 草案，包含核心表 DDL、约束、索引、pgvector search_doc 和迁移注意事项。
- `docs/backend_skeleton_v0.1.md`：后端工程骨架说明，包含 FastAPI / SQLAlchemy / Alembic / 健康检查 / 本地运行方式。

## 数据库草案

- `database/migrations/001_initial_schema.sql`：一期 PostgreSQL 初始化 schema SQL，按当前讨论稿拆出，可作为后续 Alembic/ORM 迁移的基线。
- `database/migrations/002_seed_defaults.sql`：一期默认 seed，包含默认团队、默认数据空间、管理员用户和最小 fallback 标签。
- `database/migrations/003_seed_reference_config.sql`：一期参考配置 seed，包含非穷尽一级行业、交易路径、支付方式、控制路径、P0 风险字典和区域别名展开配置。

## 后端骨架

当前已创建 FastAPI 后端基线：

```text
backend/app/main.py
backend/app/config.py
backend/app/db.py
backend/app/api/routes/health.py
alembic/
```

本地运行参考：

```powershell
cd C:\Users\MP\search-toolkit\Match-MA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
alembic upgrade head
uvicorn backend.app.main:app --reload
```

健康检查：

```text
GET /api/v1/health
GET /api/v1/health/db
```

## 当前已确认方向

- 新系统独立于旧 FastGPT 方案，不复用 FastGPT 相关能力。
- 主检索底座一期采用 PostgreSQL + pgvector。
- LLM 意向解析采用 filter DSL，由服务端转参数化 SQL。
- 推荐支持双向模式：为买家找标的、为标的找买家。
- 统一业务更新入口支持混合文字、截图、附件，由 AI 拆分后默认待复核。
- 字典采用轻量归一化策略：不要求一期全覆盖，LLM 先抽取原文，服务端召回小候选集后归一化；低置信度进入待归一化/待复核。
- 区域别名采用配置表辅助买家意向解析，例如长三角、江浙沪、珠三角；标的侧仍只保存事实地区字段。

说明：这是全新项目草案目录，暂不初始化 Git，也不推送 GitHub。
