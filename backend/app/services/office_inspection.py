from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


OFFICE_PARSER_VERSION = "ooxml-stdlib-v0.1"


@dataclass(frozen=True)
class OfficeInspectionResult:
    document_kind: str
    parser_name: str
    parser_version: str
    extracted_text: str
    extracted_char_count: int
    item_count: int
    error_message: str | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.extracted_text.strip())


def inspect_office_text(
    file_bytes: bytes,
    *,
    file_name: str | None = None,
    file_type: str | None = None,
    mime_type: str | None = None,
    max_chars: int = 200_000,
) -> OfficeInspectionResult:
    document_kind = office_document_kind(file_name=file_name, file_type=file_type, mime_type=mime_type)
    if document_kind not in {"docx", "xlsx", "pptx"}:
        return _result(document_kind or "unsupported_office", "", 0, "Unsupported Office document type.")

    try:
        with ZipFile(BytesIO(file_bytes)) as archive:
            if document_kind == "docx":
                parts = _extract_docx_parts(archive, max_chars=max_chars)
            elif document_kind == "xlsx":
                parts = _extract_xlsx_parts(archive, max_chars=max_chars)
            else:
                parts = _extract_pptx_parts(archive, max_chars=max_chars)
    except BadZipFile as exc:
        return _result(document_kind, "", 0, f"Invalid OOXML zip document: {exc}")
    except Exception as exc:
        return _result(document_kind, "", 0, str(exc))

    text = _join_limited(parts, max_chars=max_chars)
    return _result(document_kind, text, len(parts), None)


def office_document_kind(
    *,
    file_name: str | None = None,
    file_type: str | None = None,
    mime_type: str | None = None,
) -> str | None:
    suffix = Path(file_name or "").suffix.lower().lstrip(".")
    normalized_type = (file_type or suffix).strip().lower()
    normalized_mime = (mime_type or "").split(";")[0].strip().lower()
    if normalized_type in {"docx", "xlsx", "pptx"}:
        return normalized_type
    mime_map = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    }
    return mime_map.get(normalized_mime)


def _extract_docx_parts(archive: ZipFile, *, max_chars: int) -> list[str]:
    names = [
        name
        for name in archive.namelist()
        if name == "word/document.xml"
        or name.startswith("word/header")
        or name.startswith("word/footer")
        or name.startswith("word/footnotes")
        or name.startswith("word/endnotes")
    ]
    parts: list[str] = []
    for name in sorted(names, key=_natural_key):
        xml_root = _parse_xml_member(archive, name)
        texts = _text_nodes(xml_root, local_names={"t", "instrText"})
        if texts:
            parts.append(f"[{name}]\n" + _collapse_lines(texts))
        if _parts_length(parts) >= max_chars:
            break
    return parts


def _extract_xlsx_parts(archive: ZipFile, *, max_chars: int) -> list[str]:
    shared_strings = _xlsx_shared_strings(archive)
    sheet_names = [
        name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
    ]
    parts: list[str] = []
    for name in sorted(sheet_names, key=_natural_key):
        xml_root = _parse_xml_member(archive, name)
        rows: list[str] = []
        for row in xml_root.iter():
            if _local_name(row.tag) != "row":
                continue
            values = [_xlsx_cell_text(cell, shared_strings) for cell in row if _local_name(cell.tag) == "c"]
            values = [value for value in values if value]
            if values:
                rows.append("\t".join(values))
        if rows:
            parts.append(f"[{name}]\n" + _join_limited(rows, max_chars=max_chars))
        if _parts_length(parts) >= max_chars:
            break
    return parts


def _extract_pptx_parts(archive: ZipFile, *, max_chars: int) -> list[str]:
    slide_names = [
        name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")
    ]
    parts: list[str] = []
    for name in sorted(slide_names, key=_natural_key):
        xml_root = _parse_xml_member(archive, name)
        texts = _text_nodes(xml_root, local_names={"t"})
        if texts:
            parts.append(f"[{name}]\n" + _collapse_lines(texts))
        if _parts_length(parts) >= max_chars:
            break
    return parts


def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _parse_xml_member(archive, "xl/sharedStrings.xml")
    result: list[str] = []
    for item in root.iter():
        if _local_name(item.tag) != "si":
            continue
        result.append("".join(_text_nodes(item, local_names={"t"})).strip())
    return result


def _xlsx_cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return " ".join(_text_nodes(cell, local_names={"t"})).strip()
    value = None
    for child in cell:
        if _local_name(child.tag) == "v":
            value = child.text
            break
    if value is None:
        return ""
    value = value.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(value)].strip()
        except (ValueError, IndexError):
            return value
    return value


def _parse_xml_member(archive: ZipFile, name: str) -> ElementTree.Element:
    with archive.open(name) as member:
        return ElementTree.fromstring(member.read())


def _text_nodes(root: ElementTree.Element, *, local_names: set[str]) -> list[str]:
    texts: list[str] = []
    for item in root.iter():
        if _local_name(item.tag) in local_names and item.text:
            text = item.text.strip()
            if text:
                texts.append(text)
    return texts


def _local_name(tag: Any) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _collapse_lines(values: list[str]) -> str:
    return "\n".join(value.strip() for value in values if value and value.strip())


def _join_limited(values: list[str], *, max_chars: int) -> str:
    parts: list[str] = []
    total = 0
    for value in values:
        if not value:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        clipped = value[:remaining]
        parts.append(clipped)
        total += len(clipped) + 2
    return "\n\n".join(parts).strip()


def _parts_length(values: list[str]) -> int:
    return sum(len(value) for value in values)


def _natural_key(value: str) -> list[Any]:
    parts: list[Any] = []
    current = ""
    digit_mode = False
    for char in value:
        is_digit = char.isdigit()
        if current and is_digit != digit_mode:
            parts.append(int(current) if digit_mode else current)
            current = ""
        current += char
        digit_mode = is_digit
    if current:
        parts.append(int(current) if digit_mode else current)
    return parts


def _result(
    document_kind: str,
    extracted_text: str,
    item_count: int,
    error_message: str | None,
) -> OfficeInspectionResult:
    return OfficeInspectionResult(
        document_kind=document_kind,
        parser_name="office_text_layer",
        parser_version=OFFICE_PARSER_VERSION,
        extracted_text=extracted_text.strip(),
        extracted_char_count=len(extracted_text.strip()),
        item_count=item_count,
        error_message=error_message,
    )
