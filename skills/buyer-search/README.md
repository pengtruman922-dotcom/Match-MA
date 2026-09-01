# 接入说明（给 wegent 那边）

## 文件

| 文件 | 用途 |
|---|---|
| `tool.json` | Wegent 可识别的单个工具定义（OpenAI function-calling 格式），通过 `operation` 分发三种查询 |
| `SKILL.md` | 给 Agent 读的技能说明：三接口用法 + 7 条硬规则 + **空值方向那一条** |
| `search_buyers.py` | 可独立运行的实现，也可 `from search_buyers import search_buyers_business, get_buyer, filter_buyers` 调用 |

与 `skills/target-search/`（为买家找标的）是反方向的一对，凭证方案完全相同。

## Wegent 注册方式

本目录按 `target-search` 的单工具格式接入：注册 `tool.json` 后，工具名是
`search_buyers`，运行入口是 `search_buyers.py` 里的同名 `search_buyers()` 函数。
它不是 MCP server，不需要在 Wegent 里寻找名为 Match-MA 的 MCP。Wegent 需要支持
执行 skill 的 Python 入口并把 `tool.json` 注册为 function tool。

三个原始查询函数仍保留，但不直接作为三个 tool 注册。调用时传 `operation`：

```json
{"operation": "business", "detail": "full"}
{"operation": "get", "name": "北大健康"}
{"operation": "filter", "city": "杭州市"}
```

如果 Wegent 的导入器只接受一个 `tool.json` 对象，这个版本可以直接导入；如果它
只支持 MCP、不能执行 Python skill，则需要 Wegent 管理员提供执行器或另建 MCP
适配层，仓库里的 skill 文件本身无法注册 MCP 服务。

## 这个 skill 与标的侧那个最大的不同

**空值的含义反了。**

标的侧只有一类缺失：「这个字段库里没录」。买家侧有两类，而且含义相反：

- 买家自身的事实（业务说明、市值、营收）缺失 = 没录、未知；
- 买家需求的门槛（最低营收、可接受地区）缺失 = **买家没提这个门槛 = 不构成障碍**。

补充：如果 `filter_buyers` 明确筛选买家自身的企业性质、上市状态、所在地、市值
或营收，未知/空值不算满足，会被排除。结果过少时由调用方 Agent 自主减少条件重试。

写不清这一条，模型会把「没提营收门槛」读成「信息不足无法判断」，
然后**把库里最灵活的那批买家全漏掉** —— 而那批恰恰最该推。

所以 `SKILL.md` 用一整节讲它，返回结构也把两者分成 `买家信息` / `收购需求` 两个块，
让这个区分在数据形状上成立，而不是只写在文档里。**不要把这两块拍平成一层。**

## 上线前必须先做的一件事

**库里有 Mock 测试数据没清。** 2026-08-27 实测：42 个主体里 5 个、52 条需求里 10 条是
`Mock测试-20260624-*`，别名编得很像真的（「苏州康瑞医疗集团股份有限公司」）。

全量倒给 LLM 的方案下，**Agent 一定会把它们当成真买家推荐出去**。

正解是把这 5 个主体置 `status='archived'`（`buyer_party.status` 已经有这个取值，
当前 42 个全是 `active`），本 skill 只取 `active`，它们就自然不出现了。
**靠客户端按名字前缀排除是脆的** —— 下一批测试数据换个前缀就漏了。

## 认证

**不要用仓库里 `.match-ma-local-auth.json` 的那个 token。** 它是 `effective_admin_token`：
静态、不过期、权限全开（能读也能写），而且是登录系统的恢复通道 —— 要撤销只能改它，
一改就影响所有在用它的工具。不该发进外部运行环境。

凭证解析优先级（脚本按此顺序尝试）：

| 优先级 | 配置 | 说明 |
|---|---|---|
| 1 | `MATCH_MA_USERNAME` + `MATCH_MA_PASSWORD` | **推荐。** 专用账号，脚本调 `POST /auth/login` 换 7 天 JWT 并缓存到临时目录；401 时自动重登一次。可单独停用该账号，不动恢复通道 |
| 2 | `MATCH_MA_TOKEN` | 静态令牌，仅限本机调试 |
| 3 | `MATCH_MA_AUTH_FILE` | 指向一个 `{"token": "..."}` 的 JSON 文件 |
| 4 | 家目录 / 当前目录 / 仓库根目录的 `.match-ma-local-auth.json` | 本地开发回退 |

