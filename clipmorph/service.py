"""Shared job service used by the CLI and local web API."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable

from clipmorph.job import JobManifest


class CancellationToken:
    """Cooperative cancellation signal passed to a running job."""

    def __init__(self):
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


class JobService:
    """Persist job lifecycle state while executing bounded background work."""

    def __init__(self, data_dir: str | Path, max_workers: int = 1):
        self.data_dir = Path(data_dir)
        self.jobs_dir = self.data_dir / "jobs"
        self.executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
        self._lock = Lock()
        self._tokens: dict[str, CancellationToken] = {}
        self._futures: dict[str, Future] = {}

    def create_job(self, source_path: str, configuration: dict[str, Any],
                   runner: Callable[[JobManifest, CancellationToken], None] | None = None
                   ) -> JobManifest:
        manifest = JobManifest.create(source_path, configuration, self.jobs_dir)
        if runner is not None:
            manifest.set_status("queued", self.jobs_dir)
            token = CancellationToken()
            with self._lock:
                self._tokens[manifest.job_id] = token
            future = self.executor.submit(self._run, manifest.job_id, runner, token)
            with self._lock:
                self._futures[manifest.job_id] = future
        return manifest

    def _run(self, job_id: str, runner: Callable,
             token: CancellationToken) -> None:
        manifest = JobManifest.load(job_id, self.jobs_dir)
        if token.is_cancelled:
            manifest.set_status("cancelled", self.jobs_dir)
            return
        manifest.set_status("running", self.jobs_dir)
        try:
            runner(manifest, token)
            if token.is_cancelled:
                manifest.set_status("cancelled", self.jobs_dir)
            else:
                manifest.set_status("completed", self.jobs_dir)
        except Exception as error:
            manifest.warnings.append(str(error))
            manifest.set_status("failed", self.jobs_dir)

    def get_job(self, job_id: str) -> JobManifest:
        return JobManifest.load(job_id, self.jobs_dir)

    def list_jobs(self) -> list[JobManifest]:
        if not self.jobs_dir.exists():
            return []
        jobs = []
        for path in self.jobs_dir.glob("*/manifest.json"):
            jobs.append(JobManifest.load(path.parent.name, self.jobs_dir))
        return sorted(jobs, key=lambda item: item.updated_at, reverse=True)

    def cancel_job(self, job_id: str) -> JobManifest:
        manifest = self.get_job(job_id)
        with self._lock:
            token = self._tokens.get(job_id)
        if token is not None:
            token.cancel()
        if manifest.status in {"created", "queued"}:
            manifest.set_status("cancelled", self.jobs_dir)
        return self.get_job(job_id)

    def resume_job(self, job_id: str, runner: Callable) -> JobManifest:
        manifest = self.get_job(job_id)
        token = CancellationToken()
        manifest.set_status("queued", self.jobs_dir)
        with self._lock:
            self._tokens[job_id] = token
            self._futures[job_id] = self.executor.submit(
                self._run, job_id, runner, token)
        return manifest

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
