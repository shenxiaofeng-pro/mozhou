from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection

from app.migrations import v1, v2, v3, v4, v5, v6, v7

MigrationUpgrade = Callable[[Connection, str], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: MigrationUpgrade


MIGRATIONS = (
    Migration(version=1, name="initial_schema", upgrade=v1.upgrade),
    Migration(version=2, name="chapter_brief_and_ai_provenance", upgrade=v2.upgrade),
    Migration(version=3, name="migration_history", upgrade=v3.upgrade),
    Migration(version=4, name="durable_ai_jobs", upgrade=v4.upgrade),
    Migration(version=5, name="reference_job_provenance", upgrade=v5.upgrade),
    Migration(version=6, name="ai_provider_profiles", upgrade=v6.upgrade),
    Migration(version=7, name="ai_task_defaults", upgrade=v7.upgrade),
)

if tuple(migration.version for migration in MIGRATIONS) != tuple(
    range(1, len(MIGRATIONS) + 1)
):
    raise RuntimeError("数据库迁移版本必须从 1 开始连续递增")
