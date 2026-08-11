from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from sqlite3 import Row
from uuid import uuid4
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from app.database import Database
from app.models import (
    ChapterStatus,
    ChapterVersionSource,
    ConfirmManuscriptImportRequest,
    ManuscriptExport,
    Workspace,
)
from app.repository import NotFoundError, ProjectRepository, now_iso
from app.review.repository import ReviewRepository


class ManuscriptService:
    def __init__(self, database: Database, projects: ProjectRepository) -> None:
        self.database = database
        self.projects = projects

    def confirm_import(self, request: ConfirmManuscriptImportRequest) -> Workspace:
        project_id = str(uuid4())
        timestamp = now_iso()
        chapter_number = 0
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, title, genre, rebirth_year, rebirth_location,
                    chapter_target_words, safety_buffer_chapters, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    request.title,
                    request.genre.value,
                    request.rebirth_year,
                    request.rebirth_location,
                    request.chapter_target_words,
                    request.safety_buffer_chapters,
                    timestamp,
                    timestamp,
                ),
            )
            for volume_number, volume in enumerate(request.volumes, start=1):
                volume_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO manuscript_volumes (
                        id, project_id, volume_number, title, sort_key,
                        revision, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        volume_id,
                        project_id,
                        volume_number,
                        volume.title,
                        volume_number * 1024,
                        timestamp,
                        timestamp,
                    ),
                )
                for volume_chapter_number, imported in enumerate(volume.chapters, start=1):
                    chapter_number += 1
                    chapter_id = str(uuid4())
                    content = imported.content
                    if (
                        chapter_number == 1
                        and request.unrecognized_text
                        and request.unrecognized_action == "prepend_first_chapter"
                    ):
                        content = (
                            f"{request.unrecognized_text.rstrip()}\n\n{content.lstrip()}".strip()
                        )
                    connection.execute(
                        """
                        INSERT INTO chapters (
                            id, project_id, volume_id, volume_number, chapter_number,
                            sort_key, title, content, reader_promise, opening_hook,
                            state_change, emotional_payoff, ending_cliffhanger,
                            status, revision, deleted_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '', ?, 0, NULL, ?)
                        """,
                        (
                            chapter_id,
                            project_id,
                            volume_id,
                            volume_number,
                            chapter_number,
                            volume_chapter_number * 1024,
                            imported.title,
                            content,
                            (
                                ChapterStatus.DRAFTED.value
                                if content.strip()
                                else ChapterStatus.PLANNED.value
                            ),
                            timestamp,
                        ),
                    )
                    ReviewRepository.append_chapter_version(
                        connection,
                        chapter_id=chapter_id,
                        chapter_revision=0,
                        content=content,
                        source=ChapterVersionSource.INITIAL,
                        source_id=request.source_sha256,
                        created_at=timestamp,
                    )
        return self.projects.get_workspace(project_id)

    def export_markdown(self, project_id: str) -> ManuscriptExport:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            rows = connection.execute(
                """
                SELECT v.id AS volume_id, v.title AS volume_title,
                       c.id AS chapter_id, c.title AS chapter_title, c.content
                FROM manuscript_volumes v
                JOIN chapters c ON c.volume_id = v.id
                WHERE v.project_id = ? AND v.deleted_at IS NULL AND c.deleted_at IS NULL
                ORDER BY v.sort_key, v.id, c.sort_key, c.id
                """,
                (project_id,),
            ).fetchall()
        if not rows:
            raise ValueError("empty_manuscript")
        lines = [f"# {project['title']}", ""]
        current_volume_id: str | None = None
        volume_count = 0
        for row in rows:
            if row["volume_id"] != current_volume_id:
                current_volume_id = str(row["volume_id"])
                volume_count += 1
                lines.extend((f"## {row['volume_title']}", ""))
            lines.extend((f"### {row['chapter_title']}", "", str(row["content"]), ""))
        content = "\n".join(lines).rstrip() + "\n"
        filename_stem = (
            "".join(
                "_" if character in '\\/:*?"<>|' or ord(character) < 32 else character
                for character in str(project["title"])
            ).strip()
            or "墨舟作品"
        )
        return ManuscriptExport(
            filename=f"{filename_stem}.md",
            content=content,
            content_sha256=sha256(content.encode("utf-8")).hexdigest(),
            volume_count=volume_count,
            chapter_count=len(rows),
        )

    def export_binary(self, project_id: str, format: str) -> ManuscriptBinaryExport:
        if format not in {"docx", "epub"}:
            raise ValueError("unsupported_export_format")
        project, rows = self._export_rows(project_id)
        payload = (
            self._build_docx(str(project["title"]), rows)
            if format == "docx"
            else self._build_epub(str(project["title"]), rows)
        )
        stem = self._filename_stem(str(project["title"]))
        return ManuscriptBinaryExport(
            filename=f"{stem}.{format}",
            payload=payload,
            content_sha256=sha256(payload).hexdigest(),
            volume_count=len({str(row["volume_id"]) for row in rows}),
            chapter_count=len(rows),
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if format == "docx"
                else "application/epub+zip"
            ),
        )

    def _export_rows(self, project_id: str) -> tuple[Row, list[Row]]:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            rows = connection.execute(
                """SELECT v.id volume_id, v.title volume_title,
                c.id chapter_id, c.title chapter_title, c.content FROM manuscript_volumes v
                JOIN chapters c ON c.volume_id=v.id WHERE v.project_id=? AND v.deleted_at IS NULL
                AND c.deleted_at IS NULL ORDER BY v.sort_key, v.id, c.sort_key, c.id""",
                (project_id,),
            ).fetchall()
        if not rows:
            raise ValueError("empty_manuscript")
        return project, list(rows)

    @staticmethod
    def _filename_stem(title: str) -> str:
        return (
            "".join(
                "_" if character in '\\/:*?"<>|' or ord(character) < 32 else character
                for character in title
            ).strip()
            or "墨舟作品"
        )

    @staticmethod
    def _build_docx(title: str, rows: list[Row]) -> bytes:
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ElementTree.register_namespace("w", w)
        document = ElementTree.Element(f"{{{w}}}document")
        body = ElementTree.SubElement(document, f"{{{w}}}body")

        def paragraph(text: str, style: str | None = None) -> None:
            p = ElementTree.SubElement(body, f"{{{w}}}p")
            if style:
                ppr = ElementTree.SubElement(p, f"{{{w}}}pPr")
                ElementTree.SubElement(ppr, f"{{{w}}}pStyle", {f"{{{w}}}val": style})
            run = ElementTree.SubElement(p, f"{{{w}}}r")
            node = ElementTree.SubElement(
                run, f"{{{w}}}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
            )
            node.text = text

        paragraph(title, "Heading1")
        current_volume = None
        for row in rows:
            if row["volume_id"] != current_volume:
                current_volume = row["volume_id"]
                paragraph(str(row["volume_title"]), "Heading2")
            paragraph(str(row["chapter_title"]), "Heading3")
            for line in str(row["content"]).split("\n"):
                paragraph(line)
        ElementTree.SubElement(body, f"{{{w}}}sectPr")
        document_xml = ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)
        content_types = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
        rels = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", rels)
            archive.writestr("word/document.xml", document_xml)
        return output.getvalue()

    @staticmethod
    def _build_epub(title: str, rows: list[Row]) -> bytes:
        container = b"""<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""
        manifest: list[str] = []
        spine: list[str] = []
        pages: list[tuple[str, bytes]] = []
        current_volume = None
        volume_title = ""
        for ordinal, row in enumerate(rows, start=1):
            if row["volume_id"] != current_volume:
                current_volume = row["volume_id"]
                volume_title = str(row["volume_title"])
            item_id = f"chapter-{ordinal}"
            filename = f"chapter-{ordinal}.xhtml"
            html = ElementTree.Element(
                "html", {"xmlns": "http://www.w3.org/1999/xhtml", "lang": "zh-CN"}
            )
            head = ElementTree.SubElement(html, "head")
            ElementTree.SubElement(head, "title").text = str(row["chapter_title"])
            body = ElementTree.SubElement(html, "body")
            ElementTree.SubElement(body, "h2").text = volume_title
            ElementTree.SubElement(body, "h3").text = str(row["chapter_title"])
            ElementTree.SubElement(body, "pre").text = str(row["content"])
            pages.append(
                (filename, ElementTree.tostring(html, encoding="utf-8", xml_declaration=True))
            )
            manifest.append(
                f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="{item_id}"/>')
        package = f"""<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:sha256:{sha256(title.encode()).hexdigest()}</dc:identifier><dc:title>{escape(title)}</dc:title><dc:language>zh-CN</dc:language></metadata><manifest>{"".join(manifest)}</manifest><spine>{"".join(spine)}</spine></package>""".encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                zipfile.ZipInfo("mimetype"),
                b"application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            archive.writestr(
                "META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED
            )
            archive.writestr("EPUB/package.opf", package, compress_type=zipfile.ZIP_DEFLATED)
            for filename, content in pages:
                archive.writestr(f"EPUB/{filename}", content, compress_type=zipfile.ZIP_DEFLATED)
        return output.getvalue()


@dataclass(frozen=True, slots=True)
class ManuscriptBinaryExport:
    filename: str
    payload: bytes
    content_sha256: str
    volume_count: int
    chapter_count: int
    media_type: str
