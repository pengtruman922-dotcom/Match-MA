# Match-MA API 测试命令 v0.1

日期：2026-05-27

范围：记录在 Windows PowerShell 中测试 Match-MA API 的命令，重点避免中文请求和响应编码问题。

---

## 1. PowerShell 中文编码设置

测试前先执行：

```powershell
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
```

如果控制台仍显示乱码，可改用：

```powershell
chcp 65001
```

或使用 Windows Terminal / PowerShell 7。

---

## 2. 发送中文 JSON 的正确方式

不要直接把 JSON 字符串传给 `-Body`。

推荐写法：

```powershell
$json = @{
  target_name = "杭州启元三号项目"
  target_type = "company"
  industry_primary = "healthcare"
  headquarter_province = "浙江省"
  headquarter_city = "杭州市"
  business_summary = "医疗器械相关标的，利润约2500万。"
} | ConvertTo-Json

$body = [System.Text.Encoding]::UTF8.GetBytes($json)

Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/seller-targets" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

---

## 3. 响应中文仍显示乱码时

如果 API 中已经存入了正确中文，但 PowerShell 显示成：

```text
æµæ±...
```

通常是响应没有被 PowerShell 按 UTF-8 解码，或当前终端字体/编码不支持。

服务端已强制 JSON 响应头：

```text
Content-Type: application/json; charset=utf-8
```

如果仍乱码，可以用 `Invoke-WebRequest` 手动 UTF-8 解码：

```powershell
$res = Invoke-WebRequest `
  -Uri "https://match-ma-production.up.railway.app/api/v1/seller-targets?q=启元" `
  -UseBasicParsing

[System.Text.Encoding]::UTF8.GetString($res.RawContentStream.ToArray())
```

或直接在浏览器中打开 GET 接口查看。

---

## 4. 注意已入库乱码数据

如果请求阶段没有按 UTF-8 发送，数据库中会真实保存 `????` 或 `æµæ±...`。

这类测试数据后续需要通过更新/删除接口清理。当前一期最小 API 还没有删除接口，可以先保留，不影响验证读写链路。

---

## 5. 更新标的

```powershell
$json = @{
  target_name = "杭州启元三号项目"
  information_status = "normal"
  business_summary = "医疗器械相关标的，利润约2500万，信息已人工确认。"
} | ConvertTo-Json

$body = [System.Text.Encoding]::UTF8.GetBytes($json)

Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/seller-targets/$($sellerTarget2.id)" `
  -Method Patch `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

---

## 6. 软删除标的

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/seller-targets/$($sellerTarget2.id)" `
  -Method Delete
```

删除后列表不再返回该标的：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/seller-targets?q=启元" `
  -Method Get
```

---

## 7. 更新买家意向

```powershell
$json = @{
  status = "paused"
  pause_reason = "买家阶段性暂停收购"
  preference_summary = "后续如恢复收购，仍优先关注浙江医药健康标的。"
} | ConvertTo-Json

$body = [System.Text.Encoding]::UTF8.GetBytes($json)

Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/buyer-intents/$($buyerIntent2.id)" `
  -Method Patch `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

---

## 8. 软删除买家意向

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/buyer-intents/$($buyerIntent2.id)" `
  -Method Delete
```

删除后列表不再返回该意向：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/buyer-intents?q=医药" `
  -Method Get
```

---

## 9. 查询更新记录

查询标的更新记录：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/update-logs?entity_type=seller_target&entity_id=26d78a25-961c-4763-8002-e8baedb8fa40" `
  -Method Get
```

查询买家意向更新记录：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/update-logs?entity_type=buyer_intent&entity_id=64c9995b-6d1d-42c1-9f95-e8792cf0131a" `
  -Method Get
```

只按对象类型查询最近记录：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/update-logs?entity_type=seller_target&limit=20" `
  -Method Get
```

---

## 10. 新建统一业务更新

```powershell
$json = @{
  raw_text = "上海启元项目：周二下午已与项目方见面沟通。无锡某上市公司仍在联系中，计划近期进场。下周继续催促协议签署，并确认具体进场时间。"
  input_type = "text"
  bound_seller_target_ids = @("26d78a25-961c-4763-8002-e8baedb8fa40")
  bound_buyer_intent_ids = @("64c9995b-6d1d-42c1-9f95-e8792cf0131a")
  metadata_json = @{
    source = "manual_test"
  }
} | ConvertTo-Json -Depth 5

$body = [System.Text.Encoding]::UTF8.GetBytes($json)

$businessUpdate = Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/business-updates" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body

$businessUpdate
```

查询业务更新列表：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/business-updates" `
  -Method Get
```

按标的查询业务更新：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/business-updates?seller_target_id=26d78a25-961c-4763-8002-e8baedb8fa40" `
  -Method Get
```

查询业务更新详情：

```powershell
Invoke-RestMethod `
  -Uri "https://match-ma-production.up.railway.app/api/v1/business-updates/$($businessUpdate.id)" `
  -Method Get
```
