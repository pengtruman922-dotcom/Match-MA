# Match-MA 自建部署操作手册

与 Railway 部署**并行存在、互不影响**。本目录下的所有文件只服务自建环境；
Railway 侧的 `railway*.toml` 与 `scripts/railway_*.py` 保持原样，两条链路物理隔离。

方案背景与设计取舍见 `平台优化方案/自建部署实施方案0729.md`。

---

## 架构

```text
                    ┌──────── 唯一对外端口 :80 ────────┐
  浏览器 ──────────▶ │  web (Caddy)  静态前端 + /api 反代 │
                    └────────────────┬─────────────────┘
                                     │  /api/* → api:8000（同源，免 CORS）
   Docker 内网       ┌───────────────┼──────────────────────────────┐
   (match-ma_default)│  api (uvicorn :8000)                         │
                     │  worker-llm       --queue llm                │
                     │  worker-ocr       --queue ocr                │
                     │  worker-research  --queue research           │
                     │  migrate     一次性 alembic upgrade head      │
                     │  db      pgvector/pgvector:pg17  :5432       │
                     │  minio   对象存储 :9000 / 控制台 :9001         │
                     └──────────────────────────────────────────────┘
   持久卷：pgdata · minio-data · attachments · caddy-data · caddy-config
```

db 的 5432 与 MinIO 控制台 9001 **只绑宿主机回环地址**，公网不可达，需要时走 SSH 隧道。

---

## 一、首次部署

### 1. 准备代码

```bash
cd /opt && git clone https://github.com/pengtruman922-dotcom/Match-MA.git match-ma && cd match-ma/deploy
```

### 2. 生成密钥并填写 .env

```bash
cp .env.example .env && chmod 600 .env
```

一次性生成全部随机值（把输出逐项填进 `.env`）：

```bash
python3 - <<'EOF'
import secrets
print("POSTGRES_PASSWORD      =", secrets.token_urlsafe(24))
print("ADMIN_PASSWORD         =", secrets.token_urlsafe(24))
print("ADMIN_TOKEN            =", secrets.token_urlsafe(48))
print("AUTH_JWT_SECRET        =", secrets.token_urlsafe(48))
print("MINIO_ROOT_PASSWORD    =", secrets.token_urlsafe(24))
EOF
```

Fernet 加密密钥（格式特殊，必须单独生成）：

```bash
docker run --rm python:3.12-slim sh -c "pip install -q cryptography && python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'"
```

把它填进 `MODEL_SECRET_ENCRYPTION_KEY`。

> `.env` 里 `ADMIN_PASSWORD` 等留空或用默认值时，`APP_ENV=production` 会让应用**拒绝启动**并打印缺哪一项。这是设计好的保护，按提示补齐即可。

### 3. 构建并启动

```bash
docker compose build
```

```bash
docker compose up -d
```

### 4. 确认迁移成功

```bash
docker compose logs migrate
```

应看到 alembic 执行日志且容器以 exit 0 结束。迁移失败会阻断 api 与所有 worker 启动 —— 这时去看日志排查，不要重复 `up`。

### 5. 查看整体状态

```bash
docker compose ps
```

---

## 二、冒烟验证

```bash
curl -s localhost/api/v1/health
```

```bash
curl -s localhost/api/v1/health/db
```

```bash
curl -s localhost/api/v1/meta/seed-status
```

依次应返回 `status: ok`、`database: reachable`、以及默认 team/workspace/admin 与各字典均已写入。

然后浏览器打开 `http://<服务器公网IP>`，用 `.env` 里的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录，并完成：

- [ ] 「AI 设置」录入国内厂商模型 key（通义千问 / DeepSeek / 智谱 / Kimi 等）
- [ ] 新建一条买家需求，跑通解析（验证 worker-llm + 密钥解密）
- [ ] 上传一个附件（验证 MinIO 读写链路）
- [ ] 新建一个标的并发起推荐（验证 worker-research + rerank）

附件存储配置自检（该接口需鉴权，用 `.env` 里的 `ADMIN_TOKEN`）：

```bash
curl -s -H "Authorization: Bearer $(grep '^ADMIN_TOKEN=' .env | cut -d= -f2-)" localhost/api/v1/meta/ai-infra-status
```

看返回里的 `storage` 段：`attachment_storage_backend` 应为 `s3`，
`s3_configured` 及各项 `*_configured` 应均为 `true`。同一接口的 `ocr` 段可确认 OCR provider。

---

## 三、日常运维

### 更新到最新代码

```bash
git pull && docker compose build && docker compose up -d
```

`migrate` 会自动跑新增迁移。

### 看日志

```bash
docker compose logs -f api
```

把 `api` 换成 `worker-llm` / `worker-ocr` / `worker-research` / `db` / `minio` 查对应服务。

### 扩调研并发

```bash
docker compose up -d --scale worker-research=3
```

stale 窗口已设 1800s，多副本不会互相判死。

### 数据库备份

```bash
docker compose exec -T db pg_dump -U match_ma match_ma | gzip > /root/backup/match-ma-$(date +%F).sql.gz
```

建议加进 crontab 每日执行，并定期清理旧文件。

### 附件备份

```bash
docker run --rm -v match-ma_minio-data:/data -v /root/backup:/backup alpine tar czf /backup/minio-$(date +%F).tar.gz -C /data .
```

### 磁盘清理（本机只有 40G 单盘，建议定期执行）

```bash
docker system df
```

```bash
docker image prune -af && docker builder prune -af
```

### 访问 MinIO 控制台

控制台只绑回环，从**你本地电脑**建隧道：

```bash
ssh -L 9001:127.0.0.1:9001 <用户名>@<服务器IP>
```

然后本地浏览器打开 `http://localhost:9001`，用 `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` 登录。

---

## 四、常见问题

| 现象 | 原因与处理 |
|---|---|
| 应用启动即退出，日志有 `Refusing to start with insecure auth configuration` | `.env` 鉴权项没填全，按日志列出的条目补齐 |
| 浏览器打不开，但 `curl localhost` 正常 | 阿里云**安全组**没放行 80 端口 |
| 解析任务一直排队不动 | 看 `docker compose logs worker-llm`；多为模型 key 未录入或厂商不可达 |
| 附件上传成功但解析报读不到文件 | 检查 api 与 worker 的 S3 配置是否一致（本编排由同一份 .env 提供，正常不会发生） |
| `docker compose build` 前端阶段 OOM | 本机 8G 足够；若确有问题，先 `docker compose stop` 再 build |
| 镜像拉取超时 | 配置 Docker 国内镜像加速（见下） |

Docker 镜像加速配置：

```bash
mkdir -p /etc/docker && cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://docker.m.daocloud.io", "https://dockerproxy.com"]
}
EOF
systemctl restart docker
```

---

## 五、安全基线

- 安全组只放行 **80/443**，22 限制到固定来源 IP。
- **绝不**对公网开放 5432（数据库）、9000/9001（MinIO）、8000（API）—— 本编排已默认只绑回环。
- `.env` 权限 600，且已在 `.gitignore` 中排除（仓库是公开的，务必确认）。
- 生产化时建议：为应用单独建 MinIO 服务账号（而非用 root 凭据）、绑域名启用 HTTPS、关闭 SSH 密码登录改用密钥。
