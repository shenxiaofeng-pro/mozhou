from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.main import create_app
from app.safe_import import MAX_TEXT_FILE_BYTES, UnsafeImportError, parse_reference_file


def _pdf_bytes(*pages: str, encrypted: bool = False, javascript: bool = False) -> bytes:
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): writer._add_object(font),
            }),
        })
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    if javascript:
        writer.add_js("app.alert('unsafe')")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "payload", "encoding", "text"),
    [
        ("utf8.txt", "第一章\n南平".encode(), "utf-8", "第一章\n南平"),
        ("bom.md", b"\xef\xbb\xbf" + "标题\n正文".encode(), "utf-8-sig", "标题\n正文"),
        ("gb.txt", "第一章\n闽北旧城".encode("gb18030"), "gb18030", "第一章\n闽北旧城"),
    ],
)
def test_text_import_detects_supported_encodings_without_data_loss(
    filename: str,
    payload: bytes,
    encoding: str,
    text: str,
) -> None:
    parsed = parse_reference_file(filename, payload)

    assert parsed.source_format in {"txt", "markdown"}
    assert parsed.source_encoding == encoding
    assert parsed.content == text
    assert parsed.import_state == "ready"
    assert parsed.preview == text


def test_text_import_blocks_mixed_encoding_and_marks_mojibake_for_review() -> None:
    with pytest.raises(UnsafeImportError, match="unsupported_or_mixed_encoding"):
        parse_reference_file("mixed.txt", b"UTF-8 prefix\xff\xff")

    suspicious = parse_reference_file("mojibake.txt", "锟斤拷锟斤拷正文".encode())

    assert suspicious.import_state == "needs_review"
    assert "suspected_mojibake" in suspicious.warnings


def test_text_import_rejects_oversize_before_decoding() -> None:
    with pytest.raises(UnsafeImportError, match="file_too_large"):
        parse_reference_file("huge.txt", b"x" * (MAX_TEXT_FILE_BYTES + 1))


def test_pdf_extracts_page_ranges_and_rejects_active_or_encrypted_files() -> None:
    parsed = parse_reference_file("pages.pdf", _pdf_bytes("page one", "page two"))

    assert parsed.source_format == "pdf"
    assert parsed.source_encoding == "pdf-text"
    assert parsed.content == "page one\n\npage two"
    assert [(span.page_number, span.start_char, span.end_char) for span in parsed.spans] == [
        (1, 0, 8),
        (2, 10, 18),
    ]

    with pytest.raises(UnsafeImportError, match="encrypted_pdf"):
        parse_reference_file("locked.pdf", _pdf_bytes("secret", encrypted=True))
    with pytest.raises(UnsafeImportError, match="active_pdf_content"):
        parse_reference_file("script.pdf", _pdf_bytes("unsafe", javascript=True))


def test_pdf_rejects_empty_text_and_mismatched_magic() -> None:
    with pytest.raises(UnsafeImportError, match="empty_pdf_text"):
        parse_reference_file("blank.pdf", _pdf_bytes(""))
    with pytest.raises(UnsafeImportError, match="invalid_pdf_magic"):
        parse_reference_file("fake.pdf", b"not a pdf")


