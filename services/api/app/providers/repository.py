import json
from sqlite3 import IntegrityError, Row
from uuid import uuid4

from app.database import Database
from app.providers.models import (
    AiTaskDefault,
    AiTaskType,
    CreateModelProfileRequest,
    ModelProfile,
    UpdateAiTaskDefaultRequest,
    UpdateModelProfileRequest,
)
from app.providers.validation import default_capabilities
from app.repository import now_iso


class ModelProfileNotFoundError(LookupError):
    pass


class DuplicateModelProfileError(ValueError):
    pass


class StaleModelProfileError(ValueError):
    pass


class StaleTaskDefaultError(ValueError):
    pass


class ModelProfileRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_profiles(self) -> list[ModelProfile]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_provider_profiles ORDER BY created_at, id"
            ).fetchall()
        return [self._profile(row) for row in rows]

    def get_profile(self, profile_id: str) -> ModelProfile:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ai_provider_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise ModelProfileNotFoundError(profile_id)
        return self._profile(row)

    def list_task_defaults(self) -> list[AiTaskDefault]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT defaults.*, profiles.name AS profile_name,
                       profiles.provider, profiles.model
                FROM ai_task_defaults AS defaults
                JOIN ai_provider_profiles AS profiles ON profiles.id = defaults.profile_id
                ORDER BY defaults.task_type
                """
            ).fetchall()
        return [self._task_default(row) for row in rows]

    def get_task_default(self, task_type: AiTaskType) -> AiTaskDefault | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT defaults.*, profiles.name AS profile_name,
                       profiles.provider, profiles.model
                FROM ai_task_defaults AS defaults
                JOIN ai_provider_profiles AS profiles ON profiles.id = defaults.profile_id
                WHERE defaults.task_type = ?
                """,
                (task_type.value,),
            ).fetchone()
        return self._task_default(row) if row is not None else None

    def get_task_profile(self, task_type: AiTaskType) -> ModelProfile | None:
        task_default = self.get_task_default(task_type)
        return self.get_profile(task_default.profile_id) if task_default is not None else None

    def set_task_default(
        self,
        task_type: AiTaskType,
        request: UpdateAiTaskDefaultRequest,
    ) -> AiTaskDefault:
        timestamp = now_iso()
        with self.database.connect() as connection:
            profile = connection.execute(
                "SELECT id FROM ai_provider_profiles WHERE id = ?",
                (request.profile_id,),
            ).fetchone()
            if profile is None:
                raise ModelProfileNotFoundError(request.profile_id)
            current = connection.execute(
                "SELECT revision FROM ai_task_defaults WHERE task_type = ?",
                (task_type.value,),
            ).fetchone()
            if current is None:
                if request.expected_revision is not None:
                    raise StaleTaskDefaultError("missing")
                connection.execute(
                    """
                    INSERT INTO ai_task_defaults (task_type, profile_id, revision, updated_at)
                    VALUES (?, ?, 0, ?)
                    """,
                    (task_type.value, request.profile_id, timestamp),
                )
            else:
                if request.expected_revision != current["revision"]:
                    raise StaleTaskDefaultError(str(current["revision"]))
                connection.execute(
                    """
                    UPDATE ai_task_defaults
                    SET profile_id = ?, revision = revision + 1, updated_at = ?
                    WHERE task_type = ?
                    """,
                    (request.profile_id, timestamp, task_type.value),
                )
        task_default = self.get_task_default(task_type)
        if task_default is None:
            raise RuntimeError("任务默认模型保存失败")
        return task_default

    def delete_task_default(self, task_type: AiTaskType, expected_revision: int) -> None:
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT revision FROM ai_task_defaults WHERE task_type = ?",
                (task_type.value,),
            ).fetchone()
            if current is None:
                return
            if expected_revision != current["revision"]:
                raise StaleTaskDefaultError(str(current["revision"]))
            connection.execute(
                "DELETE FROM ai_task_defaults WHERE task_type = ?",
                (task_type.value,),
            )

    def create_profile(self, request: CreateModelProfileRequest) -> ModelProfile:
        profile_id = str(uuid4())
        timestamp = now_iso()
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO ai_provider_profiles (
                        id, name, provider, base_url, model, capabilities_json,
                        input_cost_microusd_per_million,
                        output_cost_microusd_per_million,
                        revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        profile_id,
                        request.name,
                        request.provider.value,
                        request.base_url,
                        request.model,
                        json.dumps(
                            default_capabilities(request.provider),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        request.input_cost_microusd_per_million,
                        request.output_cost_microusd_per_million,
                        timestamp,
                        timestamp,
                    ),
                )
        except IntegrityError as error:
            raise DuplicateModelProfileError(request.name) from error
        return self.get_profile(profile_id)

    def update_profile(
        self,
        profile_id: str,
        request: UpdateModelProfileRequest,
    ) -> ModelProfile:
        timestamp = now_iso()
        try:
            with self.database.connect() as connection:
                result = connection.execute(
                    """
                    UPDATE ai_provider_profiles
                    SET name = ?, provider = ?, base_url = ?, model = ?,
                        capabilities_json = ?,
                        input_cost_microusd_per_million = ?,
                        output_cost_microusd_per_million = ?,
                        revision = revision + 1, updated_at = ?
                    WHERE id = ? AND revision = ?
                    """,
                    (
                        request.name,
                        request.provider.value,
                        request.base_url,
                        request.model,
                        json.dumps(
                            default_capabilities(request.provider),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        request.input_cost_microusd_per_million,
                        request.output_cost_microusd_per_million,
                        timestamp,
                        profile_id,
                        request.expected_revision,
                    ),
                )
                if result.rowcount == 0:
                    current = connection.execute(
                        "SELECT revision FROM ai_provider_profiles WHERE id = ?",
                        (profile_id,),
                    ).fetchone()
                    if current is None:
                        raise ModelProfileNotFoundError(profile_id)
                    raise StaleModelProfileError(str(current["revision"]))
        except IntegrityError as error:
            raise DuplicateModelProfileError(request.name) from error
        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: str, expected_revision: int) -> None:
        with self.database.connect() as connection:
            result = connection.execute(
                "DELETE FROM ai_provider_profiles WHERE id = ? AND revision = ?",
                (profile_id, expected_revision),
            )
            if result.rowcount == 0:
                current = connection.execute(
                    "SELECT revision FROM ai_provider_profiles WHERE id = ?",
                    (profile_id,),
                ).fetchone()
                if current is None:
                    raise ModelProfileNotFoundError(profile_id)
                raise StaleModelProfileError(str(current["revision"]))

    @staticmethod
    def _profile(row: Row) -> ModelProfile:
        return ModelProfile.model_validate({
            **dict(row),
            "capabilities": json.loads(row["capabilities_json"]),
        })

    @staticmethod
    def _task_default(row: Row) -> AiTaskDefault:
        return AiTaskDefault.model_validate(dict(row))
