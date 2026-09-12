from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection

from app.migrations import (
    v1,
    v2,
    v3,
    v4,
    v5,
    v6,
    v7,
    v8,
    v9,
    v10,
    v11,
    v12,
    v13,
    v14,
    v15,
    v16,
    v17,
    v18,
    v19,
    v20,
    v21,
    v22,
    v23,
    v24,
    v25,
    v26,
    v27,
    v28,
    v29,
    v30,
)

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
    Migration(version=8, name="context_packets", upgrade=v8.upgrade),
    Migration(version=9, name="global_reference_library", upgrade=v9.upgrade),
    Migration(version=10, name="safe_reference_imports", upgrade=v10.upgrade),
    Migration(version=11, name="global_reality_sources", upgrade=v11.upgrade),
    Migration(version=12, name="versioned_originality_blueprints", upgrade=v12.upgrade),
    Migration(version=13, name="book_director_planning", upgrade=v13.upgrade),
    Migration(version=14, name="review_versions_and_change_sets", upgrade=v14.upgrade),
    Migration(
        version=15,
        name="manuscript_hierarchy_and_serial_goals",
        upgrade=v15.upgrade,
    ),
    Migration(version=16, name="closed_beta_evaluation", upgrade=v16.upgrade),
    Migration(version=17, name="narrative_sandbox", upgrade=v17.upgrade),
    Migration(
        version=18,
        name="scene_plot_graph_originality",
        upgrade=v18.upgrade,
    ),
    Migration(version=19, name="ai_narrative_sandbox", upgrade=v19.upgrade),
    Migration(version=20, name="research_agent", upgrade=v20.upgrade),
    Migration(
        version=21,
        name="document_formats_and_author_productivity",
        upgrade=v21.upgrade,
    ),
    Migration(version=22, name="ai_comic_drama_workbench", upgrade=v22.upgrade),
    Migration(
        version=23,
        name="reference_application_lifecycle",
        upgrade=v23.upgrade,
    ),
    Migration(version=24, name="topic_decisions", upgrade=v24.upgrade),
    Migration(version=25, name="craft_pattern_v2", upgrade=v25.upgrade),
    Migration(version=26, name="writing_pattern_recipes", upgrade=v26.upgrade),
    Migration(
        version=27,
        name="pattern_adaptation_originality_gate",
        upgrade=v27.upgrade,
    ),
    Migration(
        version=28,
        name="pattern_adaptation_job_routing",
        upgrade=v28.upgrade,
    ),
    Migration(
        version=29,
        name="unified_creative_context_and_plan_rebase",
        upgrade=v29.upgrade,
    ),
    Migration(
        version=30,
        name="chapter_production_workbench",
        upgrade=v30.upgrade,
    ),
)

if tuple(migration.version for migration in MIGRATIONS) != tuple(
    range(1, len(MIGRATIONS) + 1)
):
    raise RuntimeError("数据库迁移版本必须从 1 开始连续递增")
