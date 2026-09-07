"""多方案需求的文本去重 —— 输出层的机械处理，不动数据、不让解析器猜。

一条需求拆成「上市 / 非上市」两档之后，两个方案的「其他要求」常常有大半是一模一样的
（2026-09-07 实测：南宁轨道 83%、物产中大 83%、岭南 47%、洛阳科创 47%）。
全量买家扫描时这些重复直接乘在 token 上。

**不在数据里加「公共说明」字段。** 0901 取消公共层正是因为解析器猜不出某条约束属于
哪一档，让它再写一份「整体摘要」等于把这个猜测请回来。这里的去重是精确的：
只有在**每一个**方案里都出现的句子才提到「各方案共同要求」，剩下的原样留在各自方案里。
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"[。；;\n]+")
_LEADING_NUMBER = re.compile(
    r"^\s*(?:[0-9０-９]+[.、．)）]|[（(][0-9０-９一二三四五六七八九十]+[)）]|[一二三四五六七八九十]+[、.])\s*"
)
_COMPARE_NOISE = re.compile(r"[\s，,、：:“”‘’\"'（）()【】\[\]·—_-]+")


def split_requirement_sentences(text: str | None) -> list[str]:
    """按句号、分号、换行切句，去掉「1.」「（一）」这类序号，保留原文其余部分。"""
    if not text:
        return []
    sentences: list[str] = []
    for piece in _SENTENCE_SPLIT.split(str(text)):
        cleaned = _LEADING_NUMBER.sub("", piece).strip()
        if len(cleaned) >= 2:
            sentences.append(cleaned)
    return sentences


def _compare_key(sentence: str) -> str:
    return _COMPARE_NOISE.sub("", sentence)


def dedupe_scenario_requirements(texts: list[str | None]) -> tuple[list[str], list[str | None]]:
    """把各方案都有的句子提出来。

    返回 ``(shared, remaining)``：``shared`` 按第一个方案里的出现顺序排列；
    ``remaining[i]`` 是第 i 个方案去掉共同句子后剩下的文本（用「；」重连），
    什么都不剩时为 ``None``。只有一个方案时不做任何事，原样返回。
    """
    if len(texts) < 2:
        return [], [str(t).strip() or None if t else None for t in texts]
    per_scenario = [split_requirement_sentences(t) for t in texts]
    if any(not sentences for sentences in per_scenario):
        # 有方案根本没写其他要求，就没有「各方案都有」这回事。
        return [], [_rejoin(sentences) for sentences in per_scenario]
    keys = [{_compare_key(s) for s in sentences} for sentences in per_scenario]
    shared_keys = set.intersection(*keys)
    if not shared_keys:
        return [], [_rejoin(sentences) for sentences in per_scenario]
    shared: list[str] = []
    seen: set[str] = set()
    for sentence in per_scenario[0]:
        key = _compare_key(sentence)
        if key in shared_keys and key not in seen:
            shared.append(sentence)
            seen.add(key)
    remaining = [
        _rejoin([s for s in sentences if _compare_key(s) not in shared_keys])
        for sentences in per_scenario
    ]
    return shared, remaining


def _rejoin(sentences: list[str]) -> str | None:
    return "；".join(sentences) or None
