import ast
import inspect
from pathlib import Path

from pydantic import BaseModel

from app import beta
from app import models as shared_models
from app.canon_reconciliation import models as canon_models
from app.chapter_production import models as production_models
from app.context import models as context_models
from app.context import plan_models
from app.pattern_adaptation import models as adaptation_models
from app.writing_patterns import models as pattern_models

FEATURE_MODULES = (
    beta,
    canon_models,
    production_models,
    context_models,
    plan_models,
    adaptation_models,
    pattern_models,
)

STRICT_SHARED_MODELS: tuple[type[BaseModel], ...] = (
    shared_models.TopicDecisionContent,
    shared_models.CreateProjectRequest,
    shared_models.UpdateTopicDecisionRequest,
    shared_models.ConfirmTopicDecisionRequest,
    shared_models.TopicDecisionCandidateRequest,
    shared_models.TopicDecisionRegenerationRequest,
    shared_models.SelectTopicDecisionCandidateRequest,
    shared_models.RejectTopicDecisionCandidateRequest,
    shared_models.BookBlueprintContent,
    shared_models.DirectorStartupRequest,
    shared_models.SelectDirectorCandidateRequest,
    shared_models.UpdateBookBlueprintRequest,
    shared_models.DirectorRegenerationImpactRequest,
    shared_models.DirectorFieldRegenerationRequest,
    shared_models.ApplyDirectorProposalRequest,
    shared_models.VolumePlanContent,
    shared_models.RollingChapterPlanContent,
    shared_models.DirectorExpansionRequest,
    shared_models.UpdateVolumePlanRequest,
    shared_models.UpdateRollingChapterPlanRequest,
    shared_models.DirectorChapterPipelineRequest,
    shared_models.CreateRecoveryPointRequest,
    shared_models.ManuscriptImportChapter,
    shared_models.ManuscriptImportVolume,
    shared_models.ConfirmManuscriptImportRequest,
    shared_models.CraftPatternAnalysisPreviewRequest,
    shared_models.SubmitCraftPatternAnalysisRequest,
    shared_models.CraftPatternFusionPreviewRequest,
    shared_models.SubmitCraftPatternFusionRequest,
    shared_models.UpdateCraftPatternLifecycleRequest,
)


def test_m28_m35_feature_request_models_reject_unknown_json_fields() -> None:
    checked: list[str] = []
    for module in FEATURE_MODULES:
        for name, model in inspect.getmembers(module, inspect.isclass):
            if (
                not name.endswith("Request")
                or not issubclass(model, BaseModel)
                or model.__module__ != module.__name__
            ):
                continue
            assert model.model_config.get("extra") == "forbid", (
                f"{module.__name__}.{name} must fail closed on unknown JSON fields"
            )
            checked.append(f"{module.__name__}.{name}")

    for model in STRICT_SHARED_MODELS:
        assert model.model_config.get("extra") == "forbid", (
            f"{model.__module__}.{model.__name__} must fail closed on unknown JSON fields"
        )
        checked.append(f"{model.__module__}.{model.__name__}")

    assert len(checked) >= 65


def _dynamic_sql_calls(path: Path) -> list[tuple[str, str, tuple[str, ...], str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    calls: list[tuple[str, str, tuple[str, ...], str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {
            "execute",
            "executemany",
        }:
            continue
        query = node.args[0]
        if not isinstance(query, (ast.JoinedStr, ast.BinOp)):
            continue
        owner: ast.AST | None = node
        while owner is not None and not isinstance(
            owner, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            owner = parent.get(owner)
        interpolations = tuple(
            ast.unparse(item.value)
            for item in ast.walk(query)
            if isinstance(item, ast.FormattedValue)
        )
        calls.append(
            (
                str(path),
                owner.name if owner is not None else "<module>",
                interpolations,
                ast.unparse(query),
            )
        )
    return calls


def test_m28_m35_sql_uses_parameters_or_reviewed_identifier_whitelists() -> None:
    app_root = Path(__file__).parents[1] / "app"
    paths = [
        app_root / "topic_decisions.py",
        app_root / "craft_patterns.py",
        app_root / "author_navigation.py",
        app_root / "beta.py",
        *(app_root / "writing_patterns").glob("*.py"),
        *(app_root / "pattern_adaptation").glob("*.py"),
        *(app_root / "context").glob("*.py"),
        *(app_root / "chapter_production").glob("*.py"),
        *(app_root / "canon_reconciliation").glob("*.py"),
    ]
    dynamic_calls = [call for path in paths for call in _dynamic_sql_calls(path)]
    reviewed_interpolations = {
        "craft_patterns.py": {
            "self._summary_columns()",
            "join",
            "where",
            "placeholders",
            "parent_placeholders",
        },
        "writing_patterns/service.py": {"placeholders"},
        "writing_patterns/repository.py": {
            "where",
            "placeholders",
            "' AND '.join(filters)",
        },
        "context/service.py": {"table"},
        "context/plan_repository.py": {"placeholders"},
        "context/repository.py": {"table", "project_column"},
        "chapter_production/repository.py": {"clause"},
        "canon_reconciliation/repository.py": {"placeholders"},
    }
    assert len(dynamic_calls) == 19
    for path, _owner, interpolations, expression in dynamic_calls:
        relative = Path(path).relative_to(app_root).as_posix()
        if interpolations:
            assert set(interpolations) <= reviewed_interpolations[relative]
        else:
            assert "_CANDIDATE_SELECT" in expression

    context_source = (app_root / "context" / "service.py").read_text(encoding="utf-8")
    assert "if table not in _FEEDBACK_STATE_TABLES" in context_source
    assert "_FEEDBACK_STATE_TABLES = frozenset" in context_source
