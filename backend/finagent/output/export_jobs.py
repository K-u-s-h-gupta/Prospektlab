"""Async export job registry for document generation.

Manages lifecycle of PDF/DOCX/XLSX generation jobs. Jobs run in a thread
executor (WeasyPrint/Chromium are synchronous) and results are written
to .finagent/exports/.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from finagent.output.contracts import AnswerArtifact
from finagent.output.report_exporter import export_docx, export_pdf, export_xlsx
from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.export_jobs")

_EXPORTS_DIR = finagent_data_path("exports")
_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

_TTL_SECONDS = 86400  # 24 hours

ExportFormat = Literal["pdf", "docx", "xlsx"]


@dataclass
class ExportJob:
    job_id: str
    session_id: str
    format: ExportFormat
    status: str = "queued"  # queued | running | done | error
    path: Path | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None


_JOBS: dict[str, ExportJob] = {}


def get_job(job_id: str) -> ExportJob | None:
    return _JOBS.get(job_id)


def list_jobs(session_id: str) -> list[ExportJob]:
    return [j for j in _JOBS.values() if j.session_id == session_id]


async def start_export(
    session_id: str,
    artifact: AnswerArtifact,
    fmt: ExportFormat,
    style: str = "sell_side",
) -> ExportJob:
    """Queue an export job and return immediately."""
    job_id = uuid.uuid4().hex[:12]
    out_dir = _EXPORTS_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = fmt
    job = ExportJob(
        job_id=job_id,
        session_id=session_id,
        format=fmt,
        path=out_dir / f"{job_id}.{ext}",
    )
    _JOBS[job_id] = job

    asyncio.create_task(_run_export(job, artifact, style))
    return job


async def _run_export(job: ExportJob, artifact: AnswerArtifact, style: str) -> None:
    job.status = "running"
    try:
        if job.format == "pdf":
            data = await export_pdf(artifact, style=style)
        elif job.format == "docx":
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, export_docx, artifact, style)
        elif job.format == "xlsx":
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, export_xlsx, artifact)
        else:
            raise ValueError(f"Unsupported format: {job.format}")

        job.path.write_bytes(data)
        job.status = "done"
        job.completed_at = time.time()
        logger.info("Export job %s completed: %s (%d bytes)", job.job_id, job.path, len(data))

    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.completed_at = time.time()
        logger.exception("Export job %s failed", job.job_id)


def cleanup_expired() -> int:
    """Remove expired export files. Call on gateway startup."""
    removed = 0
    now = time.time()
    expired_ids = []
    for job_id, job in _JOBS.items():
        if now - job.created_at > _TTL_SECONDS:
            if job.path and job.path.exists():
                try:
                    job.path.unlink()
                    removed += 1
                except OSError:
                    pass
            expired_ids.append(job_id)
    for jid in expired_ids:
        del _JOBS[jid]
    return removed
