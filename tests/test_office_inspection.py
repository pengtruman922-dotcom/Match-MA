from io import BytesIO
from zipfile import ZipFile

from backend.app.services.office_inspection import inspect_office_text, office_document_kind


def _zip_bytes(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_office_document_kind_uses_mime_when_extension_is_not_available() -> None:
    assert (
        office_document_kind(
            file_name="黄河产业集团投资意向",
            file_type=None,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        == "docx"
    )


def test_inspect_docx_text_from_document_xml() -> None:
    data = _zip_bytes(
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>黄河产业集团</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        }
    )

    result = inspect_office_text(data, file_name="demo.docx")

    assert result.document_kind == "docx"
    assert result.has_text is True
    assert "黄河产业集团" in result.extracted_text


def test_inspect_xlsx_text_from_shared_strings() -> None:
    data = _zip_bytes(
        {
            "xl/sharedStrings.xml": """
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <si><t>买方名称</t></si><si><t>广州城投</t></si>
            </sst>
            """,
            "xl/worksheets/sheet1.xml": """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
              </sheetData>
            </worksheet>
            """,
        }
    )

    result = inspect_office_text(data, file_name="demo.xlsx")

    assert result.document_kind == "xlsx"
    assert "买方名称\t广州城投" in result.extracted_text


def test_inspect_pptx_text_from_slides() -> None:
    data = _zip_bytes(
        {
            "ppt/slides/slide1.xml": """
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>项目亮点</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
            </p:sld>
            """,
        }
    )

    result = inspect_office_text(data, file_name="demo.pptx")

    assert result.document_kind == "pptx"
    assert "项目亮点" in result.extracted_text


def test_inspect_invalid_office_zip_returns_error() -> None:
    result = inspect_office_text(b"not a zip", file_name="demo.docx")

    assert result.has_text is False
    assert result.error_message
