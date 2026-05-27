# Match-MA Railway 部署记录 v0.1

日期：2026-05-27

范围：记录 Match-MA 在 Railway 上创建测试环境、连接 PostgreSQL、执行 Alembic migration 和健康检查的已验证配置。

---

## 1. 当前部署结论

当前 Railway 测试环境已跑通：

```text
GET /api/v1/health
GET /api/v1/health/db
```

已验证结果：

```json
{"status":"ok","app":"Match-MA API","environment":"staging"}
```

```json
{"status":"ok","database":"reachable"}
```

说明：

- FastAPI 服务正常启动。
- Railway public domain 正常转发。
- PostgreSQL 连接正常。
- Alembic migration 已能在部署前执行。
- `DATABASE_URL` 已正确注入应用服务。

---

## 2. Railway 服务结构

建议每个环境使用独立 Railway Project。

当前测试环境建议结构：

```text
Railway Project: Match-MA

Services:
- Match-MA Web/API Service
- Postgres Database Service
```

不要复用旧 `dd-report-generator` 的 Railway 项目，避免旧数据、旧 Volume、旧环境变量污染新系统。

---

## 3. 应用服务变量

应用服务 Variables 建议：

```text
APP_NAME=Match-MA API
APP_ENV=staging
DEBUG=false
DATABASE_URL=${{ Postgres.DATABASE_URL }}
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

说明：

- `DATABASE_URL` 必须配置在应用服务上，不是只配置在 Postgres 服务上。
- 如果 Railway 中 PostgreSQL 服务名不是 `Postgres`，变量引用里的服务名需要同步修改。
- Railway 常见 `DATABASE_URL` 格式是 `postgresql://...`，应用内会自动转换为 SQLAlchemy/psycopg 可用的 `postgresql+psycopg://...`。

---

## 4. railway.toml

当前 `railway.toml`：

```toml
[build]
builder = "NIXPACKS"

[deploy]
preDeployCommand = "alembic upgrade head"
startCommand = "uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/api/v1/health"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

含义：

- 部署前先执行数据库 migration。
- 应用使用 Railway 注入的 `$PORT` 启动。
- Railway 用 `/api/v1/health` 做健康检查。

---

## 5. 关键坑：Public Networking Target Port

本次部署最关键的问题是公网 502。

现象：

```text
Application failed to respond
```

但 Deploy Logs 显示：

```text
Uvicorn running on http://0.0.0.0:8080
GET /api/v1/health HTTP/1.1" 200 OK
```

原因：

```text
Railway 内部健康检查已打通，但 Public Networking 的 Target Port 没有指向应用实际监听端口。
```

解决：

```text
Match-MA 服务 -> Settings -> Networking -> Public Networking -> Target Port = 8080
```

修改后公网健康检查成功。

注意：后续如果 Railway 分配的 `$PORT` 变化，应以 Deploy Logs 里的 `Uvicorn running on http://0.0.0.0:xxxx` 为准，确认 Public Networking Target Port。

---

## 6. 验证接口

基础健康检查：

```text
https://match-ma-production.up.railway.app/api/v1/health
```

数据库健康检查：

```text
https://match-ma-production.up.railway.app/api/v1/health/db
```

Seed 检查：

```text
https://match-ma-production.up.railway.app/api/v1/meta/seed-status
```

Seed 检查用于确认：

- 默认 team 是否存在。
- 默认 workspace 是否存在。
- 默认 admin user 是否存在。
- 行业、交易路径、支付方式、控制路径、风险字典是否已写入。
- 区域别名配置是否已写入。

---

## 7. 后续部署原则

一期建议：

- Railway 只作为测试 / staging。
- 不要上传真实客户数据。
- 每次 schema 变更通过 Alembic migration。
- 对外 URL 暂时只用于内部验证。
- 等核心 API 和基础 UI 跑通后，再设计生产环境隔离。

