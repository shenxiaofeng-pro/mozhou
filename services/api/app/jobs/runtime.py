import threading
from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

from app.jobs.models import Job, JobKind, JobState
from app.jobs.repository import JobRepository

JobHandler = Callable[["JobExecutionContext", Job], None]


class JobCancellationRequested(RuntimeError):
    pass


class JobExecutionError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class JobExecutionContext:
    def __init__(
        self,
        repository: JobRepository,
        job_id: str,
        owner: str,
        lease_duration: timedelta,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.owner = owner
        self.lease_duration = lease_duration

    def checkpoint(self) -> Job:
        self.repository.heartbeat(
            self.job_id,
            self.owner,
            lease_duration=self.lease_duration,
        )
        job = self.repository.get_job(self.job_id)
        if job.state == JobState.PAUSE_REQUESTED:
            raise JobCancellationRequested
        if job.state != JobState.RUNNING:
            raise RuntimeError(f"任务租约已失效：{job.state.value}")
        return job


class JobRuntime:
    def __init__(
        self,
        repository: JobRepository,
        handlers: dict[JobKind, JobHandler] | None = None,
        *,
        lease_duration: timedelta = timedelta(minutes=3),
        poll_interval: float = 0.1,
    ) -> None:
        self.repository = repository
        self.handlers = dict(handlers or {})
        self.lease_duration = lease_duration
        self.poll_interval = poll_interval
        self.owner = f"worker-{uuid4()}"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, kind: JobKind, handler: JobHandler) -> None:
        self.handlers[kind] = handler
        self.wake()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.repository.recover_expired()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="mozhou-job-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def run_once(self) -> bool:
        job = self.repository.lease_next(
            self.owner,
            set(self.handlers),
            lease_duration=self.lease_duration,
        )
        if job is None:
            return False
        handler = self.handlers[job.kind]
        context = JobExecutionContext(
            self.repository,
            job.id,
            self.owner,
            self.lease_duration,
        )
        try:
            context.checkpoint()
            handler(context, job)
            current = self.repository.get_job(job.id)
            if current.state == JobState.RUNNING:
                self.repository.transition_job(
                    job.id,
                    JobState.SUCCEEDED,
                    event_type="completed",
                )
            elif current.state == JobState.PAUSE_REQUESTED:
                self.repository.transition_job(
                    job.id,
                    JobState.CANCELLED,
                    event_type="cancelled",
                )
        except JobCancellationRequested:
            current = self.repository.get_job(job.id)
            if current.state == JobState.PAUSE_REQUESTED:
                self.repository.transition_job(
                    job.id,
                    JobState.CANCELLED,
                    event_type="cancelled",
                )
        except Exception as error:  # noqa: BLE001 - worker boundary persists failures
            current = self.repository.get_job(job.id)
            if current.state == JobState.RUNNING:
                error_code = error.code if isinstance(error, JobExecutionError) else type(error).__name__
                error_message = (
                    error.safe_message
                    if isinstance(error, JobExecutionError)
                    else "任务执行失败，可重试并保留已完成结果"
                )
                self.repository.fail_open_attempts(
                    job.id,
                    error_code=error_code,
                    error_message=error_message,
                )
                self.repository.transition_job(
                    job.id,
                    JobState.FAILED,
                    event_type="failed",
                    error_code=error_code,
                    error_message=error_message,
                )
            elif current.state == JobState.PAUSE_REQUESTED:
                self.repository.transition_job(
                    job.id,
                    JobState.CANCELLED,
                    event_type="cancelled",
                )
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.run_once():
                continue
            self._wake.wait(self.poll_interval)
            self._wake.clear()
