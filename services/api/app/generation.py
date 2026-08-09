from app.fake_model import generate_demo_draft
from app.models import GenerationRun, GenerationState
from app.repository import ProjectRepository


class GenerationService:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    def start(self, chapter_id: str, expected_revision: int) -> GenerationRun:
        run = self.repository.create_generation_run(chapter_id, expected_revision)
        return self.resume(run.id)

    def resume(self, run_id: str) -> GenerationRun:
        run = self.repository.get_generation_run(run_id)
        if run.provider != "demo":
            return run
        if run.state == GenerationState.CONTEXT_READY:
            run = self.repository.transition_generation(
                run_id,
                GenerationState.CONTEXT_READY,
                GenerationState.GENERATING,
            )
        if run.state == GenerationState.GENERATING:
            candidate = generate_demo_draft(self.repository.get_generation_context(run_id))
            run = self.repository.transition_generation(
                run_id,
                GenerationState.GENERATING,
                GenerationState.DRAFTED,
                candidate_content=candidate,
            )
        return run
