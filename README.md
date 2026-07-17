# Match-MA

Match-MA 是面向内部咨询公司的并购标的与买家需求撮合管理平台：管理卖方标的、买家及其并购意向，通过 AI 解析统一业务更新（文字/截图/附件），并提供双向智能推荐（为买家找标的、为标的找买家）。

## 技术栈

- 后端：FastAPI + PostgreSQL（raw SQL，含 pgvector），Alembic 执行 `database/migrations/*.sql` 迁移
- 前端：React 18 + TypeScript + Vite + Tailwind CSS
- 后台任务：PostgreSQL 表队列（`FOR UPDATE SKIP LOCKED`），独立 worker 进程消费
- AI：可配置模型节点（LLM / OCR / embedding / rerank），prompt 版本化存库，Doc2X PDF OCR，多模态图片识别

## 仓库结构

```text
backend/app/          FastAPI 应用
  api/routes/         API 路由（/api/v1/...）
  jobs/               后台任务队列与 handler
  services/           业务服务（附件存储、行业字典、搜索文档等）
  ai/                 模型客户端（LLM / OCR / embedding / rerank / Doc2X）
  worker.py           worker 入口（--queue llm|ocr|default）
database/migrations/  SQL 迁移（编号递增，经 backend/app/migration_sql.py 切分后由 Alembic 执行）
alembic/versions/     与 SQL 迁移一一对应的 Alembic 壳
frontend/             React 前端
tests/                pytest 测试（不依赖真实数据库）
scripts/              部署与 API 验证脚本
docs/                 产品与技术设计文档（v0.1 系列）
```

## 本地开发

后端（Python 3.11+）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q          # 全量测试，无需数据库
```

前端（Node 20）：

```powershell
cd frontend
npm ci
npm run dev                  # 开发服务器
npm run typecheck            # 类型检查
npm run build                # 生产构建
```

## 部署（Railway）

生产 API：`https://match-ma-production.up.railway.app/api/v1`

| 服务 | 配置 | 说明 |
| --- | --- | --- |
| API | `railway.toml` | preDeploy 跑迁移（`scripts/railway_predeploy.py`），迁移失败会阻断部署 |
| 前端 | `frontend/railway.toml` + Caddy | 静态托管 |
| worker-llm | `railway.worker-llm.toml` | 消费 `llm` 队列（解析、推荐深评、报告生成） |
| worker-ocr | `railway.worker-ocr.toml` | 消费 `ocr` 队列（附件 OCR） |

部署后先轮询 `/api/v1/health` 确认返回的 commit hash 已切换，再验证业务行为；hash 长时间不变通常是 preDeploy 迁移失败。

## 迁移注意事项

- 新增迁移 = `database/migrations/NNN_*.sql` + 对应 `alembic/versions/` 壳文件。
- 新增迁移后必须跑 `tests/test_migration_sql.py`（对所有迁移做 load + split 回归，防止自制 splitter 切分错误）。
- 其余硬规则见 [CLAUDE.md](CLAUDE.md)。

## CI

GitHub Actions（`.github/workflows/ci.yml`）在每次推送 main 和 PR 时自动跑：后端 pytest（Python 3.11）、前端 typecheck + build（Node 20）。

## 文档

`docs/` 下为 v0.1 系列设计文档，入口：

- `docs/prd_v0.1.md`：产品需求
- `docs/confirmed_product_and_tech_plan_v0.1.md`：已确认的产品与技术方案（最全）
- `docs/data_model_v0.1.md` / `docs/postgres_schema_v0.1.md`：数据模型与 schema
- `docs/ai_task_architecture_v0.1.md`：AI 后台任务架构
- 其余按文件名对应各功能域（推荐、附件 OCR、后台任务、模型配置等）

API 端点以代码为准（`backend/app/api/routes/`），或启动服务后查看 `/docs`（FastAPI 自动文档）。
