"""Long-poll loop: leases jobs from the control plane, dispatches to a handler, reports
back. Runs on the GPU pod — has no direct DB/S3 access, only the WORKER_TOKEN and HTTPS,
per the architecture's "worker authenticates with a worker token" design (see claude.md
§1's Design decisions)."""
import importlib
import os
import time
import traceback

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
WORKER_TOKEN = os.environ["WORKER_TOKEN"]
POLL_INTERVAL_S = float(os.environ.get("WORKER_POLL_INTERVAL_S", "5"))
# Every internal-API call gets a hard timeout — without one, a dropped/stalled connection
# (e.g. the dev-mode SSH tunnel this rides over) hangs the request forever instead of
# raising, since requests has no default. Found live: a mid-request tunnel blip left the
# worker stuck on mark_running() indefinitely with no error, no retry, no progress.
REQUEST_TIMEOUT_S = 30
# Video/4K outputs are much larger than M3's candidate images — generous timeout.
UPLOAD_TIMEOUT_S = 300

JOB_TYPES = ["look_generation", "video_generation", "upscale"]

# Module names, not imported objects — imported lazily per job, on demand. Found live:
# look_generation.py needs torch/diffusers in-process, but video_generation.py/upscale.py
# deliberately DON'T (they subprocess out to LiveAvatar/SeedVR2's own isolated venvs, per
# the module docstrings). Importing all three eagerly at startup would force every worker
# pod to install Qwen's torch/diffusers even if it only ever runs video_generation/upscale.
HANDLER_MODULES = {
    "look_generation": "handlers.look_generation",
    "video_generation": "handlers.video_generation",
    "upscale": "handlers.upscale",
}

_session = requests.Session()
_session.headers["Authorization"] = f"Bearer {WORKER_TOKEN}"


def _internal_url(path: str) -> str:
    return f"{API_BASE_URL}/api/v1/internal{path}"


def lease_next_job() -> dict | None:
    resp = _session.get(
        _internal_url("/jobs/next"),
        params={"types": ",".join(JOB_TYPES)},
        timeout=REQUEST_TIMEOUT_S,
    )
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    return resp.json()


def report_progress(job_id: str, progress: int) -> None:
    resp = _session.patch(
        _internal_url(f"/jobs/{job_id}"),
        json={"progress": progress, "heartbeat": True},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()


def mark_running(job_id: str) -> None:
    resp = _session.patch(
        _internal_url(f"/jobs/{job_id}"),
        json={"status": "running", "heartbeat": True},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()


def complete_job(job_id: str, result: dict) -> None:
    resp = _session.post(
        _internal_url(f"/jobs/{job_id}/complete"),
        json={"result": result},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()


def fail_job(job_id: str, error: str) -> None:
    resp = _session.post(
        _internal_url(f"/jobs/{job_id}/fail"),
        json={"error": error},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()


def upload_output(prefix: str, filename: str, data: bytes, content_type: str) -> str:
    presign = _session.post(
        _internal_url("/uploads/presign"),
        json={"prefix": prefix, "filename": filename, "content_type": content_type},
        timeout=REQUEST_TIMEOUT_S,
    )
    presign.raise_for_status()
    body = presign.json()
    put_resp = requests.put(
        body["upload_url"],
        data=data,
        headers={"Content-Type": content_type},
        timeout=UPLOAD_TIMEOUT_S,
    )
    put_resp.raise_for_status()
    return body["s3_key"]


class JobContext:
    """Passed to handlers so they can report progress / upload outputs without knowing
    the internal API protocol themselves."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def report_progress(self, progress: int) -> None:
        report_progress(self.job_id, progress)

    def upload_output(self, prefix: str, filename: str, data: bytes, content_type: str) -> str:
        return upload_output(prefix, filename, data, content_type)


def run_forever() -> None:
    print(f"Worker starting — API_BASE_URL={API_BASE_URL}, types={JOB_TYPES}", flush=True)
    while True:
        try:
            job = lease_next_job()
        except requests.RequestException as exc:
            print(f"Poll failed: {exc}", flush=True)
            time.sleep(POLL_INTERVAL_S)
            continue

        if job is None:
            time.sleep(POLL_INTERVAL_S)
            continue

        job_id = job["id"]
        job_type = job["type"]
        module_name = HANDLER_MODULES.get(job_type)
        print(f"Leased job {job_id} ({job_type})", flush=True)

        if module_name is None:
            fail_job(job_id, f"No handler registered for job type '{job_type}'")
            continue

        try:
            handler = importlib.import_module(module_name).run
            mark_running(job_id)
            ctx = JobContext(job_id)
            result = handler(job, ctx)
            complete_job(job_id, result)
            print(f"Job {job_id} complete", flush=True)
        except Exception:
            error = traceback.format_exc()[-4000:]  # last ~50 lines, bounded
            print(f"Job {job_id} failed:\n{error}", flush=True)
            try:
                fail_job(job_id, error)
            except requests.RequestException as exc:
                print(f"Also failed to report failure back to control plane: {exc}", flush=True)


if __name__ == "__main__":
    run_forever()
