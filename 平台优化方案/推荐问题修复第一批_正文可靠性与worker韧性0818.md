# 推荐问题修复 · 第一批施工单：正文可靠性与 worker 韧性

> 2026-08-18 立项。四批问题的排查见本文件第一节（结论已在代码中逐条核实）。
> **本批只动后端**，SSE 契约保持不变，前端一行不改也能跑通。
> 前端交互在第二批，对话语义与节点配置在第三批。三批**串行**。

## 零、这一批解决什么

线上四个问题里的**两个根因**：

- **问题四**「已完成的会话变黄点、重开又重新回答」—— 正文落库挂在浏览器把 SSE 消费完这件事上
- **问题一里的真实失败部分** —— worker 被部署打断后挂 30 分钟；以及吞异常毒化 session 导致的 `InFailedSqlTransaction`

不在本批：前端假超时、轮询节奏、重试展示、澄清框（第二批）；节点超时语义、节点目录清理、中止轮进上下文（第三批）。

## 一、根因（已核实，附证据行号）

### 1.1 正文落库挂在客户端连接上

`stream_recommendation_answer` 的生成器把 `persist()` 放在流循环**之后**
（`backend/app/api/routes/recommendations.py:530`）。客户端一断开，生成器停在某次 `yield`，
`persist()` 永不执行 —— **整段已经付费生成的正文直接丢失**。

而 Writer 是**前端发起**的：worker 的 agent job 刻意停在 brief
（`backend/app/jobs/handlers/recommendation.py:136` 的 docstring 明写
"The turn deliberately stops at the brief"），前端轮询看到 brief 才去调 `/answer-stream`。
**所以关掉页签 = 没有任何人会写正文。**

`_build_recommendation_agent_status` 没判错：有 brief、无 answer/abort，只能是 `writing`
（`backend/app/services/recommendation_flow.py:282`）。黄点正确地反映了数据缺失，
**不能把 brief 当完成来掩盖 —— 那只是把数据丢失藏起来。**

生产证据：会话 `80d89a72…` brief 到 answer 相隔 43,999 秒（约 12 小时 13 分），
而最终 Writer 真实耗时只有 46.7 秒；`83b5ac9d…` 空挂约 29 分钟；`6edf62e8…` 空挂约 6.6 分钟。
目前库里没有遗留的「有 brief 无 answer」轮次，是因为重开会话触发了自动补连、**重新生成并重新付费了一次**。

### 1.2 worker 没有信号处理

`backend/app/worker.py` 全文没有 SIGTERM / SIGINT 处理。Railway 部署时发 SIGTERM 再 SIGKILL，
正在跑的 job 进程直接消失；`locked_at` 只在领取时写一次（`backend/app/jobs/queue.py:117`），
运行期间从不刷新，因此只能等 `--stale-after 1800`（`scripts/railway_start.py:22`）的扫描回收。
agent job `max_attempts=1`，被回收即 `failed`。

对照一下：Agent 墙钟预算 240 秒（`backend/app/jobs/handlers/recommendation.py:67`），
单次调用最长按节点配置（生产 600 秒），**怎么算都到不了 1800 秒**。
所以 8 月 18 日那 3 个 `stale_running_job` 极大概率是**部署窗口打断**，不是模型慢。
`AGENTS.md` 自己就写了「避免连续部署再次中断正在运行的 worker job」。

→ heartbeat 只是把暴露窗口从 30 分钟缩到几十秒，**治本是优雅退出**。

### 1.3 吞异常毒化 session

`ToolContext._emit_step` 用 `except Exception: pass` 吞掉进度回写失败
（`backend/app/services/recommendation_agent_tools.py:283`），`backend/app/ai/tool_loop.py` 同理。

而 handler 是 **inline commit 模式**：`backend/app/jobs/handlers/recommendation.py` 里有 8 处
裸 `db.commit()`（185/228/271/298/319/402/440/526），全部共用 worker 传进来的同一个 session。
一旦某次 `db.execute` 抛错被吞掉，session 进入 aborted 状态，
**下一次查询才报 `InFailedSqlTransaction`，最初的真实错误永远丢失**。

## 二、做什么

### 2.1 Writer 归 worker（问题四根治）

