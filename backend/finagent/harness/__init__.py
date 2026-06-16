"""Long-running harness: checkpoints, interrupts, gates, footprint, compression."""

from finagent.harness.context_manager import CompressedContext, compress_context_stub, should_compress
from finagent.harness.human_gates import GATES, Gate, evaluate_gate
from finagent.harness.orchestrator import Harness, HarnessConfig
from finagent.state.checkpoint import Checkpoint, deserialize_checkpoint, serialize_checkpoint

__all__ = [
    "Harness",
    "HarnessConfig",
    "Checkpoint",
    "serialize_checkpoint",
    "deserialize_checkpoint",
    "CompressedContext",
    "compress_context_stub",
    "should_compress",
    "GATES",
    "Gate",
    "evaluate_gate",
]
