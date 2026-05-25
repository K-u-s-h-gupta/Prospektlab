"""Backward compatibility wrapper for pdf_transformer.

This module re-exports all public symbols from pdf_transformer to maintain
backward compatibility with existing imports.

New code should import directly from pdf_transformer.
"""

from finagent.ingestion.pdf_transformer import (
    DocumentMarkdown,
    DocumentTransformError,
    document_to_markdown,
)

__all__ = [
    "DocumentMarkdown",
    "DocumentTransformError",
    "document_to_markdown",
]
