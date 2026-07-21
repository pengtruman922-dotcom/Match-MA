"""Entity anchoring for researched evidence.

The most common way web research corrupts a database is not hallucination — it
is a page about a different company with a similar name. A claim is only
accepted when its supporting text carries a feature that ties it to this
specific entity: the unified social credit code, the registered legal name, the
company's own domain, or the legal representative. Without that gate, the more
diligently the agent researches, the dirtier the library gets, and it gets
dirty in a way nobody notices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

# 统一社会信用代码：18 位，数字与大写字母（不含 I O S V Z）
CREDIT_CODE_PATTERN = re.compile(r"\b[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}\b")

# 名称型锚点太短时会误命中（"中电""华能"随处可见），设下限。
MIN_NAME_ANCHOR_LENGTH = 4


@dataclass(frozen=True)
class AnchorMatch:
    kind: str
    value: str


def build_anchors(entity: dict[str, Any]) -> dict[str, list[str]]:
    """Collect the identifying features we can check evidence against."""
    anchors: dict[str, list[str]] = {
        "credit_code": [],
        "name": [],
        "domain": [],
        "legal_person": [],
        "region": [],
    }

    for key in ("unified_social_credit_code", "credit_code"):
        value = str(entity.get(key) or "").strip()
        if value:
            anchors["credit_code"].append(value)

    for key in ("target_subject_name", "target_name", "legal_name", "buyer_name"):
        value = str(entity.get(key) or "").strip()
        if len(value) >= MIN_NAME_ANCHOR_LENGTH and value not in anchors["name"]:
            anchors["name"].append(value)

    aliases = entity.get("aliases_json")
    if isinstance(aliases, list):
        for alias in aliases:
            value = str(alias or "").strip()
            if len(value) >= MIN_NAME_ANCHOR_LENGTH and value not in anchors["name"]:
                anchors["name"].append(value)

    for key in ("official_website", "website", "homepage_url"):
        domain = _domain_of(str(entity.get(key) or ""))
        if domain and domain not in anchors["domain"]:
            anchors["domain"].append(domain)

    for key in ("legal_representative", "legal_person"):
        value = str(entity.get(key) or "").strip()
        if len(value) >= 2 and value not in anchors["legal_person"]:
            anchors["legal_person"].append(value)

    for key in (
        "registered_province",
        "registered_city",
        "headquarter_province",
        "headquarter_city",
        "region_province",
        "region_city",
    ):
        value = str(entity.get(key) or "").strip()
        variants = [value]
        short_value = re.sub(r"(壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区|省|市)$", "", value)
        if short_value and short_value != value:
            variants.append(short_value)
        for variant in variants:
            if len(variant) >= 2 and variant not in anchors["region"]:
                anchors["region"].append(variant)

    return {kind: values for kind, values in anchors.items() if values}


def match_anchors(
    anchors: dict[str, list[str]],
    *,
    evidence_text: str,
    source_url: str = "",
) -> list[AnchorMatch]:
    """Which identifying features this piece of evidence actually carries."""
    matches: list[AnchorMatch] = []
    haystack = evidence_text or ""
    source_domain = _domain_of(source_url)

    for value in anchors.get("credit_code", []):
        if value and value in haystack:
            matches.append(AnchorMatch("credit_code", value))
    for value in anchors.get("name", []):
        if value and value in haystack:
            matches.append(AnchorMatch("name", value))
    for value in anchors.get("domain", []):
        if value and (value == source_domain or source_domain.endswith(f".{value}")):
            matches.append(AnchorMatch("domain", value))
    for value in anchors.get("legal_person", []):
        if value and value in haystack:
            matches.append(AnchorMatch("legal_person", value))
    # A city embedded in the legal name (e.g. 杭州星海…) is not independent
    # corroboration. Remove matched names before checking the region anchor.
    region_haystack = haystack
    for name in anchors.get("name", []):
        if name:
            region_haystack = region_haystack.replace(name, "")
    for value in anchors.get("region", []):
        if value and value in region_haystack:
            matches.append(AnchorMatch("region", value))
    return matches


def is_evidence_trusted(matches: list[AnchorMatch]) -> bool:
    """A single name hit is not enough; same-name companies are the norm.

    A credit code or the company's own domain identifies the entity on its own.
    A name only counts when something else corroborates it.
    """
    kinds = {match.kind for match in matches}
    if kinds & {"credit_code", "domain"}:
        return True
    return "name" in kinds and bool(kinds & {"legal_person", "region"})


def _domain_of(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    try:
        host = urlparse(value).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host