**方案：把 agent job 的终点从 brief 推到 answer；`/answer-stream` 退化成订阅。**

⚠️ **不要在 API 侧做 lease + 生产者线程。** API 在 Railway 上会重启、会多副本，进程内的生产者
跟着死；没有 Redis，跨进程协调只能靠 DB —— 最后等于把 job 表的原子领取和 stale 回收
在 API 里重新发明一遍。job 表已经有这两样，直接用。

这么改还顺带**省掉一次「前端轮询 → 看到 brief → 再发起 SSE → API 再调模型」的往返**，
正好抵消第二批把轮询放慢的代价。两批是配套的。

具体：

1. `run_recommendation_agent_turn` 写完 `agent_brief` 后**继续**执行 Writer：
   - 复用 `stream_openai_compatible_chat`，增量攒进内存
   - **节流落草稿**：每累计约 500ms 或约 20 个 delta，把当前全文写进草稿行并 commit
     （沿用 handler 现有的 inline `db.commit()` 模式）
   - 上游正常收尾 → 走现有 `sanitize_writer_output` / `backfill_target_links` → 写 `agent_answer`
   - 上游异常 → 写规则兜底正文（`fallback_answer_markdown`），仍写 `agent_answer`，
     `generation_mode="fallback"`
   - **绝不把半截草稿升格成 answer**
2. 新迁移 `database/migrations/002_*.sql`：草稿表（`session_id` + `turn_id` 唯一、
   `markdown text`、`updated_at`）。加完**必须**跑 `tests/test_migration_sql.py`。
3. abort 优先不变：每次 flush 前查 `agent_turn_aborted`，一旦为真立即停止生产、
   清掉草稿、不写 answer。
4. `/answer-stream` 改成纯订阅：
   - 已有 `agent_answer` → 回放（现有分支不动）
   - 有草稿 / job 在跑 → 轮询草稿行（约 300ms），把新增部分作为 `delta` 发出；
     出现 `agent_answer` 后发 `done` 收尾
   - job 已终态失败且无 answer → 发 `error`
   - **浏览器看到的 SSE 契约（`delta` / `done` / `error` / `aborted`）保持不变** —— 前端本批不用改
5. 墙钟预算要覆盖 Writer：`AGENT_WALL_CLOCK_BUDGET_SECONDS`（240）现在只管编排段。
   Writer 实测约 47 秒，进 job 后 job 总时长变长。**本批先把 Writer 段单独计时、单独设上限**
   （沿用 Writer 节点的 `timeout_seconds`），不要把两段混成一个数 —— 统一超时语义是第三批的事。

### 2.2 worker 优雅退出 + heartbeat

1. `backend/app/worker.py` 注册 SIGTERM / SIGINT：
   - 收到信号置标志位，`main()` 的 `while True` 在下一轮开始前退出
   - **正在执行的 job 要交回去**：在中断边界把该 job 释放回 `queued`（清 `locked_at`），
     并且**不消耗 attempts** —— agent job `max_attempts=1`，消耗掉就直接 failed，
     那样优雅退出反而在制造失败
   - job metadata 记一条 `released_by_shutdown`，便于排查
2. heartbeat：job 执行期间定期（约 30 秒）刷新 `locked_at`。
   最小实现是在 handler 每次 inline commit 时顺带刷新；
   更干净的是给 `queue.py` 加 `touch_running_job(job_id)`，由 handler 在关键节点调用。
3. **本批不要改 `--stale-after 1800`。** 有了 heartbeat 才有下调空间，但先观察一轮再说。

### 2.3 吞异常处补 savepoint

`_emit_step`、`tool_loop.py` 里所有「`except Exception` 之后继续用同一个 session」的地方：

- 把可能写库的调用包进 `db.begin_nested()`（SAVEPOINT）
- `except` 分支里**先 rollback 到 savepoint，再吞**
- 吞掉之前把最初的异常写进 trace 或 stderr —— 现在是彻底静默，事故现场什么都不留

## 三、不做什么

- 不改前端（SSE 契约不变；轮询 / 假失败 / 重试展示是第二批）
- 不改澄清框
- 不改任何 Prompt、不发新 prompt 版本
- 不改 AI 节点的 `default_timeout_seconds`、不动节点 `lifecycle`
- 不动 `--stale-after 1800`
- 不删数据库表、不删历史消息

