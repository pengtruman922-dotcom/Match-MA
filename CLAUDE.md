# Match-MA 硬规则

技术栈：FastAPI + PostgreSQL（raw SQL）+ React/TS + Vite，部署在 Railway（生产 API：https://match-ma-production.up.railway.app/api/v1）。

## 测试与验证
- 本地无后端 venv，用 `py -3.11 -m pytest -q` 跑测试；运行时行为需对生产 API 验证（`scripts/match_ma_api_tools.py`，必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`）。
- 推送涉及后端/迁移的提交后，先轮询生产 `/health` 确认返回的 commit hash 已切换到新提交，再验证业务行为；hash 长时间不变说明部署失败（通常是 preDeploy 迁移挂了），去查迁移而不是继续等。

## 数据库迁移
- 迁移是 `database/migrations/*.sql`，由 `backend/app/migration_sql.py` 的自制 splitter 解析后经 Alembic 执行（Railway `preDeployCommand = "alembic upgrade head"`，迁移失败会阻断整个部署）。
- 新增迁移文件后必须跑 `tests/test_migration_sql.py` —— 其中的参数化用例会对所有迁移文件做 load + split 回归，防止 splitter 切分错误（历史事故：注释里的分号导致语句被切坏、部署失败）。

## 同步约束
- 新增 extracted_action 的 action_type 必须同步三处：`handlers.py` 的 `ALLOWED_ACTION_TYPES`、DB check 约束 `chk_extracted_action_type`（需迁移重建）、`extracted_actions.py` 的 apply 分支。
- `prompt_template.few_shot_examples_json` 是死存储，不会注入 LLM 消息 —— few-shot 示例必须写进 `user_prompt_template` 正文；新版本 prompt 通过迁移 seed，并把同 node 旧版本的 `is_default` 置 false。
