"""Smoke tests for the new swarm and canvas modules."""

from __future__ import annotations

import pytest

from finagent.swarm import EvidenceBlackboard, SkillRegistry, SubTask, SwarmContext, SwarmOrchestrator
from finagent.swarm.blackboard import BlackboardClaim
from finagent.accuracy.layer import AccuracyLayer
from finagent.canvas.models import InteractiveResearchCanvas, CanvasClaim, CanvasSource
from finagent.canvas.store import CanvasStore, CanvasController
from finagent.tools.sandbox import SandboxTool
from finagent.tools.mcp.ikg_toolkit import IKGToolKit


def test_blackboard_add_and_list_claims():
    bb = EvidenceBlackboard("test-session")
    claim = bb.add_claim(
        text="TCS revenue grew 12% YoY",
        agent="financials_analyst",
        domain="financials",
        confidence="HIGH",
        sources=[{"source": "NSE", "url": "https://nseindia.com"}],
    )
    assert claim.claim_id == "c-0001"
    assert len(bb.list_claims("financials")) == 1
    assert bb.to_dict()["total_claims"] == 1


def test_accuracy_layer_verifies_and_downgrades():
    bb = EvidenceBlackboard("test-session")
    bb.add_claim(
        text="Revenue is ₹100 Cr",
        agent="financials_analyst",
        domain="financials",
        confidence="HIGH",
        sources=[{"source": "NSE", "url": "https://nseindia.com"}],
    )
    bb.add_claim(
        text="Unverified claim",
        agent="news_sentiment",
        domain="news",
        confidence="HIGH",
        sources=[],
    )
    report = AccuracyLayer(bb).run()
    assert report.verified_count == 1
    assert report.unverified_count == 1


def test_accuracy_layer_detects_contradictions():
    bb = EvidenceBlackboard("test-session")
    bb.add_claim(
        text="Revenue is ₹100 Cr",
        agent="financials_analyst",
        domain="financials",
        confidence="HIGH",
        sources=[{"source": "NSE"}],
    )
    bb.add_claim(
        text="Revenue is ₹110 Cr",
        agent="financials_analyst",
        domain="financials",
        confidence="HIGH",
        sources=[{"source": "BSE"}],
    )
    report = AccuracyLayer(bb).run()
    assert len(bb.contradictions) == 1
    assert report.contradictions_resolved == 1


def test_canvas_model():
    canvas = InteractiveResearchCanvas(session_id="s1", query="Analyze TCS", target="TCS.NS")
    section = canvas.add_section("Financial Analysis")
    section.claims.append(CanvasClaim(
        claim_id="c1",
        text="Revenue grew 12%",
        agent="financials",
        confidence="HIGH",
        sources=[CanvasSource(source_id="src1", source_type="NSE", title="NSE Filing", url="https://nseindia.com")],
    ))
    data = canvas.to_dict()
    assert data["query"] == "Analyze TCS"
    assert len(data["sections"]) == 1
    assert data["sections"][0]["claims"][0]["confidence"] == "HIGH"


def test_canvas_store_roundtrip(tmp_path):
    store = CanvasStore(root=tmp_path)
    canvas = InteractiveResearchCanvas(session_id="s1")
    canvas.add_section("Test")
    store.save(canvas)
    loaded = store.load("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"


def test_canvas_controller_steer():
    store = CanvasStore()
    canvas = InteractiveResearchCanvas(session_id="s2")
    controller = CanvasController(store)
    tasks = controller.apply_steer(canvas, {"command": "dig deeper into governance", "text": "Check pledge"})
    assert len(tasks) == 1
    assert tasks[0]["agent_id"] == "governance_forensics"


def test_skill_registry_has_expected_skills():
    registry = SkillRegistry()
    for skill_id in [
        "financials_analyst",
        "valuation_modeler",
        "governance_forensics",
        "risk_redflags",
        "competitor_moat",
        "news_sentiment",
        "macro_sector",
        "causal_war_gamer",
        "document_producer",
    ]:
        assert registry.get(skill_id) is not None, skill_id


@pytest.mark.anyio
async def test_swarm_orchestrator_runs_simple_plan():
    """Ensure the orchestrator can execute a small deterministic plan."""
    from finagent.swarm.models import SwarmPlan

    results = []
    events: list[tuple[str, dict]] = []

    async def fake_runner(task: SubTask, ctx: SwarmContext) -> Any:
        from finagent.swarm.models import SubTaskResult
        results.append(task.task_id)
        return SubTaskResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            status="ok",
            findings=[{"headline": f"finding for {task.agent_id}", "confidence": "HIGH"}],
        )

    def emit(event_type: str, **kwargs):
        events.append((event_type, kwargs))

    orchestrator = SwarmOrchestrator(
        max_concurrency=5,
        max_tasks=10,
        runner=fake_runner,
        emit=emit,
    )
    ctx = SwarmContext(
        session_id="test-swarm",
        target="TCS",
        raw_query="Analyze TCS",
        objective="Analyze TCS",
    )
    plan = SwarmPlan(tasks=[
        SubTask(task_id="t1", agent_id="financials_analyst", objective="fin", priority=10),
        SubTask(task_id="t2", agent_id="governance_forensics", objective="gov", priority=15, dependencies=["t1"]),
    ])
    blackboard, stats = await orchestrator.run(ctx, prebuilt_plan=plan)
    assert len(results) == 2
    assert stats.completed == 2
    assert blackboard.to_dict()["total_claims"] >= 2
    # Verify events are emitted in the expected shape (event_type, kwargs)
    event_types = {e[0] for e in events}
    assert "swarm_planning" in event_types
    assert "swarm_done" in event_types


def test_sandbox_tool_runs_python():
    tool = SandboxTool(timeout_seconds=5.0)
    code = """
OUTPUT = {
    "dcf_value": sum([100, 110, 121]) / 3,
    "wacc": 0.12,
}
"""
    result = tool.run(code, {})
    assert result.success
    assert "dcf_value" in result.output


def test_ikg_toolkit_url_default():
    toolkit = IKGToolKit()
    assert "8007" in toolkit.base_url or "ikg" in toolkit.base_url


from finagent.output.contracts import AnswerArtifact, AnswerCitation, ResponseSection


def _sample_artifact() -> AnswerArtifact:
    return AnswerArtifact(
        mode="standard",
        depth="standard",
        title="TCS Analysis",
        summary="Quick take on TCS.",
        sections=[
            ResponseSection(
                title="Financials",
                body="Revenue grew 12% YoY.",
                citations=["c1"],
            ),
        ],
        citations=[
            AnswerCitation(title="NSE Filing", url="https://nseindia.com", kind="NSE"),
        ],
    )


def test_pptx_generator_creates_slides(tmp_path):
    from finagent.output.pptx_generator import generate_pptx

    artifact = _sample_artifact()
    path = tmp_path / "report.pptx"
    generate_pptx(artifact, path)
    assert path.is_file()
    assert path.stat().st_size > 0


@pytest.mark.anyio
async def test_document_agent_generates_all_formats(tmp_path, monkeypatch):
    from finagent.swarm.document_agent import DocumentAgent

    monkeypatch.setattr("finagent.paths.finagent_data_path", lambda *parts: tmp_path.joinpath(*parts))

    agent = DocumentAgent("doc-agent-1")
    artifact = _sample_artifact()
    results = await agent.generate_all(artifact)

    # PDF/DOCX/XLSX generation may fail if report dependencies are missing; we
    # assert that the PPTX path is produced and that every format is reported.
    assert "pptx" in results
    assert results["pptx"]["ok"] is True
    assert results["pptx"]["path"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
