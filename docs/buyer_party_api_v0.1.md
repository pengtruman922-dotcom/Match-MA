# Match-MA 买家主体 API v0.1

日期：2026-05-28

范围：实现 `buyer_party` 的最小 CRUD，用于让买家意向可以关联真实买家公司主体。

---

## 1. 目标

当前业务中，买家意向是推荐核心，但买家公司主体仍需要独立维护：

```text
buyer_party
  -> buyer_intent 1
  -> buyer_intent 2
```

一期先支持：

- 新建买家主体。
- 查询买家主体列表。
- 查询买家主体详情。
- 更新买家主体。
- 软删除买家主体。

---

## 2. 新建买家主体

```text
POST /api/v1/buyer-parties
```

请求示例：

```json
{
  "buyer_name": "浙江某国资平台",
  "legal_name": "浙江某国资平台有限公司",
  "buyer_type": "state_owned_platform",
  "listed_status": "unlisted",
  "region_province": "浙江省",
  "region_city": "杭州市",
  "main_business": "国资产业投资与并购整合",
  "profile_summary": "关注医药健康、新能源、新材料等方向。"
}
```

---

## 3. 查询列表

```text
GET /api/v1/buyer-parties
GET /api/v1/buyer-parties?q=国资
```

---

## 4. 查询详情

```text
GET /api/v1/buyer-parties/{buyer_party_id}
```

---

## 5. 更新买家主体

```text
PATCH /api/v1/buyer-parties/{buyer_party_id}
```

请求示例：

```json
{
  "profile_summary": "重点关注医药健康、新能源和高端装备并购机会。"
}
```

更新会写入 `action_application_log`。

---

## 6. 查询买家主体下的意向

```text
GET /api/v1/buyer-parties/{buyer_party_id}/intents
```

等价于：

```text
GET /api/v1/buyer-intents?buyer_party_id={buyer_party_id}
```

用途：

- 支撑买家详情页的“意向”tab。
- 展示一个买家公司主体下的一个或多个收购意向。

---

## 7. 软删除买家主体

```text
DELETE /api/v1/buyer-parties/{buyer_party_id}
```

说明：

- 不物理删除。
- 写入 `deleted_at / deleted_by`。
- 列表和详情默认不返回软删除数据。

---

## 8. 后续

下一步可以：

1. 在新建买家意向时可选自动新建或关联 `buyer_party`。
2. 在买家详情页展示其全部 `buyer_intent`。
3. 做买家主体去重。
4. 做买家主体更新记录 tab。
