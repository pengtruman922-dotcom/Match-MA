# -*- coding: utf-8 -*-
"""标的匹配评测台 —— 本地网页版。

启动：
    python docs/语义匹配测试/app.py
然后浏览器会自动打开 http://127.0.0.1:8765

和 bench.py 的关系：切片、解析、评分三块逻辑直接从 bench.py 导入，**不复制一份**。
那三个函数已经离线验过，复制出去就会有两份评分口径，早晚对不上。
这里只换掉调用层：wegent 的 responses 接口 → 任意 OpenAI 兼容端点的 chat.completions。

阿里云 DashScope 的兼容端点是 `https://dashscope.aliyuncs.com/compatible-mode/v1`，
少了 `/compatible-mode/v1` 会 404 —— 这是最容易踩的一脚。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bench import build_slice, load_master, parse_reply, render_table, score  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

CONFIG_PATH = HERE / "config.local.json"
PROMPTS_PATH = HERE / "prompts.json"
QUESTIONS_PATH = HERE / "questions.json"
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen3-max",
    "api_key": "",
    "temperature": 0.0,
    "timeout": 300,
    "concurrency": 2,
}
MASK = "••••••••"


# ---------- 配置 ----------

def read_config() -> dict[str, Any]:
    data = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except ValueError:
            pass
    # 环境变量优先，方便不想落盘的人
    if os.environ.get("DASHSCOPE_API_KEY"):
        data["api_key"] = os.environ["DASHSCOPE_API_KEY"]
    return data


def write_config(patch: dict[str, Any]) -> None:
    data = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except ValueError:
            pass
    for key, value in patch.items():
        # 界面回传掩码时说明用户没改 key，不能把真 key 覆盖掉。
        # 这里必须判「含不含圆点」而不是「等不等于 MASK」——回传的是 MASK + 后四位，
        # 用等号判会漏掉，于是掩码被当成真 key 存进去，请求头里出现非 ASCII 字符，
        # 报成 `UnicodeEncodeError ... position 7-14`（"Bearer " 之后正好 8 个圆点）。
        if key == "api_key" and (not value or "•" in str(value)):
            continue
        data[key] = value
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def public_config() -> dict[str, Any]:
    data = read_config()
    key = data.get("api_key") or ""
    data["api_key"] = (MASK + key[-4:]) if key else ""
    data["has_key"] = bool(key)
    data["key_from_env"] = bool(os.environ.get("DASHSCOPE_API_KEY"))
    return data


# ---------- 提示词与题库 ----------

DEFAULT_USER_TEMPLATE = "{question}\n\n以下是标的库，共 {count} 条：\n\n{table}"


def load_prompts() -> list[dict[str, Any]]:
    if PROMPTS_PATH.exists():
        try:
            return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
        except ValueError:
            pass
    seed = (HERE / "提示词_业务匹配判断.md")
    system = seed.read_text(encoding="utf-8") if seed.exists() else ""
    # 去掉文档抬头那两行说明，只留给模型看的正文
    system = re.sub(r"^#.*?\n+.*?\n---\n+", "", system, count=1, flags=re.S) or system
    items = [{"id": "v1", "name": "v1 三种匹配逻辑",
              "system": system.strip(), "user_template": DEFAULT_USER_TEMPLATE}]
    PROMPTS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return items


def save_prompts(items: list[dict[str, Any]]) -> None:
    PROMPTS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def load_questions() -> list[dict[str, Any]]:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def save_questions(items: list[dict[str, Any]]) -> None:
    QUESTIONS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 调用 ----------

def make_client(cfg: dict[str, Any]):
    from openai import OpenAI
    key = str(cfg.get("api_key") or "")
    if not key:
        raise RuntimeError("还没填 API Key")
    if not key.isascii():
        # 兜底：真 key 一定是 ASCII。走到这里说明存进去的是掩码或被输入法弄脏了，
        # 与其让 httpx 抛一句看不懂的 UnicodeEncodeError，不如直接说清楚。
        raise RuntimeError("API Key 里有非 ASCII 字符（多半是把掩码存进去了）。请到①连接页重新粘贴一次真实的 Key。")
    base = (cfg.get("base_url") or "").rstrip("/")
    if "dashscope.aliyuncs.com" in base and "compatible-mode" not in base:
        raise RuntimeError(
            "DashScope 的地址要带兼容模式后缀：https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    return OpenAI(api_key=cfg["api_key"], base_url=base)


def chat(cfg: dict[str, Any], system: str, user: str) -> tuple[str, dict[str, Any], float]:
    client = make_client(cfg)
    started = time.time()
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=float(cfg.get("temperature", 0)),
        timeout=int(cfg.get("timeout", 300)),
    )
    usage = getattr(resp, "usage", None)
    return (
        resp.choices[0].message.content or "",
        {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        },
        time.time() - started,
    )


_RETRYABLE = ("429", "rate", "limit", "timeout", "timed out", "502", "503", "504")


def chat_with_retry(cfg, system, user, attempts: int = 3):
    """限流与瞬时故障退避重试。**重试成功不算失败，重试耗尽才算** ——
    把限流记成模型漏检，会让曲线在高并发时假性变差。"""
    delay = 3.0
    last = None
    for i in range(attempts):
        try:
            return chat(cfg, system, user)
        except Exception as error:  # noqa: BLE001 —— 要看错误内容才知道该不该重试
            last = error
            text = str(error).lower()
            if i == attempts - 1 or not any(token in text for token in _RETRYABLE):
                raise
            time.sleep(delay)
            delay *= 2
    raise last  # pragma: no cover


# ---------- 运行状态 ----------

RUNS: dict[str, dict[str, Any]] = {}
RUNS_LOCK = threading.Lock()


def do_run(run_id: str, cfg, prompt, questions, sizes, repeats, master, by_name):
    state = RUNS[run_id]
    tasks = [(q, s, r) for q in questions for s in sizes for r in range(1, repeats + 1)]
    state["total"] = len(tasks)

    def one(task):
        question, size, rep = task
        if state["stop"]:
            return None
        rows, row_to_name = build_slice(master, size, question.get("protected", []), seed=1000 + size)
        user = prompt["user_template"].format(
            question=question["prompt"], count=len(rows), table=render_table(rows)
        )
        rec: dict[str, Any] = {"question": question["id"], "question_name": question.get("name", ""),
                               "size": size, "rep": rep, "prompt_chars": len(user), "error": ""}
        try:
            text, usage, elapsed = chat_with_retry(cfg, prompt["system"], user)
        except Exception as error:  # noqa: BLE001 —— 单次失败不该中断整轮
            rec.update(error=f"{type(error).__name__}: {error}", elapsed=0, parse="error")
            with RUNS_LOCK:
                state["records"].append(rec)
                state["done"] += 1
            return rec
        parsed, source = parse_reply(text)
        rec.update(elapsed=round(elapsed, 1), parse=source, reply_chars=len(text), **usage)
        (RESULTS_DIR / f"{run_id}_{question['id']}_{size}_{rep}.txt").write_text(text, encoding="utf-8")
        if parsed is None:
            rec["error"] = "解析不出命中行号"
        else:
            rec["checked"] = parsed.get("checked")
            rec["checked_ok"] = parsed.get("checked") == size
            rec.update(score(parsed, row_to_name, question["expected"],
                             question.get("must_not", []), by_name,
                             question.get("insufficient", [])))
        with RUNS_LOCK:
            state["records"].append(rec)
            state["done"] += 1
        return rec

    try:
        with ThreadPoolExecutor(max_workers=int(cfg.get("concurrency", 2))) as pool:
            list(pool.map(one, tasks))
        state["status"] = "stopped" if state["stop"] else "done"
    except Exception as error:  # noqa: BLE001 —— 整轮崩了也要让界面看到原因
        state["status"] = "error"
        state["error"] = f"{type(error).__name__}: {error}"
    (RESULTS_DIR / f"{run_id}.json").write_text(
        json.dumps(state | {"stop": False}, ensure_ascii=False, indent=1), encoding="utf-8")


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ok = [r for r in records if not r.get("error") and r.get("recall") is not None]
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in ok:
        groups.setdefault((r["question"], r["size"]), []).append(r)
    out = []
    for (qid, size), rs in sorted(groups.items()):
        recalls = [r["recall"] for r in rs]
        thin = [r["recall_thin"] for r in rs if r.get("recall_thin") is not None]
        thick = [r["recall_thick"] for r in rs if r.get("recall_thick") is not None]
        out.append({
            "question": qid, "size": size, "n": len(rs),
            "recall": round(statistics.mean(recalls), 3),
            "recall_min": min(recalls), "recall_max": max(recalls),
            "recall_thin": round(statistics.mean(thin), 3) if thin else None,
            "recall_thick": round(statistics.mean(thick), 3) if thick else None,
            "false_pos": round(statistics.mean([r["false_pos"] for r in rs]), 2),
            "extra": round(statistics.mean([r["extra"] for r in rs]), 2),
            "checked_ok": sum(1 for r in rs if r.get("checked_ok")),
            "elapsed": round(statistics.mean([r["elapsed"] for r in rs]), 1),
        })
    return out


# ---------- HTTP ----------

app = FastAPI(title="标的匹配评测台")


class ConfigIn(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    temperature: float | None = None
    timeout: int | None = None
    concurrency: int | None = None


class RunIn(BaseModel):
    prompt_id: str
    question_ids: list[str]
    sizes: list[int]
    repeats: int = 1


@app.get("/")
def index():
    return FileResponse(HERE / "ui.html")


@app.get("/favicon.ico")
def favicon():
    # 没有这个的话，每次刷新控制台都多一条红色 404，真出问题时反而看不见。
    return Response(content=(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<rect width="16" height="16" rx="3" fill="#2563eb"/>'
        '<path d="M4 11V5l4 4 4-4v6" stroke="#fff" stroke-width="1.6" fill="none"/></svg>'
    ), media_type="image/svg+xml")


@app.get("/api/config")
def api_get_config():
    return public_config()


@app.post("/api/config")
def api_set_config(payload: ConfigIn):
    write_config({k: v for k, v in payload.model_dump().items() if v is not None})
    return public_config()


def preflight(cfg: dict[str, Any]) -> str:
    """地址与 key 明显对不上时，直接说清楚。

    实际踩过的坑：把自家网关的 `wg-` key 填进阿里云地址，返回的是一句
    「Incorrect API key」—— 完全正确但毫无指向性，人会去反复检查 key 有没有复制错，
    而真正的问题是**这把钥匙根本不属于这扇门**。
    """
    base = (cfg.get("base_url") or "").lower()
    key = str(cfg.get("api_key") or "")
    if "dashscope" in base and key and not key.startswith("sk-"):
        return (f"你填的 Key 是 `{key[:3]}…` 开头，而阿里云百炼的 Key 一律是 `sk-` 开头。"
                "这多半是别的平台的 Key。去 阿里云百炼控制台 → API-KEY 新建一个。")
    if "ai.mpgroup.cn" in base:
        return ("这个地址是你们自建的 wegent 网关：它只实现 /responses、不实现 /chat/completions，"
                "模型名还必须写成 namespace#team_name 格式。本应用走的是标准 chat/completions，"
                "请改用阿里云百炼的地址。")
    return ""


@app.post("/api/test-connection")
def api_test():
    cfg = read_config()
    warn = preflight(cfg)
    try:
        text, usage, elapsed = chat(cfg, "你是一个测试助手，只回复用户要求的内容。", "回复两个字：正常")
    except Exception as error:  # noqa: BLE001 —— 连通性测试要把原始错误给人看
        return JSONResponse({"ok": False, "error": f"{type(error).__name__}: {error}", "hint": warn})
    return {"ok": True, "reply": text.strip()[:100], "elapsed": round(elapsed, 2), "hint": warn, **usage}


@app.get("/api/models")
def api_models():
    """列出该端点上可用的模型 id，省得靠猜模型名再撞一轮 404。"""
    cfg = read_config()
    try:
        client = make_client(cfg)
        data = client.models.list()
        return {"ok": True, "models": sorted(m.id for m in data.data)}
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(error).__name__}: {error}",
                             "hint": preflight(cfg)})


@app.get("/api/prompts")
def api_prompts():
    return load_prompts()


@app.post("/api/prompts")
def api_save_prompts(items: list[dict[str, Any]]):
    save_prompts(items)
    return {"ok": True}


@app.get("/api/questions")
def api_questions():
    return load_questions()


@app.post("/api/questions")
def api_save_questions(items: list[dict[str, Any]]):
    save_questions(items)
    return {"ok": True}


@app.get("/api/master")
def api_master():
    master = load_master()
    tags = {"T": 0, "H": 0, "E": 0}
    for d in master:
        tags[d["tag"]] = tags.get(d["tag"], 0) + 1
    return {"count": len(master), "tags": tags,
            "items": [{"name": d["name"], "tags": d.get("tags") or [], "tag": d["tag"],
                       "listed": d.get("listed", ""), "summary": d["summary"]} for d in master]}


@app.post("/api/run")
def api_run(payload: RunIn):
    cfg = read_config()
    if not cfg.get("api_key"):
        raise HTTPException(400, "还没填 API Key")
    prompts = {p["id"]: p for p in load_prompts()}
    if payload.prompt_id not in prompts:
        raise HTTPException(400, "提示词版本不存在")
    questions = {q["id"]: q for q in load_questions()}
    picked = [questions[q] for q in payload.question_ids if q in questions]
    if not picked or not payload.sizes:
        raise HTTPException(400, "至少选一道题和一个规模")
    master = load_master()
    by_name = {d["name"]: d for d in master}
    run_id = time.strftime("%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    RUNS[run_id] = {"id": run_id, "status": "running", "total": 0, "done": 0,
                    "records": [], "stop": False, "error": "",
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "prompt_id": payload.prompt_id, "model": cfg["model"]}
    threading.Thread(target=do_run, daemon=True, args=(
        run_id, cfg, prompts[payload.prompt_id], picked,
        payload.sizes, payload.repeats, master, by_name)).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}")
def api_run_state(run_id: str):
    state = RUNS.get(run_id)
    if state is None:
        path = RESULTS_DIR / f"{run_id}.json"
        if not path.exists():
            raise HTTPException(404, "没有这个运行记录")
        state = json.loads(path.read_text(encoding="utf-8"))
    return {**{k: v for k, v in state.items() if k != "stop"},
            "summary": summarize(state["records"])}


@app.post("/api/run/{run_id}/stop")
def api_run_stop(run_id: str):
    if run_id in RUNS:
        RUNS[run_id]["stop"] = True
    return {"ok": True}


@app.get("/api/runs")
def api_runs():
    out = []
    for path in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not data.get("id") or "records" not in data:
            continue
        out.append({"id": data.get("id"), "started_at": data.get("started_at"),
                    "model": data.get("model"), "total": data.get("total"),
                    "done": data.get("done"), "status": data.get("status")})
    return out


@app.get("/api/reply/{run_id}/{qid}/{size}/{rep}")
def api_reply(run_id: str, qid: str, size: int, rep: int):
    path = RESULTS_DIR / f"{run_id}_{qid}_{size}_{rep}.txt"
    if not path.exists():
        raise HTTPException(404, "没有这次的回复原文")
    return {"text": path.read_text(encoding="utf-8")}


# ---------- 复核分歧 ----------
#
# 确定性评分只能告诉你「模型的输出和答案键对不上」，分不清是**模型漏了**还是
# **答案键定错了**。实测撞过：Q2 的答案里塞了一家设备商和一家同层 Pack 厂，模型
# 不选它们其实是对的，却被记成漏检，召回率凭空掉了 16 个点。
#
# 所以这里加第二次调用，但**只裁判分歧的那几行**，不复核整份输出：
#   - 把 300 行的表格再过一遍，钱和时间翻倍，还引入新的不确定性，换不来任何东西；
#   - 分歧通常只有几条，且跨重复、跨规模是同一批，按 (题目, 标的) 去重后近乎免费。
#
# 裁判是**盲判**：不告诉它模型选没选、答案键怎么标的，只问「这家该不该推给这个买家」。
# 告诉它就会锚定，等于让它去附和某一方，那这次复核就白做了。

REVIEW_DIR = RESULTS_DIR / "reviews"
REVIEW_DIR.mkdir(exist_ok=True)
REVIEW_CACHE = REVIEW_DIR / "cache.json"

REVIEWS: dict[str, dict[str, Any]] = {}
REVIEWS_LOCK = threading.Lock()

JUDGE_SYSTEM = """你是并购撮合的资深投行顾问。现在做的是「答案键复核」：有人手工标注了一份
「某买家需求应该命中哪些标的」的答案，你要独立判断其中一条标的标得对不对。

