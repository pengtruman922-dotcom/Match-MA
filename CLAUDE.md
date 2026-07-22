# Match-MA 硬规则

技术栈：FastAPI + PostgreSQL（raw SQL）+ React/TS + Vite，部署在 Railway（生产 API：https://match-ma-production.up.railway.app/api/v1）。

**先读图纸**：`docs/系统总纲.md` 是系统的权威描述（业务流程、领域模型、技术决策、死表判决、待办）。做任何跨模块改动前先读它；大改落地后把结论合并回它。`平台优化方案/*.md` 是施工单（进行中与历史），与图纸冲突时以图纸为准。

## 测试与验证
- 本地无后端 venv，用 `python -m pytest -q` 跑测试（本机是 Python 3.14，`py -3.11` 不存在）；运行时行为需对生产 API 验证（`scripts/match_ma_api_tools.py`，必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`）。
- 推送涉及后端/迁移的提交后，先轮询生产 `/health` 确认返回的 commit hash 已切换到新提交，再验证业务行为；hash 长时间不变说明部署失败（通常是 preDeploy 迁移挂了），去查迁移而不是继续等。
- GitHub 仓库公开可读：CI 状态可匿名查 `api.github.com/repos/pengtruman922-dotcom/Match-MA/actions/runs`（日志需登录）。

## 数据库迁移
- 2026-07-22 起迁移历史已压平：`database/migrations/001_baseline.sql` 是地板（生产 schema + 种子，含现行 prompt 版本），对应唯一 alembic 修订 `20260722_0048`。**新迁移从 `002_` 起编号**，由 `backend/app/migration_sql.py` 的自制 splitter 解析后经 Alembic 执行（Railway `preDeployCommand = "alembic upgrade head"`，迁移失败会阻断整个部署）。
- 新增迁移文件后必须跑 `tests/test_migration_sql.py` —— 参数化用例对所有迁移文件做 load + split 回归，防止 splitter 切分错误（历史事故：注释里的分号导致语句被切坏、部署失败）。
- CI 的 `Fresh database from baseline` job 会在空库（pgvector/pg17）应用 baseline 并与 `tests/fixtures/schema_snapshot_production.json` 比对，然后 `upgrade head`——改 schema 的新迁移不需要更新该 fixture（比对只发生在 baseline 修订点）。

## 同步约束
- 新增 extracted_action 的 action_type 必须同步三处：`backend/app/jobs/handlers/common.py` 的 `ALLOWED_ACTION_TYPES`（经包 `backend.app.jobs.handlers` re-export）、DB check 约束 `chk_extracted_action_type`（需迁移重建）、`extracted_actions.py` 的 apply 分支。`tests/test_action_type_sync.py` 会自动比对三处，漏同步会挂 CI；只记录不落库的类型要加进该测试的 `NON_APPLYABLE_ACTION_TYPES`。
- `backend/app/jobs/handlers/` 是按任务域拆分的包，`__init__.py` re-export 全部名字；新增 handler 放对应域模块并在 `dispatch.py` 注册，跨域共享的 helper 放 `common.py`（模块依赖必须保持无环）。
- `prompt_template.few_shot_examples_json` 是死存储，不会注入 LLM 消息 —— few-shot 示例必须写进 `user_prompt_template` 正文。
- Prompt 版本通过设置页「Prompt 版本管理」或 `/model-config/prompts` API 维护（新建版本/回滚都即时生效，不需要部署）；**不要再写 prompt seed 迁移**，迁移只管 schema（baseline 里的 prompt 种子是唯一例外，只服务全新安装）。仅当新 prompt 需要新输出字段/新变量时才需要配套代码发版。
