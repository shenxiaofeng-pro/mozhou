import hashlib
import io
from dataclasses import dataclass
from typing import Any, Literal, cast

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_TEXT_FILE_BYTES = 20 * 1024 * 1024
MAX_PDF_FILE_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 20_000_000
MAX_PDF_PAGES = 2_000
MAX_PDF_EXPANSION_RATIO = 200
PREVIEW_CHARACTERS = 2_000


class UnsafeImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceSpan:
    page_number: int
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class ParsedReferenceFile:
    source_format: Literal["txt", "markdown", "pdf"]
    source_encoding: str
    encoding_confidence: float
    import_state: Literal["ready", "needs_review"]
    source_sha256: str
    content_sha256: str
    content: str
    preview: str
    page_count: int
    spans: tuple[SourceSpan, ...]
    warnings: tuple[str, ...]


def _normalize_text(value: str) -> str:
    return value.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def _validate_decoded_text(value: str) -> tuple[Literal["ready", "needs_review"], tuple[str, ...]]:
    if not value.strip():
        raise UnsafeImportError("empty_content")
    if "\x00" in value:
        raise UnsafeImportError("null_byte")
    if len(value) > MAX_EXTRACTED_CHARACTERS:
        raise UnsafeImportError("extracted_text_too_large")
    controls = sum(ord(character) < 32 and character not in "\n\t" for character in value)
    if controls > max(4, len(value) // 1_000):
        raise UnsafeImportError("unsafe_control_characters")
    mojibake_markers = ("\ufffd", "锟斤拷", "烫烫烫", "屯屯屯")
    warnings = ("suspected_mojibake",) if any(marker in value for marker in mojibake_markers) else ()
    return ("needs_review" if warnings else "ready"), warnings


def _parse_text(
    extension: str,
    payload: bytes,
) -> tuple[str, float, Literal["ready", "needs_review"], str, tuple[str, ...]]:
    if len(payload) > MAX_TEXT_FILE_BYTES:
        raise UnsafeImportError("file_too_large")
    if payload.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
        confidence = 1.0
        try:
            content = payload.decode(encoding)
        except UnicodeDecodeError as error:
            raise UnsafeImportError("invalid_utf8_bom") from error
    else:
        try:
            content = payload.decode("utf-8")
            encoding = "utf-8"
            confidence = 0.99
        except UnicodeDecodeError:
            try:
                content = payload.decode("gb18030")
            except UnicodeDecodeError as error:
                raise UnsafeImportError("unsupported_or_mixed_encoding") from error
            encoding = "gb18030"
            non_ascii = sum(ord(character) > 127 for character in content)
            confidence = 0.92 if non_ascii >= max(2, len(content) // 20) else 0.72
    normalized = _normalize_text(content)
    state, warnings = _validate_decoded_text(normalized)
    if confidence < 0.8:
        state = "needs_review"
        warnings = (*warnings, "low_encoding_confidence")
    return encoding, confidence, state, normalized, warnings


def _pdf_has_active_content(reader: PdfReader) -> bool:
    root = reader.trailer.get("/Root")
    if root is None:
        return True
    root_object = cast(Any, root)
    if hasattr(root_object, "get_object"):
        root_object = root_object.get_object()
    if root_object.get("/OpenAction") is not None or root_object.get("/AA") is not None:
        return True
    names_object = cast(Any, root_object.get("/Names"))
    if names_object is not None and hasattr(names_object, "get_object"):
        names_object = names_object.get_object()
    if names_object is not None and names_object.get("/JavaScript") is not None:
        return True
    acro_object = cast(Any, root_object.get("/AcroForm"))
    if acro_object is not None and hasattr(acro_object, "get_object"):
        acro_object = acro_object.get_object()
    if acro_object is not None and (
        acro_object.get("/XFA") is not None or acro_object.get("/AA") is not None
    ):
        return True
    return any(page.get("/AA") is not None for page in reader.pages)


def _parse_pdf(
    payload: bytes,
) -> tuple[str, int, tuple[SourceSpan, ...], tuple[str, ...]]:
    if len(payload) > MAX_PDF_FILE_BYTES:
        raise UnsafeImportError("file_too_large")
    if not payload.startswith(b"%PDF-"):
        raise UnsafeImportError("invalid_pdf_magic")
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise UnsafeImportError("encrypted_pdf")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UnsafeImportError("pdf_page_limit")
        if _pdf_has_active_content(reader):
            raise UnsafeImportError("active_pdf_content")
        page_texts: list[str] = []
        spans: list[SourceSpan] = []
        cursor = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "").strip()
            if not text:
                continue
            if page_texts:
                cursor += 2
            start = cursor
            cursor += len(text)
            if cursor > MAX_EXTRACTED_CHARACTERS:
                raise UnsafeImportError("extracted_text_too_large")
            spans.append(SourceSpan(page_number=page_number, start_char=start, end_char=cursor))
            page_texts.append(text)
        content = "\n\n".join(page_texts)
    except UnsafeImportError:
        raise
    except (PdfReadError, OSError, TypeError, ValueError, KeyError) as error:
        raise UnsafeImportError("invalid_pdf") from error
    if not content:
        raise UnsafeImportError("empty_pdf_text")
    if len(content) > max(2_000_000, len(payload) * MAX_PDF_EXPANSION_RATIO):
        raise UnsafeImportError("pdf_expansion_limit")
    _validate_decoded_text(content)
    return content, len(reader.pages), tuple(spans), ()


def parse_reference_file(filename: str, payload: bytes) -> ParsedReferenceFile:
    cleaned_filename = filename.strip()
    if (
        not cleaned_filename
        or "\x00" in cleaned_filename
        or "/" in cleaned_filename
        or "\\" in cleaned_filename
        or "." not in cleaned_filename
    ):
        raise UnsafeImportError("invalid_filename")
    extension = cleaned_filename.lower().rsplit(".", 1)[-1]
    source_sha256 = hashlib.sha256(payload).hexdigest()
    spans: tuple[SourceSpan, ...] = ()
    page_count = 0
    if extension in {"txt", "md", "markdown"}:
        encoding, confidence, state, content, warnings = _parse_text(extension, payload)
        source_format: Literal["txt", "markdown", "pdf"] = (
            "txt" if extension == "txt" else "markdown"
        )
    elif extension == "pdf":
        content, page_count, spans, warnings = _parse_pdf(payload)
        encoding = "pdf-text"
        confidence = 1.0
        state = "ready"
        source_format = "pdf"
    else:
        raise UnsafeImportError("unsupported_format")
    return ParsedReferenceFile(
        source_format=source_format,
        source_encoding=encoding,
        encoding_confidence=confidence,
        import_state=state,
        source_sha256=source_sha256,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
        preview=content[:PREVIEW_CHARACTERS],
        page_count=page_count,
        spans=spans,
        warnings=warnings,
    )