## 四、已知的坑

1. **草稿必须独立 commit 才可见。** `session_scope` 在退出时才 commit（`backend/app/db.py:53`）。
   但 handler 本来就是 inline commit 模式，直接 `db.commit()` 即可 —— **不要**为了"事务干净"
   改成一个大事务，那会让所有进度消息在 job 结束前都看不见，等于把现在能用的进度回显也弄坏。
2. **flush 频率别太高。** 每个 token 一次 commit 会把一次写作变成几百次事务。按 500ms / 20 delta 节流。
3. **abort 竞态。** 现在是「中止优先」：`turn_aborted_now()` 在 SSE 生成器里查了 4 次。
   搬到 worker 后同样要在每次 flush 前查；最终写 answer 仍走现有 advisory lock，
   **在锁内同时复查 answer 与 abort 都不存在**。
4. **`max_attempts=1`。** 任何「把 job 放回 queued」的路径都要确认不消耗 attempts。
5. **别误触失败收尾。** `_finalize_attachment_job_failure` 和
   `_mark_related_business_update_failed_if_final` 挂在 `run_once` 的失败分支
   （`backend/app/worker.py:52-54`）。优雅退出走的是**释放**不是**失败**，别顺手触发它们。
6. **迁移从 `002_` 起编号**（`001_baseline.sql` 是地板）。加完必须跑 `tests/test_migration_sql.py` ——
   历史事故：注释里的分号把语句切坏，部署被阻断。
7. **Railway preDeploy 跑 `alembic upgrade head`，迁移挂了整个部署阻断。**
   本批带迁移，推之前在本地空库（pgvector/pg17）验一遍。

## 五、验收

| 项 | 期望 |
|---|---|
| `python -m pytest -q` | 全绿；**新增**用例覆盖：断连不落半截、双页签不重复生成、abort 抢跑不落 answer、优雅退出把 job 放回 queued 且不消耗 attempts |
| `tests/test_migration_sql.py` | 通过 |
| 前端 | **一行不改**也能跑通；`npm run typecheck && npm run build && npm run lint` 仍全过 |
| 行为① | 发起一轮推荐 → **正文开始流之后立刻关页签** → 重开会话：绿点、正文完整、**没有重新生成** |
| 行为② | 一轮跑到一半重启 worker（自建环境 `docker compose restart worker-llm` 验）：该轮在秒级变成明确失败或自动重排，**不再挂 30 分钟** |
| 行为③ | 一轮跑到一半点停止：不落 answer、不留草稿、状态为 aborted |

## 六、完成判据

- 第五节 6 条全过
- `docs/系统总纲.md` 里 Writer 归属那段回填（现在写的是「Writer 在 SSE 请求里跑」，改完就不成立了）
- 本文件第七节追加施工记录（**不要另起一份会漂移的文件**）

## 七、施工记录

**2026-08-19 施工完成并已发布。** 提交 `8af3965`，CI 全绿，生产已切到该 commit。

- **基线 HEAD**：`fbf7164`（docs: 补 5B 生产端到端验证结果），分支 `main`。
- **测试通过数**：`1058 passed / 36 skipped` → **`1092 passed / 49 skipped`**（+34 通过，+13 跳过）。
  新增的 13 个跳过全部是需要真实 Postgres 的 SQL 用例（`DATABASE_URL` 未设置时跳过），
  由 CI 的 `Fresh database from baseline` job 实跑。
- **前端**：**一行未改**（`git status frontend/` 为空）。`npm run typecheck` / `build` / `lint`
  全过，lint 0 error、17 个 warning 与改动前完全一致。

### 7.1 改动文件

新增：

