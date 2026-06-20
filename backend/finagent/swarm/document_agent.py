"""Document Agent: produces all research deliverables in one pass.

The Document Agent is triggered after a deep swarm run when the user shows
export intent (either in the prompt or via the post-session export button). It
creates PDF, DOCX, XLSX, and PPTX versions of the AnswerArtifact and stores
them in the per-session export directory so the frontend can offer a one-click
download gallery.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from finagent.output.contracts import AnswerArtifact
from finagent.output.export_jobs import ExportFormat
from finagent.output.pptx_generator import generate_pptx
from finagent.output.report_exporter import export_docx, export_pdf, export_xlsx
from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.swarm.document_agent")

_EXPORT_FORMATS: list[ExportFormat] = ["pdf", "docx", "xlsx", "pptx"]


def _doc_agent_pdf_enabled() -> bool:
    """Whether the Document Agent should attempt PDF generation.

    PDF export uses a browser subprocess (Patchright/Playwright). In some
    Windows-sandboxed environments this raises WinError 5 when creating pipes.
    Keep the package generation resilient by skipping PDF there unless an
    operator explicitly enables it.
    """
    raw = os.environ.get("FINAGENT_DOC_AGENT_ENABLE_PDF")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.name != "nt"


class DocumentAgent:
    """Generate the full research-document package from an AnswerArtifact."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.out_dir = finagent_data_path("exports") / session_id
        self.out_dir.mkdir(parents=True, exist_ok=True)

    async def generate_all(self, artifact: AnswerArtifact) -> dict[str, Any]:
        """Generate PDF, DOCX, XLSX, and PPTX. Returns a dict of paths/errors."""
        results: dict[str, Any] = {}

        async def _one(fmt: ExportFormat) -> tuple[str, Path | None, str | None]:
            try:
                path = await self._generate_format(artifact, fmt)
                return fmt, path, None
            except Exception as exc:
                logger.warning("[DOCUMENT_AGENT] %s export failed for %s: %s", fmt, self.session_id, exc)
                return fmt, None, str(exc)

        tasks = [_one(fmt) for fmt in _EXPORT_FORMATS]
        for fmt, path, error in await asyncio.gather(*tasks):
            results[fmt] = {"path": str(path) if path else None, "ok": path is not None, "error": error}

        return results

    async def _generate_format(self, artifact: AnswerArtifact, fmt: ExportFormat) -> Path:
        if fmt == "pdf":
            if not _doc_agent_pdf_enabled():
                raise RuntimeError("PDF export is disabled for Document Agent in this environment.")
            data = await export_pdf(artifact, style="sell_side")
            path = self.out_dir / f"report.{fmt}"
            path.write_bytes(data)
            return path
        if fmt == "docx":
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, export_docx, artifact, "sell_side")
            path = self.out_dir / f"report.{fmt}"
            path.write_bytes(data)
            return path
        if fmt == "xlsx":
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, export_xlsx, artifact)
            path = self.out_dir / f"report.{fmt}"
            path.write_bytes(data)
            return path
        if fmt == "pptx":
            loop = asyncio.get_running_loop()
            path = self.out_dir / f"report.{fmt}"
            await loop.run_in_executor(None, generate_pptx, artifact, path)
            return path
        raise ValueError(f"Unsupported format: {fmt}")
