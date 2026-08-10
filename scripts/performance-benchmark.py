from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "services" / "api"))

from app.database import Database  # noqa: E402
from app.manuscript.serial import SerialService  # noqa: E402
from app.models import CreateProjectRequest, Genre, UpdateChapterRequest  # noqa: E402
from app.reference_lab import segment_reference_text  # noqa: E402
from app.repository import ProjectRepository  # noqa: E402

THRESHOLDS_MS = {
    "project_open_1_chapters": 2_000,
    "project_open_30_chapters": 2_000,
    "project_open_100_chapters": 2_000,
    "chapter_switch_100_chapters": 300,
    "chapter_save_100_chapters": 1_000,
    "workspace_search_300k": 2_000,
    "reference_split_3m": 2_000,
}


def elapsed_ms(operation: object) -> float:
    started_at = perf_counter()
    assert callable(operation)
    operation()
    return round((perf_counter() - started_at) * 1_000, 3)


def seed_project(database: Database, chapter_count: int) -> tuple[ProjectRepository, str, str]:
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(
        CreateProjectRequest(
            title=f"规模基准-{chapter_count}",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
            chapter_target_words=3000,
            safety_buffer_chapters=3,
        )
    )
    project_id = workspace.project.id
    first_chapter = workspace.chapters[0]
    volume_id = workspace.manuscript_volumes[0].id
    timestamp = datetime.now(UTC).isoformat()
    body = "南平竹海商路重新开张。" * 150
    with database.connect() as connection:
        connection.execute(
            "UPDATE chapters SET content = ? WHERE id = ?",
            (body, first_chapter.id),
        )
        connection.executemany(
            """
            INSERT INTO chapters (
                id, project_id, volume_id, volume_number, chapter_number,
                sort_key, title, content, status, revision, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'drafted', 0, ?)
            """,
            [
                (
                    str(uuid4()),
                    project_id,
                    volume_id,
                    chapter_number,
                    chapter_number * 1024,
                    f"第{chapter_number}章 商路",
                    ("规模检索锚点。" if chapter_number == chapter_count else "") + body,
                    timestamp,
                )
                for chapter_number in range(2, chapter_count + 1)
            ],
        )
    last_chapter_id = repository.get_workspace_summary(project_id).chapters[-1].id
    return repository, project_id, last_chapter_id


def run() -> dict[str, object]:
    measurements: dict[str, float] = {}
    with TemporaryDirectory(prefix="mozhou-benchmark-") as temporary_directory:
        root = Path(temporary_directory)
        for chapter_count in (1, 30, 100):
            database = Database(root / f"scale-{chapter_count}.db")
            repository, project_id, last_chapter_id = seed_project(database, chapter_count)
            measurements[f"project_open_{chapter_count}_chapters"] = elapsed_ms(
                lambda: repository.get_workspace_summary(project_id)
            )
            if chapter_count == 100:
                measurements["chapter_switch_100_chapters"] = elapsed_ms(
                    lambda: repository.get_chapter(last_chapter_id)
                )
                chapter = repository.get_chapter(last_chapter_id)
                measurements["chapter_save_100_chapters"] = elapsed_ms(
                    lambda: repository.update_chapter(
                        last_chapter_id,
                        UpdateChapterRequest(
                            content=chapter.content + "保存确认。",
                            expected_revision=chapter.revision,
                        ),
                    )
                )
                serial = SerialService(database)
                measurements["workspace_search_300k"] = elapsed_ms(
                    lambda: serial.search(project_id, "规模检索锚点", limit=20)
                )

        reference_text = "第1章 起点\n" + ("现实世界资料与冲突因果。" * 250_000)
        measurements["reference_split_3m"] = elapsed_ms(
            lambda: segment_reference_text(reference_text, 500_000)
        )

    failures = {
        name: {"actual_ms": measurements[name], "threshold_ms": threshold}
        for name, threshold in THRESHOLDS_MS.items()
        if measurements[name] > threshold
    }
    return {
        "benchmark_version": "scale-v1",
        "measurements_ms": measurements,
        "thresholds_ms": THRESHOLDS_MS,
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)