| 文件 | 作用 |
| --- | --- |
| `database/migrations/019_recommendation_answer_draft.sql` | 草稿表（`session_id + turn_id` 唯一） |
| `alembic/versions/20260819_0066_recommendation_answer_draft.py` | 对应 alembic 修订（down_revision = `20260817_0065`） |
| `backend/app/shutdown.py` | 进程级关机标志 + `WorkerShutdown` + 信号处理 |
| `backend/app/jobs/heartbeat.py` | `JobHeartbeat`，约 30 秒节流刷 `locked_at` |
| `backend/app/services/recommendation_answer_draft.py` | 草稿读写删 |
| `backend/app/services/recommendation_writer.py` | Writer 段本体（流式、节流落草稿、兜底、终态写） |
| `tests/test_recommendation_writer.py` | 13 个用例：断连、兜底、中止、双页签、优雅退出 |
| — | 订阅侧另有 11 个用例并入 `tests/test_recommendation_answer_stream.py` |
| `tests/test_worker_graceful_shutdown.py` | 9 个用例：释放≠失败、心跳节流、检查点语义 |
| `tests/test_recommendation_answer_persistence_sql.py` | 8 个真实 DB 用例：草稿唯一性、级联、锁内双复查 |

修改：

| 文件 | 改动 |
| --- | --- |
| `backend/app/jobs/handlers/recommendation.py` | 写完 brief 继续跑 Writer；`turn_stopped()` 同时管中止与关机；进度提交带心跳 |
| `backend/app/api/routes/recommendations.py` | `/answer-stream` 退化成订阅（回放 / 轮询草稿 / 终态判定），删掉全部生成代码 |
| `backend/app/services/recommendation_flow.py` | `insert_agent_answer_message` 返回 `AgentAnswerWrite`，锁内同时复查 abort 与已有 answer；新增 `find_agent_answer_id` |
| `backend/app/jobs/queue.py` | 新增 `touch_running_job`、`release_job_for_shutdown` |
| `backend/app/worker.py` | 装信号处理；`WorkerShutdown` 走释放分支；空转 sleep 改成可被信号打断 |
| `backend/app/db.py` | 新增 `savepoint()` |
| `backend/app/services/recommendation_agent_tools.py` | `_emit_step` 与 `execute` 包 savepoint，吞异常前打 traceback |
| `backend/app/ai/tool_loop.py` | 工具异常回传给模型之前先进 stderr |
| `docs/系统总纲.md` | §3.3 Writer 归属、落库契约、中止语义、stale 窗口四处回填 |
| `.github/workflows/ci.yml` | `Fresh database from baseline` job 加一步跑新增的真实 DB 用例（该 job 按文件点名，不加就永远不跑） |

### 7.2 与施工单的差异（各一条，均已按第一节根因执行）

1. **迁移编号是 `019_` 不是 `002_`。** 施工单第四节第 6 条的「从 `002_` 起编号」是
   `AGENTS.md` 里「baseline 是 001、新迁移从 002 起」的口径；实际目录已经排到 `018`，
   所以本批取下一个空号 `019`。`tests/test_migration_sql.py` 65 项全过。
2. **`_emit_step` 用「savepoint + 失败时整体回滚」而不是纯 savepoint。**
   施工单第 2.3 节写的是「包进 `db.begin_nested()`，except 里先 rollback 到 savepoint」。
   但 `_emit_step` 调用的 `step_sink` **自己会 `db.commit()`**（这正是进度回显能实时可见的原因，
   见第四节第 1 条），而一次 commit 会把 SAVEPOINT 一并结束。所以 `db.savepoint()` 写成：
   savepoint 还在就回滚到 savepoint，已经被块内 commit 掉了就整体 rollback ——
   两种情况都能让 session 回到可用状态，而块内已提交的进度不会丢。
   根因判断没有改，只是实现要迁就 inline commit 模式。
3. **多加了一个施工单没要求的保险：同一 job 被关机打断 3 次以上判失败。**
   放回队列不消耗 attempts 是对的，但崩溃重启循环里的 worker 会一直收到 SIGTERM，
   而重排一次 `recommendation_agent` 就是重新付一次模型钱。上限写在
   `queue.MAX_SHUTDOWN_RELEASES`，超限记 `worker_shutdown_exhausted`。

### 7.3 两个已知边界

**其一，发布窗口内的遗留轮次。**

发布的那一刻若正好有「agent job 已成功、只写了 brief、正文还没生成」的旧轮次（旧代码的形态），
新的 `/answer-stream` 只订阅不生成，会给出 `error`「这一轮没能生成正文，请重新提问」。
这类轮次在旧代码下**本来就已经丢了正文**（关页签即丢），差别只是从「静默重新生成并重新收费」
变成「如实说没有」。窗口只覆盖发布瞬间在飞的轮次。