def test_file_api_requires_matching_preview_and_explicit_uncertain_confirmation(
    tmp_path: Path,
) -> None:
    payload = "锟斤拷锟斤拷正文".encode()
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        preview = client.post(
            "/api/reference-library/file-previews",
            params={"source_filename": "review.txt"},
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        blocked = client.post(
            "/api/reference-library/file-imports",
            params={
                "source_filename": "review.txt",
                "title": "待确认编码",
                "rights_basis": "self_owned",
                "expected_source_sha256": preview.json()["source_sha256"],
                "confirm_preview": "true",
            },
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        imported = client.post(
            "/api/reference-library/file-imports",
            params={
                "source_filename": "review.txt",
                "title": "已确认编码",
                "rights_basis": "self_owned",
                "expected_source_sha256": preview.json()["source_sha256"],
                "confirm_preview": "true",
                "confirm_uncertain_encoding": "true",
            },
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        )

    assert preview.status_code == 200
    assert preview.json()["import_state"] == "needs_review"
    assert blocked.status_code == 409
    assert imported.status_code == 201
    assert imported.json()["import_state"] == "needs_review"
    assert imported.json()["source_sha256"] == preview.json()["source_sha256"]


def test_pdf_file_api_persists_page_provenance_without_returning_original_text(
    tmp_path: Path,
) -> None:
    payload = _pdf_bytes("page one", "page two")
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        preview = client.post(
            "/api/reference-library/file-previews",
            params={"source_filename": "pages.pdf"},
            content=payload,
            headers={"Content-Type": "application/pdf"},
        ).json()
        imported = client.post(
            "/api/reference-library/file-imports",
            params={
                "source_filename": "pages.pdf",
                "title": "分页资料",
                "rights_basis": "authorized",
                "expected_source_sha256": preview["source_sha256"],
                "confirm_preview": "true",
            },
            content=payload,
            headers={"Content-Type": "application/pdf"},
        )

    assert imported.status_code == 201
    assert imported.json()["source_format"] == "pdf"
    assert imported.json()["source_spans"] == preview["source_spans"]
    assert '"content":' not in imported.text


def test_reality_file_creates_unconfirmed_provenance_card_and_reuses_global_document(
    tmp_path: Path,
) -> None:
    payload = "1998 年南平铝厂先摸底岗位，再公布分流方案。".encode("gb18030")
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        first_project = client.post(
            "/api/projects",
            json={
                "title": "南平厂事",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()["project"]["id"]
        second_project = client.post(
            "/api/projects",
            json={
                "title": "闽北新局",
                "genre": "urban_rebirth",
                "rebirth_year": 1999,
                "rebirth_location": "福建南平",
            },
        ).json()["project"]["id"]
        preview = client.post(
            "/api/reference-library/file-previews",
            params={"source_filename": "factory.txt"},
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        ).json()
        created = client.post(
            "/api/source-library/file-imports",
            params={
                "project_id": first_project,
                "source_filename": "factory.txt",
                "title": "南平铝厂改制资料",
                "source_kind": "industry",
                "source_reference": "作者本地档案 1998-04",
                "applicable_year_start": 1998,
                "applicable_year_end": 1999,
                "confidence": "high",
                "source_date": "1998-04",
                "expected_source_sha256": preview["source_sha256"],
                "confirm_preview": "true",
            },
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        documents = client.get("/api/source-library/documents")
        document_id = documents.json()[0]["id"]
        reused = client.post(
            f"/api/projects/{second_project}/source-documents/{document_id}/cards",
            json={
                "source_kind": "industry",
                "title": "铝厂岗位摸底",
                "source_reference": "复用全局现实资料",
                "applicable_year_start": 1998,
                "applicable_year_end": 2000,
                "confidence": "medium",
            },
        )
        deleted = client.delete(
            f"/api/source-library/documents/{document_id}?confirm_purge=true"
        )
        first_workspace = client.get(f"/api/projects/{first_project}").json()

    assert created.status_code == 201
    assert created.json()["confirmed"] is False
    assert created.json()["source_document_id"] == document_id
    assert created.json()["source_date"] == "1998-04"
    assert created.json()["start_char"] == 0
    assert created.json()["end_char"] == len(created.json()["excerpt"])
    assert documents.status_code == 200
    assert '"content":' not in documents.text
    assert reused.status_code == 201
    assert reused.json()["source_document_id"] == document_id
    assert deleted.json() == {"affected_cards": 2}
    assert first_workspace["source_cards"][0]["source_document_id"] is None
    assert first_workspace["source_cards"][0]["excerpt"]