### 情况一：能注入环境变量（首选）

```bash
export MATCH_MA_USERNAME="wegent-buyer-search"
export MATCH_MA_PASSWORD="<该账号的密码>"
```

### 情况二：不能注入环境变量、沙箱又是临时的（wegent 目前就是这样）

此时 skill 目录是唯一的持久存储。**在 skill 目录里放一个 `auth.local.json`，
里面存 7 天 JWT，不要存账号密码。**

在**你自己的电脑**上打开 PowerShell，跑这一条（不用先设任何环境变量，它会问你）：

```powershell
cd D:/Match-MA_v1.0
python skills/buyer-search/search_buyers.py --issue-token
```

它会依次问「Match-MA 用户名」和「密码」（密码输入时不显示，输完直接回车），
然后把凭证**直接写好**在 `skills/buyer-search/auth.local.json`，并打印到期时间。

之后把整个 `buyer-search` 目录（含 `auth.local.json`）上传到 wegent，
在那边跑 `python search_buyers.py --check` 验证。**过期前重跑一次换新的。**

> 需要把令牌原文贴到别处时，加 `--show`。
> 注意 PowerShell 用 `$env:X = "值"`，**不能**用 bash 的 `X=值 命令` 写法。

为什么是 JWT 不是密码：JWT **7 天自动过期**，泄漏的损失有界；密码是长期有效的，
还能用来登录 Web 端、改自己的密码。

`auth.local.json` 已写进仓库根的 `.gitignore`（`skills/**/auth.local.json`），
不会被提交。**但它在 wegent 那边是明文存着的** —— 所以：

> ⚠️ **先搞清楚谁能读到 wegent 里的 skill。** 这个账号是 admin 角色（受限于当前
> 没有只读角色），能读到 skill 的人就拿到了 7 天的全库 API 权限。
>
> **买家侧比标的侧多一层风险**：买家库里有联系人与联系方式。本 skill 在代码层面
> **永不返回**联系人三件套（`contact_name` / `contact_info_json` / `our_contact_name`）
> 与运营备注（`notes`），但拿到令牌的人可以直接调 API 取到它们。
>
> 长期的正解是二选一：① 给 Match-MA 加只读角色；② 部署一个中转端点，凭证留在
> 服务端，wegent 只拿到一个无凭证的查询地址。两个都是代码改动。

要撤销时：Match-MA「账号管理」里点「停用」，**最多 60 秒生效**
（`authn.py` 每个请求都回库查 status，带 60 秒缓存），不用等 JWT 过期。

## 诊断

```bash
python skills/buyer-search/search_buyers.py --check
```

除了凭证与连通性，它还会打印**库规模与业务说明填充率**：

```
在库买家主体        : 37 家（过闸门后）
  其中有业务说明    : 12 家  ← 首轮筛只读这一栏，它是效果上限
在库需求            : 42 条（E 级与已结束的已排除）
```

**这个数字就是这套方案的效果上限。** 首轮筛只读业务说明，
没有业务说明的买家判不出业务匹配。超过一半为空时 `--check` 会额外警告一句 ——
遇到那种情况要补的是**数据**，不是提示词。

## 第一轮要验的不是「能不能调通」

是**「全量业务原文 + LLM 判断」这一段够不够用**。拿 5-8 个真实标的跑，每条记两个数：

- **漏了几家**：先让顾问从全库挑出「该推的买家」，再看模型有没有全部选出来。
  **这是唯一要压到 0 的指标。**
- **误报数**：选出来但顾问认为完全不搭的。可以有，但不该超过一半。

如果漏检集中在「买家没填业务说明」，那要补的是**数据**不是提示词 ——
这个区分很重要，别改错地方。

## 手工试跑

```bash
# 接口一：全库业务原文
python skills/buyer-search/search_buyers.py --business

# 接口二：按名称取全量档
python skills/buyer-search/search_buyers.py --name 北大健康

# 接口三：按标的事实反查
python skills/buyer-search/search_buyers.py --filter --target-revenue-yuan 200000000 --target-province 江苏省
```

命令行入口与 `tool.json` 支持同一组筛选维度：买家自身还可传
`--min-market-cap-yuan` / `--min-revenue-yuan`，标的事实还可传
`--target-market-cap-yuan` / `--target-valuation-yuan` / `--target-district`。
