"""CommunityAgent — aggregates Reddit / HN / StockTwits sentiment.

Existing enrichment already pulls the raw feed; this agent's job is to
*interpret* it: spot pump-and-dump signals, score bull/bear ratio,
surface the loudest threads as findings.
"""

from __future__ import annotations

from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext
from finagent.tools.social.viral_verifier import score_text_for_pump_and_dump


class CommunityAgent(BaseSubAgent):
    name = "community"
    display = "Community Pulse"
    priority = 30

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        b = ctx.bundle
        reddit = (getattr(b, "reddit", None) if b else None) or []
        hn = (getattr(b, "hackernews", None) if b else None) or []
        st = getattr(b, "stocktwits", None) if b else None

        if reddit:
            bull = sum(1 for p in reddit if p.sentiment == "bullish")
            bear = sum(1 for p in reddit if p.sentiment == "bearish")
            hype = sum(1 for p in reddit if p.sentiment == "hype")
            top = sorted(reddit, key=lambda p: p.score, reverse=True)[:5]
            ratio_txt = (
                f"bullish={bull} bearish={bear} hype={hype} neutral={len(reddit) - bull - bear - hype}"
            )
            # Pump-and-dump scan across all post titles + selftext
            combined = " ".join((p.title or "") + " " + (p.selftext or "") for p in reddit[:25])
            viral = score_text_for_pump_and_dump(combined[:6000], host="reddit.com")
            conf = "HIGH" if viral.risk_level == "high" else "MEDIUM"
            headline = f"Reddit pulse on {ctx.canonical_label}: {len(reddit)} posts, {ratio_txt}"
            detail = (
                f"Top thread: '{top[0].title}' ({top[0].subreddit}, {top[0].score} score). "
                f"Pump/dump risk: {viral.risk_level} ({viral.score:.2f})."
                if top else f"{len(reddit)} posts gathered; sentiment {ratio_txt}."
            )
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="sentiment",
                    headline=headline,
                    detail=detail,
                    confidence=conf,
                    evidence=[t.url for t in top[:3]],
                    metrics={
                        "post_count": len(reddit),
                        "bullish": bull,
                        "bearish": bear,
                        "hype": hype,
                        "pump_risk_score": viral.score,
                        "pump_risk_level": viral.risk_level,
                    },
                )
            )
            if viral.risk_level == "high":
                out.findings.append(
                    Finding(
                        agent=self.name,
                        kind="risk",
                        headline="Elevated pump/dump signal in retail commentary",
                        detail=(
                            f"Viral verifier flagged community chatter as high risk. "
                            f"Markers: {', '.join(viral.markers[:4]) if viral.markers else 'unspecified'}."
                        ),
                        confidence="MEDIUM",
                        evidence=[t.url for t in top[:3]],
                        metrics={"markers": viral.markers},
                    )
                )

        if hn:
            top_hn = sorted(hn, key=lambda s: s.points, reverse=True)[:3]
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="sentiment",
                    headline=f"Hacker News: {len(hn)} story/ies, top has {top_hn[0].points} points",
                    detail="; ".join(f"'{s.title}' ({s.points} pts)" for s in top_hn),
                    confidence="MEDIUM",
                    evidence=[s.url for s in top_hn],
                    metrics={"story_count": len(hn), "top_points": top_hn[0].points},
                )
            )

        if st:
            ratio = None
            if (st.bullish_count or 0) + (st.bearish_count or 0) > 0:
                ratio = st.bullish_count / max(1, st.bullish_count + st.bearish_count)
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="sentiment",
                    headline=f"StockTwits: {st.message_count} msgs, {ratio * 100:.0f}% bullish" if ratio is not None else f"StockTwits: {st.message_count} msgs",
                    detail=(
                        f"{st.bullish_count} bull / {st.bearish_count} bear declared sentiment "
                        f"across {st.message_count} messages."
                    ),
                    confidence="LOW",
                    evidence=[f"https://stocktwits.com/symbol/{ctx.target}"],
                    metrics={
                        "messages": st.message_count,
                        "bullish": st.bullish_count,
                        "bearish": st.bearish_count,
                        "bull_ratio": ratio,
                    },
                )
            )

        return out
