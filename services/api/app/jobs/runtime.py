import threading
from collections.abc import Callable
from datetime import timedelta
from time import monotonic
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
        lease_duration: timedelta = timedelta(seconds=15),
        poll_interval: float = 0.1,
        recovery_interval: float | None = None,
    ) -> None:
        lease_seconds = lease_duration.total_seconds()
        if lease_seconds <= 0:
            raise ValueError("lease duration must be positive")
        self.repository = repository
        self.handlers = dict(handlers or {})
        self.lease_duration = lease_duration
        self.poll_interval = poll_interval
        self.heartbeat_interval = max(0.05, min(5.0, lease_seconds / 3))
        self.recovery_interval = (
            recovery_interval
            if recovery_interval is not None
            else max(0.1, min(5.0, lease_seconds / 3))
        )
        if self.recovery_interval <= 0:
            raise ValueError("recovery interval must be positive")
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
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._maintain_lease,
            args=(job.id, heartbeat_stop),
            name=f"mozhou-job-heartbeat-{job.id}",
            daemon=True,
        )
        try:
            context.checkpoint()
            heartbeat_thread.start()
            handler(context, job)
            context.checkpoint()
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
        finally:
            heartbeat_stop.set()
            if heartbeat_thread.is_alive():
                heartbeat_thread.join(self.heartbeat_interval + 0.1)
        return True

    def _maintain_lease(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            try:
                if not self.repository.heartbeat(
                    job_id,
                    self.owner,
                    lease_duration=self.lease_duration,
                ):
                    return
            except Exception:  # noqa: BLE001 - final checkpoint owns failure handling
                return

    def _run(self) -> None:
        next_recovery = monotonic() + self.recovery_interval
        while not self._stop.is_set():
            current_time = monotonic()
            if current_time >= next_recovery:
                self.repository.recover_expired()
                next_recovery = current_time + self.recovery_interval
            if self.run_once():
                continue
            wait_for = min(self.poll_interval, max(0.0, next_recovery - monotonic()))
            self._wake.wait(wait_for)
            self._wake.clear()
