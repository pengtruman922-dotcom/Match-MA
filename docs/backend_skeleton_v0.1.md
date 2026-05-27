# Match-MA 后端工程骨架 v0.1

日期：2026-05-27

范围：把 Match-MA 从方案文档推进到可运行后端基线。当前只搭建 FastAPI / SQLAlchemy / Alembic / 配置 / 健康检查，不实现具体业务 API。

---

## 1. 技术基线

一期后端采用：

- FastAPI：HTTP API。
- SQLAlchemy 2.x：数据库连接、事务和后续 ORM。
- Alembic：数据库迁移入口。
- PostgreSQL + pgvector：主数据库和向量召回底座。
- pydantic-settings：环境变量和 `.env` 配置。

当前目录：

```text
backend/
  app/
    main.py
    config.py
    db.py
    api/
      router.py
      routes/
        health.py

alembic/
  env.py
  versions/
    20260527_0001_initial_schema.py
    20260527_0002_seed_defaults.py
    20260527_0003_seed_reference_config.py

database/
  migrations/
    001_initial_schema.sql
    002_seed_defaults.sql
    003_seed_reference_config.sql
```

---

## 2. 迁移策略

当前 `database/migrations/*.sql` 是讨论阶段固化出来的 SQL 基线。

Alembic 版本文件暂时不重复内联大段 SQL，而是读取对应 SQL 文件执行：

```text
20260527_0001 -> 001_initial_schema.sql
20260527_0002 -> 002_seed_defaults.sql
20260527_0003 -> 003_seed_reference_config.sql
```

执行时会去掉 SQL 文件里的 `begin; / commit;`，由 Alembic 统一管理事务。

当前 SQL 文件没有 PL/pgSQL 函数体和字符串内分号，Alembic 版本中会按分号拆分执行。后续如果 migration 中出现函数、trigger body 或复杂 SQL，应改为 Alembic `op.execute()` 显式编写或使用更严格的 SQL 分割工具。

后续进入正式开发后，可以逐步切换为：

- SQLAlchemy ORM 模型。
- Alembic autogenerate。
- 每次业务 schema 变更单独 migration。

---

## 3. 本地运行

```powershell
cd C:\Users\MP\search-toolkit\Match-MA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

编辑 `.env`：

```text
DATABASE_URL=postgresql+psycopg://match_ma:match_ma@localhost:5432/match_ma
```

执行迁移：

```powershell
alembic upgrade head
```

启动 API：

```powershell
uvicorn backend.app.main:app --reload
```

健康检查：

```text
GET http://localhost:8000/api/v1/health
GET http://localhost:8000/api/v1/health/db
```

---

## 4. 当前限制

- 本机尚未执行真实 PostgreSQL migration 校验。
- `pgvector` 扩展必须在目标 PostgreSQL 环境可用，否则 `create extension vector` 会失败。
- 当前还没有业务 ORM 模型，schema 仍以 SQL 文件为准。
- Alembic downgrade 暂不支持，避免误删早期业务数据。
- 权限字段已进入 schema，但真实鉴权和 RLS 尚未实现。

---

## 5. 下一步

建议下一步进入两个并行方向：

1. 工程方向：验证 PostgreSQL / pgvector 环境，跑通 `alembic upgrade head`。
2. 业务方向：定义第一批核心 API 草案，包括新建标的、新建买家意向、统一业务更新、推荐会话。
