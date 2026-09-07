# 接入说明（给 wegent 那边）

这个目录只有 `SKILL.md`，没有代码、没有凭证。查询逻辑全部在 Match-MA 服务端的 MCP 端点上，
skill 只是教 Agent 怎么用那六个工具。它取代了 `skills/buyer-search/` 与 `skills/target-search/`
两个带 Python 脚本和 `auth.local.json` 的旧版本。

## 一、在 Match-MA 签发一把只读 API key

用管理员身份调一次（或者在设置页做，后续补界面）：

```bash
curl -s -X POST https://match-ma-production.up.railway.app/api/v1/api-keys \
  -H "Authorization: Bearer <管理员 JWT>" -H "Content-Type: application/json" \
  -d '{"name": "wegent-buyer-agent", "scopes": ["agent:read"]}'
```

响应里的 `api_key`（`mma_` 开头）**只在这一次出现**，库里只存哈希。要撤销：

```bash
curl -s -X POST https://match-ma-production.up.railway.app/api/v1/api-keys/<id>/revoke \
  -H "Authorization: Bearer <管理员 JWT>"
```

停用后下一次请求即失效。`GET /api/v1/api-keys` 看列表（只显示前缀）。

## 二、在 Wegent 添加 MCP 服务

机器人（Bot）编辑页 → MCP 配置 → 导入 JSON：

```json
{
  "mcpServers": {
    "match-ma": {
      "type": "streamable-http",
      "url": "https://match-ma-production.up.railway.app/api/v1/mcp",
      "headers": {"Authorization": "Bearer mma_……"}
    }
  }
}
```

`type` 必须显式写 `streamable-http`，Wegent 的默认值不是它。配置存在这个机器人的 Ghost 里，
运行时把 `headers` 原样带到连接上。**Ghost 所属的 Team 分享出去时这段配置可能一起分享**，
要么这个 Team 保持私有，要么每个使用者在自己的机器人里填自己的 key。

加完用 Wegent 自带的「测试连接」看六个工具有没有列出来：
`buyers_scan` `buyer_get` `buyers_filter` `targets_scan` `target_get` `targets_filter`。

## 三、让 Agent 会用

工具的名称、说明和参数 schema 随连接下发，Agent 看到工具就会用；`SKILL.md` 里的流程与铁律
放进机器人的系统提示词，或者把本目录作为只有 `SKILL.md` 的 skill 绑到 Ghost 上。

## 四、手工验证端点

```bash
curl -s https://match-ma-production.up.railway.app/api/v1/mcp \
  -H "Authorization: Bearer mma_……" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

无状态实现：没有会话 id，`GET` 回 405，每个 POST 独立处理，API 多副本不需要协调。
每次 `tools/call` 在 `agent_call_log` 表留一条：谁、何时、哪个工具、什么参数、命中几条、耗时。