**其二，订阅占一个线程池槽位。** 同步生成器由 Starlette 放进线程池跑，`time.sleep(0.3)` 阻塞的是线程池 worker 而不是事件循环 —— 与改动前那个阻塞在 urlopen 上的实现是同一形状，不是新增的问题。区别是超时上限从「模型流多久」变成了固定 300 秒，但任务一进终态订阅就立刻返回，真正跑满 300 秒只会发生在 job 被重排、整轮重跑的情况下。按当前并发（个位数顾问）无需处理；若将来并发上来，改成异步生成器 + `asyncio.sleep` 即可，SSE 契约不受影响。

### 7.4 验证结果

**CI**（run `32230342581`，全部 job success）——**这就是施工单第四节第 7 条要的迁移预演**：

| job / step | 结果 |
| --- | --- |
| Backend tests (pytest) | success |
| Fresh database from baseline → Apply the baseline to a fresh database | success（pgvector/pg17 **空库**） |
| Fresh database from baseline → Apply any migrations after the baseline | success（即 `alembic upgrade head`，019 干净应用） |
| → Exercise the job-queue SQL | success（含新增的释放/心跳 5 例） |
| → Exercise the answer persistence SQL | success（新增 8 例：草稿唯一性、级联删除、锁内双复查） |
| Frontend typecheck + build | success |

**部署**：`/api/v1/health` 的 `git_commit_sha` 已切到 `8af3965313215d7210907cff5e494df8f5f46c5c`。
前端服务按预期**没有**重建（本次提交没碰 `frontend/**`）。

**生产行为验证**：

| 项 | 会话 | 结果 |
| --- | --- | --- |
| **行为①** 正文开始流之后立刻断开 | `ed98a4e5` | **通过**。收到第 1 个 `delta` 后主动挂断连接，正文仍然完整落库：875 字、`generation_mode=llm`、`duration_ms=51734`、站内链接 4 个；`job_status=succeeded`；重连拿到 `replayed=true` 且正文与 duration 完全一致（**没有重新生成**）；该轮 `agent_answer` 行数 = 1；会话运行态 = `completed`（绿点）。 |
| **行为③** 编排阶段点停止 | `0d49d10c` | **通过**。只有 `agent_aborted` + 过程消息，无 `agent_brief`、无 `agent_answer`；`answer-stream` 返回 409；运行态 = `aborted`。 |
| **行为③b** 正文正在流的时候点停止（本批新代码路径） | `e487394b` | **通过**。订阅端先真实收到 3 个 `delta`（证明 worker 在落草稿、订阅端在读），此时发停止 → 无 `agent_answer`（**半截草稿没有升格**）、`answer-stream` 409（没有残留草稿被当成正文流出去）、运行态 = `aborted`，而 `job_status` 仍是 `succeeded`（编排段本来就跑完了，中止的是正文段）。 |
| **心跳** | `e00b3cfa` | **通过**。一次约 3 分钟的 job 期间 `locked_at` 从 `08:11:52` → `08:12:41` → `08:13:51` 逐步前移，不再冻在领取时刻；`attempt_count` 全程 1/1。 |

### 7.5 唯一未演的一条：行为②

**行为②（跑到一半重启 worker）在 Railway 上演不了** —— 没有按需向 worker 发 SIGTERM 的手段，
而借一次部署来触发的话，构建排队十几分钟到一小时，等 worker 真的收到信号时那一轮早就跑完了。
施工单第五节写的验证方式本来就是自建环境的 `docker compose restart worker-llm`，那是秒级的。

所以这一条要么在自建 ECS 上补（需要先把 `8af3965` 部署过去：
`ssh match-ma-aliyun 'cd /opt/match-ma && git pull && cd deploy && docker compose build && docker compose up -d'`，
`migrate` 会自动应用 019），要么接受「代码路径由
`tests/test_worker_graceful_shutdown.py` 的 9 个用例覆盖 + 心跳已在生产实测前移」这个程度。
**待用户决定。**