判断口径：
- 业务匹配分三种，都算该命中：横向（做同一件事）、纵向（上下游）、相邻（技术相通或客户相通）。
- **只看业务本身。** 营收、地区、上市与否一律不作为该不该命中的理由。
- **只依据给出的业务说明，绝不能从公司名或标签推断业务。** 业务说明为空或过短就判「说不准」。
- 一家公司可能有好几门生意，对口的可能是写在中段的第二门 —— 整段读完再下结论。
- 宁可判「说不准」，也不要硬凑一个理由。"""

JUDGE_USER = """买家需求：{question}

待判断的标的：
名称：{name}
标签（人工录入，可能滞后或写错，仅供参考）：{tags_text}
业务说明：{summary}

这家标的该不该推荐给这个买家？

只输出一行 JSON，不要代码块，不要任何其他文字：
{{"verdict":"该命中|不该命中|说不准","type":"横向|纵向|相邻|无","reason":"不超过40字，必须落在业务摘要的具体内容上"}}"""

_JUDGE_JSON = re.compile(r"\{[^{}]*\"verdict\"[^{}]*\}")

# (答案键里的角色, 裁判结论) → 该怎么办。带 ★ 的是「答案键该改」。
VERDICT_ACTION = {
    ("expected", "该命中"): ("答案键没问题，模型确实漏了", False),
    ("expected", "不该命中"): ("★ 答案键该删掉这条", True),
    ("neither", "该命中"): ("★ 答案键该补上这条", True),
    ("neither", "不该命中"): ("模型多选了，可加进禁忌名单", False),
    ("must_not", "该命中"): ("★ 禁忌名单该删掉这条", True),
    ("must_not", "不该命中"): ("答案键没问题，模型确实误判", False),
}
KIND_CN = {"expected": "漏检", "neither": "额外召回", "must_not": "误检"}


def _hit_names_of(run_id: str, rec: dict[str, Any], question: dict[str, Any],
                  master: list[dict[str, Any]]) -> set[str] | None:
    """取这一次实际命中的标的名单。

    新跑的记录里直接有 hit_names；旧记录没有，就从存下来的回复原文重算 ——
    切片是 seed 固定的纯函数，重算得到的行号映射和当时完全一致。
    """
    if rec.get("hit_names") is not None:
        return {n for n in str(rec["hit_names"]).split("、") if n}
    path = RESULTS_DIR / f"{run_id}_{rec['question']}_{rec['size']}_{rec['rep']}.txt"
    if not path.exists():
        return None
    parsed, _ = parse_reply(path.read_text(encoding="utf-8"))
    if parsed is None:
        return None
    try:
        rows, row_to_name = build_slice(master, rec["size"], question.get("protected", []),
                                        seed=1000 + rec["size"])
    except SystemExit:
        return None
    if len(rows) != rec["size"]:
        return None
    return {row_to_name.get(r) for r in parsed["hit"]} - {None}


def collect_disputes(run_id: str, records: list[dict[str, Any]],
                     questions: dict[str, dict[str, Any]],
                     master: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """把整轮的分歧按 (题目, 标的) 去重，返回待裁判清单和跳过原因。"""
    by_name = {d["name"]: d for d in master}
    tally: dict[tuple[str, str], dict[str, Any]] = {}
    notes: list[str] = []
    per_q: dict[str, int] = {}
    usable = 0
    for rec in records:
        if rec.get("error"):
            continue
        question = questions.get(rec["question"])
        if question is None:
            notes.append(f"题目 {rec['question']} 已被删掉，跳过")
            continue
        hits = _hit_names_of(run_id, rec, question, master)
        if hits is None:
            notes.append(f"{rec['question']} N={rec['size']} #{rec['rep']} 取不到命中名单，跳过")
            continue
        usable += 1
        per_q[rec["question"]] = per_q.get(rec["question"], 0) + 1
        expected = set(question.get("expected", []))
        must_not = set(question.get("must_not", []))
        for name in expected | must_not | hits:
            role = "expected" if name in expected else ("must_not" if name in must_not else "neither")
            item = tally.setdefault((rec["question"], name), {
                "qid": rec["question"], "question_name": question.get("name", ""),
                "question_prompt": question.get("prompt", ""), "name": name, "role": role,
                "tags_text": "、".join(by_name.get(name, {}).get("tags") or []),
                "summary": by_name.get(name, {}).get("summary", ""),
                "times_hit": 0, "times_total": 0,
            })
            item["times_hit"] += 1 if name in hits else 0
    # 只留真有分歧的：该命中却没全中、不该命中却中了、答案之外被选中
    out = []
    for item in tally.values():
        total = per_q.get(item["qid"], 0)
        item["times_total"] = total
        role, hit = item["role"], item["times_hit"]
        if role == "expected" and hit == total:
            continue
        if role in ("must_not", "neither") and hit == 0:
            continue
        item["kind"] = KIND_CN[role]
        out.append(item)
    if not usable:
        notes.append("这轮没有可用的记录（记录全是失败的）")
    # 排序按「这条分歧有多稳定」，而稳定的方向随角色相反：
    #   漏检——一次都没被选中，最可能是答案键定错了；15 次里漏 1 次只是模型抖动。
    #   额外召回/误检——反过来，次次都被选中才说明答案键漏了它。
    # 这个方向搞反，limit_per_question 截断时留下的恰好是最没信息量的那批。
    out.sort(key=lambda d: (d["qid"], d["role"],
                            d["times_hit"] if d["role"] == "expected" else -d["times_hit"],
                            d["name"]))
    return out, notes


def _cache_load() -> dict[str, Any]:
    if REVIEW_CACHE.exists():
        try:
            return json.loads(REVIEW_CACHE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def _cache_key(item: dict[str, Any], model: str) -> str:
    # 题面或摘要一改，缓存自然失效；换模型也重判。
    raw = "\x1f".join([model, item["qid"], item["question_prompt"], item["name"], item["summary"]])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def judge_one(cfg, item: dict[str, Any]) -> dict[str, Any]:
    text, usage, elapsed = chat_with_retry(
        cfg, JUDGE_SYSTEM,
        JUDGE_USER.format(question=item["question_prompt"], name=item["name"],
                          tags_text=item["tags_text"] or "（未录）",
                          summary=item["summary"] or "（未录入）"),
    )
    found = _JUDGE_JSON.findall(text)
    if not found:
        return {"verdict": "说不准", "type": "无",
                "reason": "裁判没按格式回复：" + text.strip()[:80],
                "elapsed": round(elapsed, 1), **usage}
    try:
        data = json.loads(found[-1])
    except ValueError:
        return {"verdict": "说不准", "type": "无", "reason": "裁判回复解析失败",
                "elapsed": round(elapsed, 1), **usage}
    verdict = str(data.get("verdict", "")).strip()
    if verdict not in ("该命中", "不该命中", "说不准"):
        verdict = "说不准"
    return {"verdict": verdict, "type": str(data.get("type", "无")).strip(),
            "reason": str(data.get("reason", "")).strip()[:120],
            "elapsed": round(elapsed, 1), **usage}


def do_review(review_id: str, cfg, items: list[dict[str, Any]]) -> None:
    state = REVIEWS[review_id]
    cache = _cache_load()
    model = cfg["model"]

    def one(item):
        if state["stop"]:
            return
        key = _cache_key(item, model)
        cached = cache.get(key)
        if cached:
            verdict = {**cached, "cached": True}
        else:
            try:
                verdict = judge_one(cfg, item)
            except Exception as error:  # noqa: BLE001 —— 单条裁判失败不该中断整轮
                verdict = {"verdict": "说不准", "type": "无",
                           "reason": f"{type(error).__name__}: {error}", "elapsed": 0}
            else:
                with REVIEWS_LOCK:
                    cache[key] = verdict
        action, key_wrong = VERDICT_ACTION.get(
            (item["role"], verdict["verdict"]), ("人工看一眼", False))
        with REVIEWS_LOCK:
            state["items"].append({**item, **verdict, "action": action, "key_wrong": key_wrong})
            state["done"] += 1

    try:
        with ThreadPoolExecutor(max_workers=int(cfg.get("concurrency", 2))) as pool:
            list(pool.map(one, items))
        state["status"] = "stopped" if state["stop"] else "done"
    except Exception as error:  # noqa: BLE001 —— 整轮崩了也要让界面看到原因
        state["status"] = "error"
        state["error"] = f"{type(error).__name__}: {error}"
    # 答案键该改的排最前面，那才是这份清单的用处
    state["items"].sort(key=lambda d: (not d["key_wrong"], d["qid"], d["role"]))
    REVIEW_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    (REVIEW_DIR / f"{review_id}.json").write_text(
        json.dumps(state | {"stop": False}, ensure_ascii=False, indent=1), encoding="utf-8")


class ReviewIn(BaseModel):
    qids: list[str] | None = None
    limit_per_question: int = 20


def _disputes_of(run_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    state = RUNS.get(run_id)
    if state is None:
        path = RESULTS_DIR / f"{run_id}.json"
        if not path.exists():
            raise HTTPException(404, "没有这个运行记录")
        state = json.loads(path.read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in load_questions()}
    return collect_disputes(run_id, state["records"], questions, load_master())


@app.get("/api/review/{run_id}/disputes")
def api_review_disputes(run_id: str):
    """只算不判：先让人看清楚有多少条分歧、要花多少次调用，再决定跑不跑。

    Q8 那种「答案是空集」的抗硬凑题，模型一口气命中三十家，全都算分歧 ——
    不给预览就直接开跑，等于替人做了一个花钱的决定。
    """
    items, notes = _disputes_of(run_id)
    cache = _cache_load()
    cfg = read_config()
    for item in items:
        item["cached"] = _cache_key(item, cfg.get("model", "")) in cache
    return {"items": items, "notes": notes, "total": len(items),
            "cached": sum(1 for i in items if i["cached"])}


@app.post("/api/review/{run_id}")
def api_review_start(run_id: str, payload: ReviewIn):
    cfg = read_config()
    if not cfg.get("api_key"):
        raise HTTPException(400, "还没填 API Key")
    items, notes = _disputes_of(run_id)
    if payload.qids is not None:
        items = [i for i in items if i["qid"] in set(payload.qids)]
    if payload.limit_per_question > 0:
        seen: dict[str, int] = {}
        capped = []
        for item in items:
            n = seen.get(item["qid"], 0)
            if n >= payload.limit_per_question:
                continue
            seen[item["qid"]] = n + 1
            capped.append(item)
        if len(capped) < len(items):
            notes.append(f"每题最多复核 {payload.limit_per_question} 条，"
                         f"截掉了 {len(items) - len(capped)} 条低频分歧")
        items = capped
    REVIEWS[run_id] = {"id": run_id, "status": "running" if items else "done",
                       "total": len(items), "done": 0, "items": [], "stop": False,
                       "error": "", "notes": notes, "model": cfg["model"],
                       "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if items:
        threading.Thread(target=do_review, daemon=True, args=(run_id, cfg, items)).start()
    return {"run_id": run_id, "total": len(items), "notes": notes}


@app.get("/api/review/{run_id}")
def api_review_state(run_id: str):
    state = REVIEWS.get(run_id)
    if state is None:
        path = REVIEW_DIR / f"{run_id}.json"
        if not path.exists():
            # 「还没复核过」不是错误 —— 界面每次切换运行记录都会来问一次。
            # 这里返回 404 的话，控制台上就永远躺着一排红色，真出问题时反而看不出来。
            return {"id": run_id, "status": "none", "total": 0, "done": 0, "items": None}
        state = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in state.items() if k != "stop"}


@app.post("/api/review/{run_id}/stop")
def api_review_stop(run_id: str):
    if run_id in REVIEWS:
        REVIEWS[run_id]["stop"] = True
    return {"ok": True}


def main() -> None:
    import uvicorn
    port = int(os.environ.get("EVAL_APP_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  标的匹配评测台已启动： {url}")
    print("  关闭这个窗口即停止服务。\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
