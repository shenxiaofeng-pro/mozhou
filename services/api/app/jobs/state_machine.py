from app.jobs.models import JobState

LEGAL_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset({
        JobState.PAUSE_REQUESTED,
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.INTERRUPTED,
    }),
    JobState.PAUSE_REQUESTED: frozenset({
        JobState.CANCELLED,
        JobState.RUNNING,
        JobState.INTERRUPTED,
    }),
    JobState.CANCELLED: frozenset({JobState.QUEUED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.INTERRUPTED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
}


class InvalidJobTransitionError(ValueError):
    def __init__(self, current: JobState, target: JobState) -> None:
        super().__init__(f"illegal job transition: {current.value} -> {target.value}")
        self.current = current
        self.target = target


def require_job_transition(current: JobState, target: JobState) -> None:
    if target not in LEGAL_JOB_TRANSITIONS[current]:
        raise InvalidJobTransitionError(current, target)
