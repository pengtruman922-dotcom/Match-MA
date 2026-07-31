# Match-MA 硬规则

> **本文件是跨工具的单一真源。** Claude Code 经 `CLAUDE.md` 导入本文件，Codex / Cursor 等直接读本文件。
> 规则只维护在这里，不要在别处复制一份，否则必然漂移。

技术栈：FastAPI + PostgreSQL（raw SQL）+ React/TS + Vite。两套部署并存，见下方「部署拓扑」。

**先读图纸**：`docs/系统总纲.md` 是系统的权威描述（业务流程、领域模型、技术决策、死表判决、待办）。做任何跨模块改动前先读它；大改落地后把结论合并回它。`平台优化方案/*.md` 是施工单（进行中与历史），与图纸冲突时以图纸为准。

## 部署拓扑

两套部署**并存且互不影响**，共享同一份代码；差异只在「谁注入环境变量、谁启动进程」。

**Railway（生产，推送自动部署）** —— 生产 API：`https://match-ma-production.up.railway.app/api/v1`

| 服务 | 配置文件 | 说明 |
| --- | --- | --- |
| API | `railway.toml` | preDeploy 跑 `scripts/railway_predeploy.py`（`alembic upgrade head`），迁移失败阻断整个部署 |
| 前端 | `frontend/railway.toml` + `frontend/Caddyfile` | Caddy 静态托管 |
| worker-llm | `railway.worker-llm.toml` | 消费 `llm` 队列（解析、深评、报告、embedding、rerank） |
| worker-ocr | `railway.worker-ocr.toml` | 消费 `ocr` 队列（附件 OCR） |
| worker-research | `railway.worker-research.toml` | 消费 `research` 队列；多副本，stale 窗口 1800s |

服务角色由 `scripts/railway_start.py` 按 `RAILWAY_SERVICE_NAME` / `MATCH_MA_SERVICE_ROLE` 推断。

**自建 Docker Compose（手动部署）** —— 全部产物在 `deploy/`

`deploy/docker-compose.yml` 起 9 个服务：`db`(pgvector/pg17) / `minio` / `minio-init` / `migrate`(一次性 alembic) / `api` / `worker-llm` / `worker-ocr` / `worker-research` / `web`(Caddy，前端 + `/api` 反代做成同源)。启动命令在 compose 里**显式写死**，不经过 `scripts/railway_*.py`。操作手册见 `deploy/README.md`，方案背景见 `平台优化方案/自建部署实施方案0729.md`。

**边界铁律**：`deploy/**` 只服务自建；`railway*.toml` 与 `scripts/railway_*.py` 只服务 Railway。改一侧时不要顺手动另一侧。Railway 的 `builder = "NIXPACKS"` 已锁死，不会误用 `deploy/` 下的 Dockerfile。

## Git 规则

- **推送 `main` 会自动部署 Railway 生产环境**（CI 也在 push main / PR 时跑）。**未经用户明确要求，不要 commit、不要 push。**
- 自建环境是**拉取式**：在服务器上手动 `git pull && docker compose build && docker compose up -d`。推代码不会影响自建环境，直到有人上服务器拉取。
- 服务器上**只 pull，不 commit、不 push**；也不要在服务器上直接改文件（下次 pull 会冲突）。服务器用匿名 HTTPS 克隆公开仓库，不配任何 git 凭证。
- `deploy/.env`、`frontend/.env`、`.match-ma-local-auth.json` 已被 `.gitignore` 排除，含密钥，**绝不提交**（仓库是公开可读的）。

## 测试与验证

- 本地无后端 venv，用 `python -m pytest -q` 跑测试（本机是 Python 3.14，`py -3.11` 不存在）；运行时行为需对生产 API 验证（`scripts/match_ma_api_tools.py`，必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`）。
- 推送涉及后端/迁移的提交后，先轮询生产 `/health` 确认返回的 commit hash 已切换到新提交，再验证业务行为；hash 长时间不变说明部署失败（通常是 preDeploy 迁移挂了），去查迁移而不是继续等。
- GitHub 仓库公开可读：CI 状态可匿名查 `api.github.com/repos/pengtruman922-dotcom/Match-MA/actions/runs`（日志需登录）。

## 数据库迁移

- 2026-07-22 起迁移历史已压平：`database/migrations/001_baseline.sql` 是地板（生产 schema + 种子，含现行 prompt 版本），对应唯一 alembic 修订 `20260722_0048`。**新迁移从 `002_` 起编号**，由 `backend/app/migration_sql.py` 的自制 splitter 解析后经 Alembic 执行（Railway `preDeployCommand = "alembic upgrade head"`，迁移失败会阻断整个部署）。
- 新增迁移文件后必须跑 `tests/test_migration_sql.py` —— 参数化用例对所有迁移文件做 load + split 回归，防止 splitter 切分错误（历史事故：注释里的分号导致语句被切坏、部署失败）。
- CI 的 `Fresh database from baseline` job 会在空库（pgvector/pg17）应用 baseline 并与 `tests/fixtures/schema_snapshot_production.json` 比对，然后 `upgrade head`——改 schema 的新迁移不需要更新该 fixture（比对只发生在 baseline 修订点）。
- schema 依赖 `vector`（pgvector）与 `pg_trgm` 扩展：任何新环境的数据库都必须带这两个扩展，普通 postgres 镜像起不来。

## 同步约束

- 新增 extracted_action 的 action_type 必须同步三处：`backend/app/jobs/handlers/common.py` 的 `ALLOWED_ACTION_TYPES`（经包 `backend.app.jobs.handlers` re-export）、DB check 约束 `chk_extracted_action_type`（需迁移重建）、`extracted_actions.py` 的 apply 分支。`tests/test_action_type_sync.py` 会自动比对三处，漏同步会挂 CI；只记录不落库的类型要加进该测试的 `NON_APPLYABLE_ACTION_TYPES`。
- **新增或改名 worker 队列必须同步两套部署**：Railway 侧加 `railway.worker-<queue>.toml` 并在 `scripts/railway_start.py` 的 `_infer_role` 注册；自建侧在 `deploy/docker-compose.yml` 加对应 service（复用 `x-backend` 锚点）。漏改自建侧会导致该队列的任务在自建环境**静默堆积、无人消费**。
- 新增影响运行时的环境变量时，`backend/app/config.py`、`.env.example`、`deploy/.env.example` 三处都要覆盖到；`deploy/docker-compose.yml` 里 api 与 3 个 worker 共用 `x-backend` 锚点，**不要给单个服务单独加 environment**，否则会破坏「API 与 worker 配置必须一致」这个前提（尤其 `MODEL_SECRET_ENCRYPTION_KEY` 与 S3 配置）。
- `backend/app/jobs/handlers/` 是按任务域拆分的包，`__init__.py` re-export 全部名字；新增 handler 放对应域模块并在 `dispatch.py` 注册，跨域共享的 helper 放 `common.py`（模块依赖必须保持无环）。
- `prompt_template.few_shot_examples_json` 是死存储，不会注入 LLM 消息 —— few-shot 示例必须写进 `user_prompt_template` 正文。
- Prompt 版本通过设置页「Prompt 版本管理」或 `/model-config/prompts` API 维护（新建版本/回滚都即时生效，不需要部署）；**不要再写 prompt seed 迁移**，迁移只管 schema（baseline 里的 prompt 种子是唯一例外，只服务全新安装）。仅当新 prompt 需要新输出字段/新变量时才需要配套代码发版。
