"""
ProspektLab Flash Content Engine — v2
Isolated content pipeline that orchestrates the existing 8-phase research
engine + IKG to generate highest-accuracy financial articles.

ISOLATION GUARANTEE: This module only CALLS run_research_session() and
IKGService methods as read-only consumers. It NEVER modifies
_DEEP_PASS_OBJECTIVES, run_research_session(), or any existing /research/*
routes. All changes are purely additive.

Content types:
  earnings — quarterly/annual results analysis
  sebi     — enforcement orders, regulatory updates
  trend    — sector / macro / thematic trends
  company  — company deep-dive profile
  manual   — operator-specified free topic

Modes:
  flash — 2 research passes + 1 synthesis  (~60–120 s)
  deep  — 7 research passes + 1 synthesis  (~5–8 min, optimised fork)
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

# ── v1 helpers (imported, never duplicated) ───────────────────────────────────
from finagent.content_automation import (
    ContentArticlePackage,
    ContentArticleSection,
    ContentArticleFaq,
    ContentAutomationRequest,
    ContentAutomationResult,
    _article_dir,
    _public_article_dir,
    _public_article_dirs,
    _safe_route_base,
    _find_cover_asset_name,
    _write_bytes,
    _write_text,
    _upsert_sitemap,
    _generate_cover_for_article,
    _event_fingerprint,
    _load_event_state,
    _save_event_state,
    refresh_public_research_hub,
    render_article_html,
    slugify,
    _SITE_URL,
)
from finagent.content.editorial import (
    contains_internal_language,
    event_is_low_value,
    run_editorial_revision_loop,
    sanitize_article_package,
    sanitize_public_text,
)
from finagent.output.compliance import is_ra_licensed, CHAT_DISCLAIMER
from finagent.output.fact_check import extract_numeric_claims, triangulate_claims
from finagent.seo.google_search_console import submit_sitemap
from finagent.events import BUS
from finagent.run_agent import AgentLoopConfig, run_research_session
from finagent.runtime_provider import resolve_openai_config

logger = logging.getLogger("finagent.content.flash_engine")


_HUB_EDITORIAL_CSS = """
/* ── ProspektLab Research Hub — dark-blue editorial theme ── */
  :root {
    color-scheme: dark;
    --paper:   #03060d;
    --paper-2: rgba(8,16,32,0.7);
    --paper-3: #0a1628;
    --card:    #0d1f3c;
    --ink:     #EAE3D6;
    --ink-2:   #A8B4C8;
    --ink-3:   #5F7088;
    --muted:   #5F7088;
    --ink-on-dark: #EAE3D6;
    --line:        rgba(148,163,184,0.10);
    --line-2:      rgba(147,197,253,0.18);
    --line-strong: rgba(147,197,253,0.30);
    --accent:      #60A5FA;
    --accent-deep: #3B82F6;
    --accent-soft: rgba(96,165,250,0.12);
    --up:   #34D399;
    --down: #FB7185;
    --dark:   #060e1e;
    --dark-2: #0d1928;
    --bg-elevated: rgba(10,22,44,0.78);
    --serif: "Newsreader", Georgia, "Times New Roman", serif;
    --mono:  "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
    --gap: clamp(16px, 2.2vw, 28px);
    --pad-x: clamp(20px, 5vw, 80px);
    --maxw: 1320px;
    --radius: 14px;
    --radius-lg: 22px;
    --shadow-sm: 0 1px 0 rgba(0,0,0,0.2), 0 1px 4px rgba(0,0,0,0.3);
    --shadow:    0 2px 8px rgba(0,0,0,0.4), 0 20px 50px -16px rgba(0,0,0,0.6);
    --shadow-lg: 0 30px 70px -30px rgba(0,0,0,0.7);
    --ease: cubic-bezier(0.22, 0.61, 0.36, 1);
  }
  *, *::before, *::after { box-sizing: border-box; }
  * { margin: 0; }
  html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
  body {
    font-family: var(--serif); background: var(--paper); color: var(--ink);
    line-height: 1.6; font-size: 18px; -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility; overflow-x: hidden;
    background-image:
      radial-gradient(ellipse 700px 450px at 10% 5%, rgba(37,99,235,0.12) 0%, transparent 60%),
      radial-gradient(ellipse 560px 380px at 88% 12%, rgba(96,165,250,0.08) 0%, transparent 60%);
  }
  body::before {
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 1;
    opacity: 0.35;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.08'/%3E%3C/svg%3E");
    mix-blend-mode: overlay;
  }
  img, svg, canvas { display: block; max-width: 100%; }
  a { color: inherit; text-decoration: none; }
  button { font: inherit; color: inherit; cursor: pointer; border: none; background: none; }
  input, textarea { font: inherit; }
  ::selection { background: var(--accent); color: #03060d; }
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(148,163,184,0.15); border-radius: 10px; }

  .wrap { width: 100%; max-width: var(--maxw); margin-inline: auto; padding-inline: var(--pad-x); }
  .section { position: relative; z-index: 2; padding: clamp(32px,5vw,60px) 0; }
  .divider { height: 1px; background: var(--line); border: 0; }

  /* ── Typography ── */
  .eyebrow {
    font-family: var(--mono); font-size: 0.7rem; font-weight: 500;
    letter-spacing: 0.2em; text-transform: uppercase; color: var(--ink-3);
    display: inline-flex; align-items: center; gap: 0.6em;
  }
  .eyebrow .dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .display {
    font-family: var(--serif); font-weight: 500;
    font-size: clamp(2.8rem, 6.4vw, 6rem);
    line-height: 0.97; letter-spacing: -0.025em; font-optical-sizing: auto;
  }
  .display .it { font-style: italic; font-weight: 460; color: var(--accent); }
  h1,h2,h3,h4 { font-family: var(--serif); font-weight: 560; letter-spacing: -0.018em; line-height: 1.05; }
  .h2 { font-size: clamp(1.9rem, 3.4vw, 3rem); }
  .lede { font-size: clamp(1.05rem, 1.5vw, 1.3rem); line-height: 1.55; color: var(--ink-2); }
  .muted { color: var(--ink-3); }
  .mono { font-family: var(--mono); }
  .serif-it { font-style: italic; color: var(--accent); }

  /* ── Buttons ── */
  .btn {
    font-family: var(--mono); font-size: 0.74rem; letter-spacing: 0.14em; text-transform: uppercase;
    font-weight: 500; display: inline-flex; align-items: center; gap: 0.7em;
    padding: 0.95em 1.5em; border-radius: 999px;
    background: var(--ink); color: var(--paper);
    transition: transform .4s var(--ease), background .3s, box-shadow .4s var(--ease);
  }
  .btn:hover { background: var(--accent-deep); color: #fff; box-shadow: var(--shadow); }
  .btn .arrow { transition: transform .4s var(--ease); }
  .btn:hover .arrow { transform: translateX(4px); }
  .btn--ghost { background: transparent; color: var(--ink); border: 1px solid var(--line-2); }
  .btn--ghost:hover { background: rgba(96,165,250,0.1); border-color: var(--accent); color: var(--accent); }
  .btn--accent { background: var(--accent); color: #03060d; border: none; }
  .btn--accent:hover { background: var(--accent-deep); color: #fff; }
  .btn--sm { padding: 0.7em 1.15em; font-size: 0.68rem; }
  .magnetic { display: inline-block; }

  /* ── Chips ── */
  .chip {
    font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.04em; color: var(--ink-2);
    background: rgba(255,255,255,0.04); border: 1px solid var(--line);
    padding: 0.5em 0.9em; border-radius: 999px; display: inline-flex; align-items: center; gap: 0.5em;
    transition: border-color .25s, color .25s, background .25s, transform .25s var(--ease);
  }
  .chip:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .chip.is-active { background: var(--ink); color: var(--paper); border-color: var(--ink); }

  /* ── Header ── */
  .site-head {
    position: sticky; top: 0; z-index: 50;
    background: rgba(3,6,13,0.88); backdrop-filter: blur(18px) saturate(1.2);
    border-bottom: 1px solid transparent; transition: border-color .3s;
  }
  .site-head.is-stuck { border-color: var(--line); }
  .head-inner { display: flex; align-items: center; justify-content: space-between; height: 64px; gap: 20px; }
  .brand { display: inline-flex; align-items: baseline; gap: 0.6em; }
  .brand .mk-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); align-self: center; box-shadow: 0 0 0 3px var(--accent-soft); }
  .brand .mk-name { font-family: var(--mono); font-weight: 600; letter-spacing: 0.14em; font-size: 0.82rem; text-transform: uppercase; color: #fff; }
  .brand .mk-sub { font-family: var(--mono); font-weight: 400; letter-spacing: 0.22em; font-size: 0.62rem; text-transform: uppercase; color: var(--ink-3); }
  .nav { display: flex; align-items: center; gap: 6px; }
  .nav a:not(.btn) {
    font-family: var(--mono); font-size: 0.74rem; letter-spacing: 0.1em; text-transform: uppercase;
    padding: 0.6em 0.95em; border-radius: 999px; color: var(--ink-2);
    position: relative; transition: color .25s, background .25s;
  }
  .nav a:not(.btn):hover { color: var(--ink); background: rgba(255,255,255,0.06); }
  .nav a:not(.btn).is-current { color: var(--ink); }
  .nav a:not(.btn).is-current::after {
    content: ""; position: absolute; left: 0.95em; right: 0.95em; bottom: 0.35em; height: 1.5px; background: var(--accent);
  }
  .nav-cta { margin-left: 8px; }
  .burger { display: none; width: 42px; height: 42px; border-radius: 10px; border: 1px solid var(--line-2); align-items: center; justify-content: center; flex-direction: column; gap: 4px; }
  .burger span { width: 18px; height: 1.6px; background: var(--ink); transition: transform .3s var(--ease), opacity .3s; }
  .burger.is-open span:nth-child(1) { transform: translateY(5.6px) rotate(45deg); }
  .burger.is-open span:nth-child(2) { opacity: 0; }
  .burger.is-open span:nth-child(3) { transform: translateY(-5.6px) rotate(-45deg); }
  .m-nav {
    position: fixed; inset: 0; z-index: 49; background: rgba(3,6,13,0.97);
    backdrop-filter: blur(20px); padding: 90px var(--pad-x) 40px;
    display: flex; flex-direction: column; gap: 8px;
    transform: translateY(-100%); transition: transform .5s var(--ease); visibility: hidden;
  }
  .m-nav.is-open { transform: translateY(0); visibility: visible; }
  .m-nav a { font-family: var(--serif); font-size: 2rem; padding: 0.3em 0; border-bottom: 1px solid var(--line); }
  .m-nav a .n-num { font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-right: 1em; }

  /* ── Ticker ── */
  .ticker {
    position: relative; z-index: 40; background: var(--dark); color: var(--ink-on-dark);
    border-bottom: 1px solid rgba(255,255,255,0.06); overflow: hidden; height: 36px;
  }
  .ticker-track { display: flex; gap: 0; width: max-content; height: 100%; animation: ticker 24s linear infinite; align-items: center; }
  .ticker:hover .ticker-track { animation-play-state: paused; }
  @keyframes ticker { to { transform: translateX(-50%); } }
  .tk {
    font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.02em;
    display: inline-flex; align-items: center; gap: 0.55em;
    padding: 0.7em 1.3em; border-right: 1px solid rgba(255,255,255,0.07); white-space: nowrap;
    height: 100%;
  }
  .tk .sym { color: #fff; font-weight: 500; }
  .tk .px { color: var(--ink-2); }
  .tk .chg.up { color: #4FCF8E; }
  .tk .chg.down { color: #F2876F; }
  .tk .tri { font-size: 0.6rem; }

  /* ── Reveal — default visible, animate when JS adds .in (no-JS safe) ── */
  [data-reveal] { opacity: 1; transform: none; transition: opacity .7s var(--ease), transform .7s var(--ease); }
  [data-reveal-stagger] > * { opacity: 1; transform: none; transition: opacity .6s var(--ease), transform .6s var(--ease); }
  /* Only hide if JS explicitly opts-in by adding .pre class to <html>;
     belt-and-braces: 60 ms safety force-reveal in JS clears any pre state. */
  html.pre-reveal [data-reveal] { opacity: 0; transform: translateY(18px); }
  html.pre-reveal [data-reveal].in { opacity: 1; transform: none; }
  html.pre-reveal [data-reveal-stagger] > * { opacity: 0; transform: translateY(18px); }
  html.pre-reveal [data-reveal-stagger].in > * { opacity: 1; transform: none; }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
    [data-reveal], [data-reveal-stagger] > * { opacity: 1 !important; transform: none !important; }
  }

  /* ── Hero ── */
  .hero { padding: clamp(48px, 8vw, 110px) 0 clamp(40px, 6vw, 72px); }
  .hero-grid { display: grid; grid-template-columns: 1.45fr 1fr; gap: clamp(28px, 4vw, 64px); align-items: end; }
  .hero-head .display { margin: 0.35em 0 0; max-width: 14ch; }
  .hero-lede { margin-top: 1.3em; max-width: 46ch; }
  .hero-actions { margin-top: 2em; display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }

  /* ── Market Snapshot ── */
  .snap {
    background: var(--card); border: 1px solid var(--line-2); border-radius: var(--radius-lg);
    padding: clamp(18px,2vw,26px); box-shadow: var(--shadow); position: relative; overflow: hidden;
  }
  .snap::after { content:""; position:absolute; inset:0; border-radius:inherit; pointer-events:none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.06); }
  .snap-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
  .snap-live { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.16em; text-transform: uppercase; color: var(--up); display: inline-flex; align-items: center; gap: 0.5em; }
  .snap-live .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--up); position: relative; }
  .snap-live .pulse::after { content:""; position:absolute; inset:0; border-radius:50%; background: var(--up); animation: pulse 2s var(--ease) infinite; }
  @keyframes pulse { 0%{transform:scale(1);opacity:.7} 70%{transform:scale(2.6);opacity:0} 100%{opacity:0} }
  .idx-row { display: flex; justify-content: space-between; align-items: center; padding: 13px 0; border-top: 1px solid var(--line); }
  .idx-row:first-of-type { border-top: 0; }
  .idx-meta .idx-name { font-family: var(--mono); font-size: 0.78rem; font-weight: 500; letter-spacing: 0.02em; }
  .idx-meta .idx-sub { font-family: var(--mono); font-size: 0.62rem; color: var(--ink-3); letter-spacing: 0.04em; }
  .idx-spark { width: 96px; height: 34px; }
  .idx-val { text-align: right; min-width: 92px; }
  .idx-val .idx-px { font-family: var(--mono); font-size: 0.84rem; font-weight: 500; font-feature-settings:"tnum"; }
  .idx-val .idx-chg { font-family: var(--mono); font-size: 0.66rem; margin-top: 2px; }
  .idx-chg.up { color: var(--up); }
  .idx-chg.down { color: var(--down); }

  /* ── Market Band ── */
  .market-band { padding: clamp(8px,1vw,16px) 0 clamp(36px,5vw,60px); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: var(--paper-2); }
  .mb-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; }
  .mb-card {
    background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 16px 16px 12px; transition: transform .4s var(--ease), border-color .3s, box-shadow .4s var(--ease);
  }
  .mb-card:hover { transform: translateY(-3px); border-color: var(--line-2); box-shadow: var(--shadow-sm); }
  .mb-card .mb-name { font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); }
  .mb-card .mb-px { font-family: var(--mono); font-size: 1.05rem; font-weight: 500; margin: 6px 0 2px; font-feature-settings:"tnum"; }
  .mb-card .mb-chg { font-family: var(--mono); font-size: 0.7rem; display: inline-flex; gap: 0.3em; }
  .mb-card canvas { width: 100%; height: 30px; margin-top: 8px; }

  /* ── Section header ── */
  .sec-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: clamp(24px,3vw,40px); flex-wrap: wrap; }
  .sec-head .sec-title { max-width: 22ch; }
  .sec-num { font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.16em; color: var(--ink-3); }

  /* ── Publishing Model ── */
  .pubmodel { padding: clamp(40px,6vw,80px) 0; }
  .pubmodel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(28px,4vw,60px); align-items: start; }
  .pubmodel .chips-wrap { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }

  /* ── Story cards ── */
  .stories { display: grid; grid-template-columns: repeat(12, 1fr); gap: var(--gap); }
  .story { grid-column: span 4; display: flex; flex-direction: column; }
  .story--feature { grid-column: span 12; }
  .story-card {
    background: var(--card); border: 1px solid var(--line); border-radius: var(--radius-lg);
    padding: clamp(20px,2.2vw,30px); height: 100%; display: flex; flex-direction: column;
    transition: transform .5s var(--ease), box-shadow .5s var(--ease), border-color .4s;
    position: relative; overflow: hidden;
  }
  .story-card:hover { transform: translateY(-5px); box-shadow: var(--shadow); border-color: var(--line-2); }
  .story-card::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background: var(--accent); transform: scaleY(0); transform-origin: top; transition: transform .5s var(--ease); }
  .story-card:hover::before { transform: scaleY(1); }
  .story-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 18px; }
  .story-cat { font-family: var(--mono); font-size: 0.64rem; letter-spacing: 0.14em; text-transform: uppercase; }
  .story-read { font-family: var(--mono); font-size: 0.64rem; color: var(--ink-3); letter-spacing: 0.04em; }
  .story-title { font-family: var(--serif); font-weight: 560; line-height: 1.1; letter-spacing: -0.015em; font-size: clamp(1.3rem, 1.7vw, 1.65rem); margin-bottom: 0.5em; }
  .story--feature .story-title { font-size: clamp(1.9rem, 3.2vw, 2.9rem); max-width: 18ch; line-height: 1.06; }
  .story-dek { color: var(--ink-2); font-size: 0.98rem; line-height: 1.55; }
  .story--feature .story-dek { font-size: clamp(1.05rem,1.4vw,1.25rem); max-width: 52ch; }
  .story-foot { margin-top: auto; padding-top: 20px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  .story-date { font-family: var(--mono); font-size: 0.66rem; color: var(--ink-3); letter-spacing: 0.04em; }
  .story-go { font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink); display: inline-flex; align-items: center; gap: 0.5em; transition: gap .3s var(--ease), color .3s; }
  .story-card:hover .story-go { gap: 0.9em; color: var(--accent); }
  .story-metric { display: inline-flex; align-items: center; gap: 0.6em; font-family: var(--mono); font-size: 0.72rem; padding: 0.4em 0.7em; border: 1px solid var(--line); border-radius: 8px; }
  .story-metric canvas { width: 60px; height: 22px; }
  .story--feature .story-card { display: flex; flex-direction: column; gap: clamp(22px,2.5vw,30px); }
  .story--feature .feat-thumb { display: block; width: 100%; aspect-ratio: 21/9; border-radius: var(--radius); overflow: hidden; object-fit: cover; }
  .story--feature .feat-row { display: grid; grid-template-columns: 1.5fr 1fr; gap: 40px; align-items: center; }
  .story--feature .feat-row > *:first-child { display: flex; flex-direction: column; }
  .story--feature .feat-side { border-left: 1px solid var(--line); padding-left: 36px; }
  .feat-side-label { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-3); display: block; }
  .feat-brief-accent { display: flex; align-items: flex-end; gap: 3px; height: 26px; margin: 16px 0 18px; }
  .feat-brief-accent span { flex: 1; border-radius: 2px; background: linear-gradient(180deg, var(--accent), rgba(96,165,250,0.15)); }
  .feat-brief-accent span:nth-child(1) { height: 45%; }
  .feat-brief-accent span:nth-child(2) { height: 70%; }
  .feat-brief-accent span:nth-child(3) { height: 55%; }
  .feat-brief-accent span:nth-child(4) { height: 100%; }
  .feat-brief-accent span:nth-child(5) { height: 75%; }
  .feat-brief-accent span:nth-child(6) { height: 88%; }
  .feat-brief-accent span:nth-child(7) { height: 60%; }
  .feat-brief { display: flex; flex-direction: column; gap: 13px; }
  .feat-brief-row { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
  .feat-brief-row:last-child { border-bottom: 0; padding-bottom: 0; }
  .feat-brief-row span { font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-3); }
  .feat-brief-row strong { font-family: var(--serif); font-size: 1.02rem; font-weight: 600; color: var(--ink); text-align: right; }
  .feat-brief-tag { display: inline-flex; align-items: center; margin-top: 18px; padding: 0.45em 0.85em; border-radius: 999px; border: 1px solid rgba(96,165,250,0.35); background: rgba(96,165,250,0.08); color: var(--accent); font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.08em; text-transform: uppercase; }
  .story-thumb { display: block; width: 100%; aspect-ratio: 16/10; border-radius: var(--radius); overflow: hidden; margin-bottom: 20px; object-fit: cover; }

  /* Search & filter */
  #archive-search {
    width: min(340px,100%); border: 1px solid var(--line); border-radius: var(--radius);
    background: rgba(255,255,255,0.03); padding: 11px 14px; color: var(--ink);
    font-family: var(--mono); font-size: 0.82rem; outline: none; transition: border-color .2s;
  }
  #archive-search:focus { border-color: var(--accent); background: rgba(96,165,250,0.04); }
  #archive-search::placeholder { color: var(--ink-3); }
  .filter-strip { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
  [data-filter] {
    font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
    padding: 0.55em 1em; border-radius: 999px; border: 1px solid var(--line);
    background: rgba(255,255,255,0.03); color: var(--ink-2); cursor: pointer;
    display: inline-flex; align-items: center; gap: 0.5em;
    transition: border-color .2s, color .2s, background .2s, transform .2s var(--ease);
  }
  [data-filter]:hover, [data-filter].is-active { border-color: var(--accent); color: var(--accent); background: rgba(96,165,250,0.08); transform: translateY(-1px); }
  [data-filter] span { font-family: var(--mono); font-size: 0.62rem; color: var(--ink-3); }
  #story-count { font-family: var(--mono); font-size: 0.72rem; color: var(--ink-3); letter-spacing: 0.06em; }

  /* ── Principles ── */
  .principles { padding: clamp(40px,6vw,80px) 0; background: var(--paper-2); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .principle-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--gap); }
  .principle { border-top: 2px solid rgba(96,165,250,0.3); padding-top: 22px; }
  .principle .p-num { font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.16em; color: var(--accent); margin-bottom: 14px; display: block; }
  .principle h3 { font-size: clamp(1.3rem,1.8vw,1.7rem); line-height: 1.12; margin-bottom: 0.55em; }
  .principle p { color: var(--ink-2); font-size: 0.98rem; line-height: 1.6; }

  /* ── Contact ── */
  .contact { padding: clamp(50px,7vw,100px) 0; }
  .contact-card {
    background: var(--dark); color: var(--ink-on-dark); border-radius: var(--radius-lg);
    border: 1px solid var(--line-2);
    padding: clamp(34px,5vw,72px); display: grid; grid-template-columns: 1.2fr 1fr;
    gap: clamp(30px,4vw,64px); position: relative; overflow: hidden;
  }
  .contact-card .eyebrow { color: rgba(234,227,214,0.6); }
  .contact-card .eyebrow .dot { box-shadow: 0 0 0 3px rgba(255,255,255,0.08); }
  .contact-card h2 { color: #fff; font-size: clamp(1.9rem,3.2vw,3rem); margin-top: 0.4em; }
  .contact-card .c-lede { color: rgba(234,227,214,0.7); margin-top: 1em; max-width: 40ch; }
  .contact-form { display: flex; flex-direction: column; gap: 14px; }
  .field label { font-family: var(--mono); font-size: 0.64rem; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(234,227,214,0.55); display: block; margin-bottom: 7px; }
  .field input, .field textarea {
    width: 100%; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.14); border-radius: 10px;
    padding: 12px 14px; color: #fff; font-family: var(--mono); font-size: 0.86rem; transition: border-color .25s, background .25s;
  }
  .field input:focus, .field textarea:focus { outline: none; border-color: var(--accent); background: rgba(255,255,255,0.08); }
  .field textarea { resize: vertical; min-height: 84px; }
  .contact-form .btn--accent { justify-content: center; margin-top: 4px; }
  .c-details { display: flex; flex-direction: column; gap: 18px; margin-top: 30px; }
  .c-detail { border-top: 1px solid rgba(255,255,255,0.1); padding-top: 14px; }
  .c-detail .cd-k { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(234,227,214,0.5); }
  .c-detail .cd-v { font-family: var(--serif); font-size: 1.15rem; margin-top: 4px; }

  /* ── Footer ── */
  .foot { position: relative; z-index: 2; background: var(--dark); color: var(--ink-on-dark); margin-top: clamp(60px, 9vw, 130px); }
  .foot a { color: var(--ink-on-dark); }
  .foot .foot-grid { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 40px; padding: clamp(50px,7vw,90px) 0 40px; }
  .foot .mk-name { color: #fff; }
  .foot-disc { font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.03em; color: rgba(234,227,214,0.55); line-height: 1.7; }
  .foot-col h4 { font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.18em; text-transform: uppercase; color: rgba(234,227,214,0.5); margin-bottom: 14px; font-weight: 500; }
  .foot-col ul { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .foot-col a { font-family: var(--mono); font-size: 0.82rem; opacity: 0.85; transition: opacity .2s, color .2s; }
  .foot-col a:hover { opacity: 1; color: #fff; }
  .foot-base { display: flex; justify-content: space-between; align-items: center; padding: 22px 0 30px; border-top: 1px solid rgba(255,255,255,0.08); font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.06em; color: rgba(234,227,214,0.5); flex-wrap: wrap; gap: 14px; }

  /* ── Custom cursor ── */
  .cursor-dot, .cursor-ring { position: fixed; top: 0; left: 0; z-index: 9999; pointer-events: none; border-radius: 50%; mix-blend-mode: difference; }
  .cursor-dot { width: 6px; height: 6px; background: #fff; transform: translate(-50%,-50%); }
  .cursor-ring { width: 34px; height: 34px; border: 1px solid #fff; transform: translate(-50%,-50%); transition: width .25s var(--ease), height .25s var(--ease), background .25s, opacity .25s; }
  .cursor-ring.is-hover { width: 54px; height: 54px; background: rgba(255,255,255,0.12); }
  @media (hover: none), (pointer: coarse) { .cursor-dot, .cursor-ring { display: none; } }

  /* ── Responsive ── */
  @media (max-width: 1080px) { .mb-grid { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 880px) { .nav { display: none; } .burger { display: flex; } .foot .foot-grid { grid-template-columns: 1fr 1fr; gap: 30px; } }
  @media (max-width: 900px) {
    .hero-grid { grid-template-columns: 1fr; align-items: start; }
    .hero-head .display { max-width: 18ch; }
    .pubmodel-grid { grid-template-columns: 1fr; }
    .story { grid-column: span 6; }
    .story--feature .feat-row { grid-template-columns: 1fr; gap: 24px; }
    .story--feature .feat-side { border-left: 0; border-top: 1px solid var(--line); padding-left: 0; padding-top: 24px; }
    .principle-grid { grid-template-columns: 1fr; gap: 30px; }
    .contact-card { grid-template-columns: 1fr; }
  }
  @media (max-width: 620px) {
    .mb-grid { grid-template-columns: repeat(2, 1fr); }
    .story, .story--feature { grid-column: span 12; }
  }
  @media (max-width: 560px) { .foot .foot-grid { grid-template-columns: 1fr; } }

  /* ── Live Market Snapshot (real-time from /public/market/ticker) ── */
  .market-snapshot {
    margin: clamp(20px, 3vw, 36px) 0 clamp(28px, 4vw, 48px);
    padding: 22px 24px 26px;
    background: var(--bg-elevated, rgba(10,22,44,0.78));
    border: 1px solid var(--line);
    border-radius: 22px;
    box-shadow: var(--shadow);
  }
  .snap-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
  .snap-kicker {
    display: inline-flex; align-items: center; gap: 8px;
    font-family: var(--mono); font-size: 11px; color: var(--accent);
    text-transform: uppercase; letter-spacing: 0.10em; font-weight: 600;
  }
  .snap-pulse {
    width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
    box-shadow: 0 0 0 0 rgba(96,165,250,0.55);
    animation: snap-pulse 1.6s ease-out infinite;
  }
  @keyframes snap-pulse {
    0% { box-shadow: 0 0 0 0 rgba(96,165,250,0.55); }
    70% { box-shadow: 0 0 0 10px rgba(96,165,250,0); }
    100% { box-shadow: 0 0 0 0 rgba(96,165,250,0); }
  }
  .snap-sub { font-family: var(--mono); font-size: 10.5px; color: var(--muted); letter-spacing: 0.06em; }
  .snap-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
  .snap-card {
    position: relative; padding: 14px 14px 12px;
    background: rgba(3, 8, 20, 0.62);
    border: 1px solid var(--line);
    border-radius: 14px; min-height: 96px;
    transition: border-color 0.2s ease, transform 0.2s ease;
  }
  .snap-card:hover { border-color: var(--line-strong); transform: translateY(-1px); }
  .snap-card .sc-name { font-family: var(--mono); font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
  .snap-card .sc-spark { margin: 4px 0 6px; height: 30px; width: 100%; display: block; }
  .snap-card .sc-row { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
  .snap-card .sc-val { font-family: var(--mono); font-size: 15px; font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; }
  .snap-card .sc-chg { font-family: var(--mono); font-size: 11px; font-weight: 600; }
  .snap-card .sc-chg.up   { color: #34D399; }
  .snap-card .sc-chg.down { color: #FB7185; }
  .snap-card.snap-skel .sk-name, .snap-card.snap-skel .sk-spark, .snap-card.snap-skel .sk-val {
    background: linear-gradient(90deg, rgba(96,165,250,0.05) 25%, rgba(96,165,250,0.12) 50%, rgba(96,165,250,0.05) 75%);
    background-size: 200% 100%; animation: skel-shimmer 1.4s linear infinite; border-radius: 6px;
  }
  .snap-card.snap-skel .sk-name  { height: 9px; width: 50%; margin-bottom: 8px; }
  .snap-card.snap-skel .sk-spark { height: 28px; width: 100%; margin-bottom: 8px; }
  .snap-card.snap-skel .sk-val   { height: 14px; width: 70%; }
  @keyframes skel-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
"""

_FLASH_PASSES = int(os.getenv("FINAGENT_CONTENT_FLASH_PASSES", "3"))
_DEEP_PASSES = int(os.getenv("FINAGENT_CONTENT_DEEP_PASSES", "8"))
_DEEP_WALL_SECONDS = float(os.getenv("FINAGENT_CONTENT_DEEP_WALL_SECONDS", "420"))
_FLASH_WALL_SECONDS = 180.0
_PUBLISH_GATE_THRESHOLDS = {
    "confidence": 85,
    "editorial_score": 85,
    "source_score": 85,
    "depth_score": 85,
    "evidence_score": 95,
    "publish_gate_score": 90,
}
_OFFICIAL_DOMAIN_HINTS = (
    "nseindia.com",
    "bseindia.com",
    "bseindia",
    "sebi.gov.in",
    "rbi.org.in",
    "mca.gov.in",
)
_TRUSTED_SUPPORTING_DOMAIN_HINTS = (
    "reuters.com",
    "bloomberg.com",
    "moneycontrol.com",
    "thehindu.com",
    "economictimes.indiatimes.com",
    "business-standard.com",
    "business-standard",
    "financialexpress.com",
    "ndtvprofit.com",
)
# Hard block: never publish Livemint as a primary or supporting source.
_BLOCKED_PUBLIC_DOMAIN_HINTS = ("livemint.com",)
_LIMITED_DATA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\blimited data\b", re.I),
    re.compile(r"\binsufficient data\b", re.I),
    re.compile(r"\bdata (?:was|were|is|are) not available\b", re.I),
    re.compile(r"\bunable to verify\b", re.I),
    re.compile(r"\bnot enough information\b", re.I),
)
_FILLER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bit is worth noting\b", re.I),
    re.compile(r"\bin conclusion\b", re.I),
    re.compile(r"\boverall[, ]", re.I),
    re.compile(r"\bneedless to say\b", re.I),
    re.compile(r"\bthis indicates that\b", re.I),
)
_SOURCE_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baccording to\b", re.I),
    re.compile(r"\bofficial disclosure\b", re.I),
    re.compile(r"\bverified filing\b", re.I),
    re.compile(r"\bcompany records\b", re.I),
    re.compile(r"\bexchange filing\b", re.I),
    re.compile(r"\bregulatory filing\b", re.I),
    re.compile(r"\bsebi\b", re.I),
    re.compile(r"\bnse\b", re.I),
    re.compile(r"\bbse\b", re.I),
)

_COMPANY_NAME_NOISE_TOKENS = {
    "limited",
    "ltd",
    "ltd.",
    "company",
    "co",
    "co.",
    "inc",
    "inc.",
    "plc",
    "private",
    "public",
    "india",
    "indian",
    "the",
    "and",
    "&",
}

_DIAGNOSTIC_PUBLIC_TOKENS: tuple[str, ...] = (
    "top metrics from the current evidence set",
    "quick visual read of the key data",
    "research coverage and limitations",
    "sources processed",
    "quality score",
    "specialist findings",
    "conflicts detected",
    "financial metrics resolved",
    "canonical entity resolution",
    "source count",
    "official source count",
    "supporting source count",
    "document evidence status",
    "context enrichment status",
    "evidence coverage by source type",
    "evidence coverage",
)
_BUSINESS_NUMERIC_HINTS: tuple[str, ...] = (
    "revenue",
    "profit",
    "loss",
    "margin",
    "ebit",
    "ebitda",
    "eps",
    "cash",
    "debt",
    "borrow",
    "order",
    "order book",
    "backlog",
    "guidance",
    "dividend",
    "buyback",
    "stake",
    "holding",
    "capex",
    "tcv",
    "turnover",
    "net worth",
    "assets",
    "liabilities",
    "default",
    "penalty",
    "settlement",
    "valuation",
    "growth",
    "yoy",
    "qoq",
    "fy",
    "quarter",
    "segment",
)


# Bound concurrent generation jobs so they don't saturate the pipeline
_FLASH_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _FLASH_SEMAPHORE
    if _FLASH_SEMAPHORE is None:
        _FLASH_SEMAPHORE = asyncio.Semaphore(2)
    return _FLASH_SEMAPHORE


# ── Flash pass objectives (3 passes: 2 research + 1 synthesis) ───────────────

_CONTENT_FLASH_OBJECTIVES: list[str] = [
    # Pass 0 — Deterministic data extraction
    (
        "FACTS & DATA EXTRACTION: Extract every verifiable data point — revenue, profit, margins, "
        "YoY/QoQ growth, EPS, dividend, debt, cash, capex — directly from official exchange filings "
        "(BSE/NSE announcements), XBRL reports, company press releases, and regulatory orders. "
        "Do NOT infer or estimate figures; flag any missing or ambiguous data. "
        "Capture exact numbers with source citation for each. Note discrepancies across sources."
    ),
    # Pass 1 — Market context and interpretation
    (
        "CONTEXT & MARKET ANALYSIS: Interpret the extracted data through industry benchmarks, peer "
        "performance, analyst expectations, and macro environment (RBI, PLI schemes, USD-INR impact, "
        "sector dynamics, FII/DII flows). What changed versus the prior period and why? How does this "
        "compare to sector peers? What does this signal for the business trajectory? "
        "Every claim must be grounded in a named source."
    ),
    # Pass 2 — Full article synthesis (always last, emits memo)
    (
        "ARTICLE SYNTHESIS — FINAL: You are a senior markets correspondent at a top Indian business daily. "
        "Write a publication-ready financial article with the authority and depth of LiveMint or Hindu BusinessLine.\n\n"
        "VOICE & STRUCTURE RULES:\n"
        "- LEDE: Open with stakes — what happened, why it matters, and what changes for the reader. No throat-clearing.\n"
        "- PARAGRAPH 2: 'Why now' — the catalyst, trigger, or timing that makes this story urgent today.\n"
        "- EVERY substantive section: at least one historical comparison OR sector benchmark with specific numbers.\n"
        "- ATTRIBUTION: 'The street had expected...', 'Management guided for...', 'Analysts at X estimated...' — never unattributed opinion.\n"
        "- CLOSE: Forward-looking — upcoming catalysts, next data point, what smart money is watching.\n"
        "- BANNED FILLER: 'significant growth', 'strong performance', 'notable development', 'robust numbers', "
        "'going forward', 'it remains to be seen', 'only time will tell'. Use specific numbers instead.\n\n"
        "Return ONLY valid JSON matching the ContentArticlePackage schema:\n"
        "  slug (URL-safe, 2-80 chars),\n"
        "  title (LiveMint-style headline, 60-100 chars, MUST anchor on a specific number/named entity, not generic SEO),\n"
        "  description (140-170 chars), hero_eyebrow, hero_title (max 100 chars),\n"
        "  hero_summary (2-3 sentences, 100-300 chars), audience, keywords (8-12),\n"
        "  narrative_lede (REQUIRED 40-70 words: inverted-pyramid opener, key number first, flowing prose),\n"
        "  market_context (REQUIRED 50-90 words: index/sector/peer/macro backdrop with numbers in sentences),\n"
        "  analyst_commentary (REQUIRED 50-90 words: estimate revisions, valuation, drivers, as continuous prose),\n"
        "  key_takeaways (3-6: {heading, detail}), metrics (4-8: {label, value, change?, period?, source?}),\n"
        "  tables (1-3: {title, columns, rows, footnote?}),\n"
        "  visuals (1-2: {kind, title, points[{label,value}], note?}),\n"
        "  timeline (0-8: {date, event, detail?, source?}),\n"
        "  evidence_notes (0-10: {claim, source_title, source_url}),\n"
        "  sections (5-7: {heading, paragraphs: [2-3 str], bullets: [0-5 str]}),\n"
        "  faqs (4-5: {question, answer} — real retail investor questions),\n"
        "  cta_label, cta_href,\n"
        "  image_prompt (REQUIRED — premium editorial cover for the ProspektLab dark research terminal: "
        "3:2 ratio, deep navy (#14233B) backdrop with cream (#EAE3D6) accents, one strong central subject tied to the story "
        "(banking columns for lenders, circuit nodes for IT, listing bell for IPO, central-bank geometry for RBI/macro, "
        "overlapping seals for M&A, forensic document shapes for fraud), soft volumetric lighting, "
        "Bloomberg/FT editorial mood, India market context, no headline text, no watermark)\n"
        "SEBI compliance: NO buy/sell/hold/accumulate/exit/target price/rebalancing. "
        "Cite every statistic. Zero filler."
    ),
]

# ── Deep pass objectives (8 passes: 7 research + 1 synthesis) ────────────────

_CONTENT_DEEP_OBJECTIVES: list[str] = [
    # Pass 0
    (
        "BREAKING FACTS & FINANCIAL DATA: Extract every verifiable number from the latest filings — "
        "P&L (revenue, EBITDA, PAT, gross/net margins), balance sheet (total debt, cash, equity, "
        "working capital, inventory days), cash flow (OCF, FCF, capex, free-cash yield), XBRL-reported "
        "metrics, QoQ and YoY delta. Source only official filings: NSE/BSE exchange announcements, "
        "annual reports, concall transcripts, XBRL data. Flag any inferred figure explicitly."
    ),
    # Pass 1
    (
        "SECTOR & MACRO CONTEXT: Industry total addressable market size and growth rate, competitive "
        "structure (top 5 players, market share), regulatory environment (RBI, SEBI, sector-specific "
        "regulators), macro drivers (PLI schemes, inflation pass-through, USD-INR sensitivity, crude "
        "oil/commodity impact), government capex cycle effect, sector index outperformance/underperformance. "
        "Ground every assertion in a named data source."
    ),
    # Pass 2
    (
        "GOVERNANCE & OWNERSHIP INTELLIGENCE: Promoter holding structure (% owned, % pledged, trend "
        "over last 8 quarters), key director network and board independence score, related party "
        "transactions (nature, value, year), auditor name and tenure/qualifications, SEBI enforcement "
        "notices or adjudication orders on the company or promoters, corporate governance red flags "
        "from public records. Cite source for each finding — IKG graph data preferred."
    ),
    # Pass 3
    (
        "RISK ASSESSMENT & RED FLAGS: Regulatory risk (SEBI orders, show-cause notices, adjudications, "
        "ongoing investigations), litigation exposure (court filings, consumer complaints, arbitrations), "
        "key-person dependency (promoter concentration risk, single-customer/supplier risk), ESG "
        "controversies, forex and commodity sensitivity, credit rating changes (upgrade/downgrade). "
        "Quantify the estimated financial impact where data supports it."
    ),
    # Pass 4
    (
        "VALUATION FRAMING (SEBI-SAFE): Current trading multiples vs 3-year historical ranges — "
        "P/E, EV/EBITDA, P/B, EV/Sales, dividend yield. Implied scenario analysis from consensus — "
        "what revenue and earnings CAGR is the current price discounting? How has the stock re-rated "
        "vs sector peers over the last 1 and 3 years? Present ONLY as factual scenario ranges. "
        "ABSOLUTE PROHIBITION: NO buy/sell/hold/accumulate/exit/target price/rebalancing instruction. "
        "SEBI compliance is non-negotiable."
    ),
    # Pass 5
    (
        "GROWTH CATALYSTS & BUSINESS OUTLOOK: New product launches and their revenue addressable market, "
        "capacity expansion (capex committed, timeline, nameplate capacity post-expansion), government "
        "contracts and open tenders, M&A activity or rumours, international expansion milestones, R&D "
        "pipeline and IP filings, PLI scheme benefit realization schedule, verbatim management guidance "
        "from the latest concall. For each catalyst: probability, timeline, and revenue/margin impact."
    ),
    # Pass 6
    (
        "SMART-MONEY SIGNALS & SHAREHOLDING: Institutional flows — FII net buying/selling (3-quarter "
        "trend), DII activity (insurance + MF combined), top-5 mutual fund holders and QoQ position "
        "changes (entry/exit), promoter pledge delta, bulk and block deal activity with counterparty "
        "names. What are sophisticated institutions doing and what directional signal does it carry?"
    ),
    # Pass 7 — synthesis (always last, emits memo as JSON)
    (
        "DEEP ARTICLE SYNTHESIS — FINAL: You are a senior markets correspondent writing the definitive "
        "investigative piece on this company/event. Your standard is LiveMint's long-form business coverage "
        "— thorough, authoritative, and impossible to skim without learning something.\n\n"
        "Integrate ALL 7 prior research passes. VOICE & STRUCTURE:\n"
        "- LEDE: Stakes first — the single most important number or event, and why it matters NOW.\n"
        "- PARAGRAPH 2: 'Why now' — the catalyst that makes this story land today, not last week.\n"
        "- HISTORICAL DEPTH: Every substantive claim gets a comparison (vs prior quarter, vs peer, vs sector, vs 3-year average).\n"
        "- ATTRIBUTION: 'The street expected X', 'Management guided for Y', 'SEBI's order noted...' — never naked opinion.\n"
        "- GOVERNANCE SECTION: One section MUST examine verified ownership, governance, and filing signals "
        "(promoter pledges, RPTs, auditor tenure, SEBI enforcement where records exist).\n"
        "- CLOSE: Forward-looking — upcoming catalysts, next reporting date, what institutional money is watching.\n"
        "- BANNED FILLER: 'significant', 'strong', 'notable', 'robust', 'going forward', 'it remains to be seen', "
        "'only time will tell', 'amid concerns'. Replace every one with a specific number or fact.\n\n"
        "Return ONLY valid JSON matching ContentArticlePackage schema:\n"
        "  slug,\n"
        "  title (LiveMint-style headline, 60-100 chars, MUST anchor on a specific number or named entity — "
        "e.g. 'TCS Q3 profit jumps 12% to Rs 11,400 crore as deal pipeline hits $42 bn'; never a generic SEO title),\n"
        "  description (140-170 chars), hero_eyebrow, hero_title, hero_summary, audience, keywords (10-12),\n"
        "  narrative_lede (REQUIRED, 40-70 words: inverted-pyramid opener that front-loads the single most important "
        "number and insight in the first sentence, written as flowing prose, not bullets),\n"
        "  market_context (REQUIRED, 50-90 words: situate the story in the index level, sector move, peer comparison, "
        "and macro backdrop with hard numbers woven into sentences),\n"
        "  analyst_commentary (REQUIRED, 50-90 words: analyst-grade interpretation — estimate revisions, valuation "
        "multiples, margin/growth drivers — woven as continuous prose, NOT a bullet dump),\n"
        "  key_takeaways, metrics, tables, visuals, timeline, evidence_notes,\n"
        "  sections (7-9: {heading, paragraphs: [2-4 str of 60+ words each, numbers embedded INSIDE the sentences], "
        "bullets: [0-3 str — prefer prose over bullets]}),\n"
        "  faqs (5-6: real investor questions with data-backed answers),\n"
        "  cta_label, cta_href,\n"
        "  image_prompt (REQUIRED — premium editorial cover for the ProspektLab dark research terminal: "
        "3:2 ratio, deep navy (#14233B) backdrop with cream (#EAE3D6) accents, one strong central subject tied to the story "
        "(banking columns for lenders, circuit nodes for IT, listing bell for IPO, central-bank geometry for RBI/macro, "
        "overlapping seals for M&A, forensic document shapes for fraud), soft volumetric lighting, "
        "Bloomberg/FT editorial mood, India market context, no headline text, no watermark)\n"
        "EDITORIAL STANDARD: Write like a LiveMint/Mint finance journalist — data-led, narrative-driven, "
        "inverted pyramid (key numbers first, then context, then analysis, then forward implications). "
        "Integrate numbers into continuous prose; never leave data stranded only in metric blocks. "
        "Vary sentence length for journalistic cadence.\n"
        "SEBI compliance: NO buy/sell/hold/accumulate/exit/target price. "
        "Cite every statistic. Zero filler. Return raw JSON only."
    ),
]


# ── Request / result models ───────────────────────────────────────────────────

class FlashGenerationRequest(BaseModel):
    mode: Literal["flash", "deep", "research"] = "research"
    content_type: Literal["earnings", "sebi", "trend", "company", "manual"] = "manual"
    target: str = Field(..., min_length=2, max_length=300,
                        description="Company name, ticker, SEBI order subject, or topic")
    objective: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)
    source_markdown: str | None = Field(default=None, max_length=30000)
    source_evidence_meta: dict[str, Any] | None = None
    route_base: str = Field(default="insights", max_length=40)
    force_publish: bool = False
    include_image: bool = True
    overwrite: bool = True


class FlashIngestRequest(BaseModel):
    content_type: Literal["earnings", "sebi", "trend"] = "earnings"
    mode: Literal["flash", "deep", "research"] = "research"
    symbols: list[str] = Field(default_factory=list, max_length=20,
                               description="Ticker symbols for earnings/company types")
    isin_list: list[str] = Field(default_factory=list, max_length=20)
    bse_codes: list[str] = Field(default_factory=list, max_length=20)
    route_base: str = Field(default="insights", max_length=40)
    max_events_per_source: int = Field(default=5, ge=1, le=15)
    include_image: bool = True
    dry_run: bool = False


class FlashIngestResult(BaseModel):
    route_base: str
    generated_at: str
    discovered_events: int = 0
    generated_articles: int = 0
    auto_published: int = 0
    drafts: int = 0
    skipped_seen: int = 0
    failures: list[dict[str, str]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


# ── IKG context builder ───────────────────────────────────────────────────────

_MANUAL_EARNINGS_MARKERS = (
    "earnings", "results", "result", "quarter", "q1", "q2", "q3", "q4",
    "fy", "concall", "conference call", "fact sheet", "investor release",
)
_MANUAL_SEBI_MARKERS = (
    "sebi", "adjudication", "show cause", "settlement", "order", "penalty",
    "interim order", "enforcement",
)
_MANUAL_TREND_MARKERS = (
    "sector", "industry", "theme", "macro", "market", "outlook", "cycle",
    "policy", "trend",
)
_MANUAL_COMPANY_MARKERS = (
    "limited", "ltd", "bank", "services", "industries", "technology",
    "pharma", "finance", "motors", "power",
)
_IKG_TARGET_NOISE = re.compile(
    r"\b(q[1-4]|fy ?\d{2,4}|earnings?|results?|overview|analysis|update|preview|review|call|concall|fact ?sheet|transcript)\b",
    flags=re.IGNORECASE,
)


def _label_for_content_type(content_type: str) -> str:
    label_map = {
        "earnings": "Earnings Analysis",
        "sebi": "SEBI and Regulatory",
        "trend": "Market Trend Analysis",
        "company": "Company Intelligence",
        "manual": "Financial Insight",
    }
    return label_map.get((content_type or "manual").strip().lower(), "Financial Insight")


def _infer_manual_content_type(target: str, objective: str | None = None) -> str:
    text = f"{target} {objective or ''}".strip().lower()
    if any(marker in text for marker in _MANUAL_SEBI_MARKERS):
        return "sebi"
    if any(marker in text for marker in _MANUAL_EARNINGS_MARKERS):
        return "earnings"
    if any(marker in text for marker in _MANUAL_TREND_MARKERS):
        return "trend"
    if any(marker in text for marker in _MANUAL_COMPANY_MARKERS):
        return "company"
    tokens = [token for token in re.split(r"\s+", target.strip()) if token]
    if tokens and len(tokens) <= 6 and any(token.isupper() and len(token) <= 8 for token in tokens):
        return "company"
    return "manual"


def _effective_content_type(req: "FlashGenerationRequest") -> str:
    if req.content_type != "manual":
        return req.content_type
    return _infer_manual_content_type(req.target, req.objective)


def _normalise_ikg_target(target: str, content_type: str) -> str:
    cleaned = _IKG_TARGET_NOISE.sub(" ", target or "")
    cleaned = re.sub(r"[^A-Za-z0-9&().,\- ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,:")
    if cleaned and content_type in {"earnings", "company", "manual"}:
        words = cleaned.split()
        if len(words) > 6:
            cleaned = " ".join(words[:6])
    return cleaned or (target or "").strip()


def _article_structure_brief(content_type: str, target: str, has_ikg: bool) -> str:
    base = (
        "General requirements:\n"
        "- Lead with what changed and why it matters now.\n"
        "- Output structured presentation blocks: key_takeaways, metrics, tables, visuals, timeline, evidence_notes.\n"
        "- Keep metrics and tables source-backed. If a number is not in evidence, do not invent it.\n"
        "- Avoid generic company introductions unless they directly explain the quarter or event.\n"
        "- Do not mix live stock price, market cap, or valuation trivia into a historic earnings article unless clearly labeled with date and source.\n"
        "- Distinguish reported numbers, management commentary, and ProspektLab inference.\n"
    )
    if content_type == "earnings":
        base += (
            "For earnings-like topics, structure the article around:\n"
            "1. The quarter in one paragraph.\n"
            "2. The metrics that actually moved (revenue, margin, profit, cash, deal wins, dividend if declared).\n"
            "3. Demand by geography, vertical, product line, or client segment.\n"
            "4. Margin quality, hiring, productivity, attrition, and cash conversion.\n"
            "5. Management commentary, order book, discretionary-spend signals, and what to monitor next.\n"
            "6. Include at least one earnings table with YoY/QoQ deltas and one visual block based on those metrics.\n"
        )
    elif content_type == "company":
        base += (
            "For company intelligence topics, structure the article around business model, financial trajectory, governance, risks, catalysts, and peer context.\n"
            "Include one comparison table or metric strip plus one visual summary.\n"
        )
    elif content_type == "sebi":
        base += (
            "For SEBI topics, structure the article around the order timeline, allegations/findings, financial or governance implications, and what changes for public investors.\n"
            "Include a timeline block and a parties/action/status table when evidence supports it.\n"
        )
    elif content_type == "trend":
        base += (
            "For trend topics, structure the article around the thesis, data points, policy or macro triggers, segment winners and laggards, and the market consequences.\n"
            "Include one metrics table and one visual signal block.\n"
        )
    if has_ikg:
        base += (
            '- Include one dedicated section on verified ownership, governance, and filing signals.\n'
            "- If record coverage is partial, say so plainly instead of inventing missing governance data.\n"
        )
    return base


def _build_insights_hub_html_editorial(route_base: str = "insights") -> str:
    """
    Render the SEO landing page at /insights/research/
    listing all published articles in an editorial, filterable layout.
    """
    from finagent.content_automation import list_generated_articles

    route_base = _safe_route_base(route_base)
    articles = list_generated_articles(route_base=route_base, limit=120)
    published = [
        a for a in articles
        if str(a.get("publish_status") or "").lower() == "published"
        and str(a.get("publish_gate_status") or "").lower() == "publish"
    ]
    total = len(articles)
    published_count = len(published)
    research_count = sum(
        1
        for article in published
        if str(article.get("mode") or "").lower() in {"deep", "research"}
    )
    ikg_count = sum(1 for article in published if bool(article.get("ikg_covered")))
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # Identity accents tuned to ProspektLab dark theme — distinguishable but
    # all in the cyan/violet/coral/ice family so the hub reads as one product.
    type_meta: dict[str, dict[str, str]] = {
        "earnings": {"label": "Earnings", "accent": "#60A5FA"},   # cyan
        "sebi":     {"label": "SEBI",     "accent": "#FB7185"},   # coral
        "trend":    {"label": "Trend",    "accent": "#C7D2FE"},   # ice
        "company":  {"label": "Company",  "accent": "#8B5CF6"},   # violet
        "manual":   {"label": "Insight",  "accent": "#34D399"},   # mint
    }

    def _story_score(article: dict[str, Any]) -> int:
        raw = article.get("quality_score")
        if raw in (None, ""):
            raw = article.get("confidence_score")
        try:
            return int(round(float(raw or 0)))
        except Exception:
            return 0

    def _rgba(hex_colour: str, alpha: float) -> str:
        cleaned = (hex_colour or "#64748b").lstrip("#")
        if len(cleaned) != 6:
            return f"rgba(100, 116, 139, {alpha})"
        try:
            red = int(cleaned[0:2], 16)
            green = int(cleaned[2:4], 16)
            blue = int(cleaned[4:6], 16)
        except Exception:
            return f"rgba(100, 116, 139, {alpha})"
        return f"rgba({red}, {green}, {blue}, {alpha})"

    def _format_date(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return "Recently updated"
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.strftime("%d %b %Y")
        except Exception:
            return html.escape(raw[:10])

    def _image_href(article: dict[str, Any]) -> str:
        slug = str(article.get("slug") or "").strip()
        if not slug:
            return "/prospektlab-logo.svg"
        detected_cover = _find_cover_asset_name(route_base, slug)
        if detected_cover:
            return f"/{route_base}/{slug}/{detected_cover}"
        suffix = Path(str(article.get("image_path") or "")).suffix.lower()
        ext = suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"} else ".png"
        return f"/{route_base}/{slug}/cover{ext}"

    def _search_blob(article: dict[str, Any]) -> str:
        chunks = [
            str(article.get("title") or ""),
            str(article.get("description") or ""),
            str(article.get("hero_summary") or ""),
            str(article.get("audience") or ""),
        ]
        keywords = article.get("keywords") or []
        if isinstance(keywords, list):
            chunks.extend(str(item) for item in keywords[:8])
        return sanitize_public_text(" ".join(chunks).strip()).lower()

    def _story_card(article: dict[str, Any], *, featured: bool = False) -> str:
        slug = str(article.get("slug") or "").strip()
        title_text = sanitize_public_text(str(article.get("title") or slug or "Untitled insight"))
        summary_text = sanitize_public_text(str(article.get("hero_summary") or article.get("description") or "").strip())
        description_text = sanitize_public_text(str(article.get("description") or summary_text).strip())
        content_type = str(article.get("content_type") or "manual").strip().lower() or "manual"
        meta = type_meta.get(content_type, type_meta["manual"])
        accent = meta["accent"]
        local_url = f"/{route_base}/{slug}/" if slug else "#"
        summary_limit = 280 if featured else 180
        summary = summary_text[:summary_limit].rstrip()
        if summary and len(summary_text) > summary_limit:
            summary = summary.rstrip(" .,;:") + "..."
        ikg = bool(article.get("ikg_covered"))
        feature_note = '<div class="feature-note">Lead story</div>' if featured else ""
        date_label = _format_date(str(article.get("published_at") or article.get("generated_at") or ""))
        cover_href = html.escape(_image_href(article))
        title = html.escape(title_text)
        deck = html.escape(summary or description_text[:summary_limit] or "Publication-ready market research.")
        description = html.escape(description_text[:170])
        story_class = "story-card story-card-featured" if featured else "story-card"
        search_attr = html.escape(_search_blob(article), quote=True)
        return (
            f'<article class="{story_class}" style="--card-accent:{accent};--card-accent-soft:{_rgba(accent, 0.12)};" '
            f'data-story data-type="{html.escape(content_type)}" data-ikg="{"yes" if ikg else "no"}" '
            f'data-search="{search_attr}">'
            f'<a class="story-media" href="{html.escape(local_url)}" aria-label="{title}">'
            f'<img class="story-image" src="{cover_href}" alt="{title} cover image" loading="lazy" />'
            "</a>"
            '<div class="story-body">'
            f"{feature_note}"
            '<div class="story-overline">'
            f'<span class="meta-pill">{html.escape(date_label)} · {html.escape(meta["label"])}</span>'
            "</div>"
            f'<h2 class="story-title"><a href="{html.escape(local_url)}">{title}</a></h2>'
            f'<p class="story-summary">{deck}</p>'
            f'<p class="story-description">{description}</p>'
            '<div class="story-footer">'
            f'<span class="story-source">{html.escape("Source-backed" if ikg else "Editorial")}</span>'
            f'<a class="story-link" href="{html.escape(local_url)}">Open article</a>'
            "</div>"
            "</div>"
            "</article>"
        )

    type_counts = {
        key: sum(1 for article in published if str(article.get("content_type") or "manual").strip().lower() == key)
        for key in type_meta
    }
    avg_quality = round(sum(_story_score(article) for article in published) / published_count) if published_count else 0
    filter_specs: list[tuple[str, str, int]] = [("all", "All", published_count)]
    for key in ("earnings", "company", "sebi", "trend", "manual"):
        count = type_counts.get(key, 0)
        if count:
            filter_specs.append((key, type_meta[key]["label"], count))
    if ikg_count:
        filter_specs.append(("ikg", "Source-backed", ikg_count))
    filter_buttons = "".join(
        f'<button class="filter-button{" is-active" if key == "all" else ""}" type="button" '
        f'data-filter-button data-filter="{html.escape(key)}">{html.escape(label)}<span>{count}</span></button>'
        for key, label, count in filter_specs
    )

    if published:
        stories_html = "\n".join(
            _story_card(article, featured=(index == 0))
            for index, article in enumerate(published)
        )
    else:
        stories_html = (
            '<section class="empty-state" data-empty-state>'
            '<div class="empty-kicker">Editorial queue warming up</div>'
            '<h2>No public insights are live yet.</h2>'
            '<p>The archive will fill automatically as high-conviction stories clear review and publication checks.</p>'
            '<a class="story-link" href="/#/dashboard">Open Dashboard</a>'
            "</section>"
        )

    featured_image = f"{_SITE_URL}{_image_href(published[0])}" if published else f"{_SITE_URL}/prospektlab-logo.svg"
    schema = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "@id": f"{_SITE_URL}/#organization",
                    "name": "ProspektLab",
                    "url": f"{_SITE_URL}/",
                    "logo": {"@type": "ImageObject", "url": f"{_SITE_URL}/prospektlab-logo.svg"},
                },
                {
                    "@type": "CollectionPage",
                    "@id": f"{_SITE_URL}/insights/research/#page",
                    "name": "ProspektLab Research Hub - Indian Market Intelligence",
                    "description": (
                        "Editorial-style financial research pages covering earnings, regulation, "
                        "company intelligence, and market trends for India."
                    ),
                    "url": f"{_SITE_URL}/insights/research/",
                    "image": featured_image,
                    "publisher": {"@id": f"{_SITE_URL}/#organization"},
                    "mainEntity": {"@id": f"{_SITE_URL}/insights/research/#itemlist"},
                },
                {
                    "@type": "ItemList",
                    "@id": f"{_SITE_URL}/insights/research/#itemlist",
                    "numberOfItems": published_count,
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": index + 1,
                            "url": f"{_SITE_URL}/{route_base}/{article.get('slug')}/",
                            "name": article.get("title") or article.get("slug") or "Insight",
                        }
                        for index, article in enumerate(published[:24])
                    ],
                },
            ],
        },
        ensure_ascii=True,
    )

    def _read_mins(article: dict[str, Any]) -> str:
        wc = 0
        for field in ("body", "hero_summary", "description"):
            txt = str(article.get(field) or "")
            wc += len(txt.split())
        mins = max(2, round(wc / 200))
        return f"{mins} min read"

    def _article_live_symbol(article: dict[str, Any]) -> str:
        text = " ".join(
            str(article.get(field) or "")
            for field in ("title", "slug", "hero_title", "description", "hero_summary", "keywords")
        ).upper()
        padded = f" {text} "
        symbol_hints = (
            ("BRITANNIA", "BRITANNIA"),
            ("TATA CONSULTANCY", "TCS"),
            (" TCS ", "TCS"),
            ("INFOSYS", "INFY"),
            ("HDFC BANK", "HDFCBANK"),
            ("HDFC", "HDFCBANK"),
            ("ICICI", "ICICIBANK"),
            ("RELIANCE", "RELIANCE"),
            ("STATE BANK", "SBIN"),
            (" SBI ", "SBIN"),
            ("BHARTI", "BHARTIARTL"),
            ("AIRTEL", "BHARTIARTL"),
            ("ITC", "ITC"),
            ("LARSEN", "LT"),
            ("L&T", "LT"),
        )
        for hint, symbol in symbol_hints:
            if hint in padded:
                return symbol
        return ""

    def _story_card_v3(article: dict[str, Any], *, featured: bool = False, index: int = 0) -> str:
        slug = str(article.get("slug") or "").strip()
        title_raw = str(article.get("title") or slug or "Untitled insight")
        summary_raw = str(article.get("hero_summary") or article.get("description") or "").strip()
        content_type = str(article.get("content_type") or "manual").strip().lower() or "manual"
        meta = type_meta.get(content_type, type_meta["manual"])
        accent = meta["accent"]
        cat_label = meta["label"]
        local_url = f"/{route_base}/{slug}/" if slug else "#"
        date_label = _format_date(str(article.get("published_at") or article.get("generated_at") or ""))
        cover_href = html.escape(_image_href(article))
        title = html.escape(sanitize_public_text(title_raw))
        deck_raw = sanitize_public_text(summary_raw[:240] if featured else summary_raw[:160])
        deck = html.escape(deck_raw or "Publication-ready market research.")
        read_time = _read_mins(article)
        search_attr = html.escape(_search_blob(article), quote=True)
        ikg = bool(article.get("ikg_covered"))
        ikg_attr = "yes" if ikg else "no"
        live_symbol = _article_live_symbol(article)
        live_attr = f' data-live-symbol="{html.escape(live_symbol)}"' if live_symbol else ""
        live_quote = (
            f'<div class="story-live-mini" aria-label="Live market quote for {html.escape(live_symbol)}">'
            f'<span>{html.escape(live_symbol)}</span><strong data-live-price>Live quote</strong>'
            '<em data-live-move>...</em></div>'
            if live_symbol else ""
        )

        if featured:
            # Feature card — full width, horizontal layout with side panel.
            # The side panel is a static editorial "Briefing" built only from
            # metadata that is always present, so it never gets stuck waiting on
            # live market data (the old live-quote table had no styling and hung
            # on "Fetching..." for macro/sector stories with no linked symbol).
            ikg_badge = '<span class="feat-brief-tag">IKG-verified coverage</span>' if ikg else ''
            side_panel = (
                '<div class="feat-side">'
                '<span class="feat-side-label">Briefing</span>'
                '<div class="feat-brief-accent" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>'
                '<div class="feat-brief">'
                f'<div class="feat-brief-row"><span>Category</span><strong style="color:{html.escape(accent)}">{html.escape(cat_label)}</strong></div>'
                f'<div class="feat-brief-row"><span>Reading time</span><strong>{html.escape(read_time)}</strong></div>'
                f'<div class="feat-brief-row"><span>Published</span><strong>{html.escape(date_label)}</strong></div>'
                '</div>'
                f'{ikg_badge}'
                '</div>'
            )
            feat_row = (
                '<div class="feat-row">'
                '<div>'
                f'<div class="story-top"><span class="story-cat" style="color:{html.escape(accent)}">{html.escape(cat_label)}</span><span class="story-read">{html.escape(read_time)}</span></div>'
                f'<h2 class="story-title">{title}</h2>'
                f'<p class="story-dek">{deck}</p>'
                '<div class="story-foot">'
                f'<span class="story-date">{html.escape(date_label)}</span>'
                f'<span class="story-go">Read story <span class="arrow">&#x2192;</span></span>'
                '</div>'
                '</div>'
                + side_panel +
                '</div>'
            )
            return (
                f'<article class="story story--feature" data-story data-type="{html.escape(content_type)}" data-ikg="{ikg_attr}" data-search="{search_attr}"{live_attr}>'
                f'<a href="{html.escape(local_url)}" class="story-card" data-cursor>'
                f'<img class="feat-thumb" src="{cover_href}" alt="{title} cover" loading="lazy" />'
                + feat_row +
                '</a></article>'
            )
        else:
            # Standard card
            return (
                f'<article class="story" data-story data-type="{html.escape(content_type)}" data-ikg="{ikg_attr}" data-search="{search_attr}"{live_attr}>'
                f'<a href="{html.escape(local_url)}" class="story-card" data-cursor>'
                f'<img class="story-thumb" src="{cover_href}" alt="{title} cover" loading="lazy" />'
                f'<div class="story-top"><span class="story-cat" style="color:{html.escape(accent)}">{html.escape(cat_label)}</span><span class="story-read">{html.escape(read_time)}</span></div>'
                f'<h2 class="story-title">{title}</h2>'
                f'<p class="story-dek">{deck}</p>'
                f'{live_quote}'
                '<div class="story-foot">'
                f'<span class="story-date">{html.escape(date_label)}</span>'
                f'<span class="story-go">Read story <span class="arrow">&#x2192;</span></span>'
                '</div>'
                '</a></article>'
            )

    if published:
        stories_html_v3 = "\n".join(
            _story_card_v3(article, featured=(i == 0), index=i)
            for i, article in enumerate(published)
        )
    else:
        stories_html_v3 = (
            '<div id="archive-empty" style="grid-column:1/-1;text-align:center;padding:60px 20px;border:1px dashed rgba(255,255,255,0.12);border-radius:22px">'
            '<div class="eyebrow" style="justify-content:center;margin-bottom:16px"><span class="dot"></span> No stories yet</div>'
            '<h2 style="font-family:var(--serif);font-size:clamp(1.8rem,3vw,2.4rem);letter-spacing:-0.04em;margin-bottom:12px">The archive is warming up.</h2>'
            '<p style="color:var(--ink-2);max-width:46ch;margin:0 auto;line-height:1.65">High-conviction stories appear here as they clear editorial review and publish checks.</p>'
            '<a href="/" class="btn" style="margin-top:28px;display:inline-flex">Go to Dashboard <span class="arrow">&#x2192;</span></a>'
            '</div>'
        )

    latest_href = (
        f"/{route_base}/{published[0].get('slug', '')}/"
        if published and published[0].get("slug")
        else f"/{route_base}/research/"
    )

    return f"""<!doctype html>
<html lang="en-IN" data-page="hub">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ProspektLab Research Hub | Indian Market Intelligence</title>
  <meta name="description" content="Earnings, regulation, company moves, and sector shifts — published as clean, searchable research pages built for fast reading and repeat discovery." />
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1" />
  <meta name="theme-color" content="#03060d" />
  <link rel="canonical" href="{html.escape(_SITE_URL)}/insights/research/" />
  <link rel="icon" type="image/svg+xml" href="/prospektlab-favicon-v2.svg" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="ProspektLab" />
  <meta property="og:title" content="ProspektLab Research Hub | Indian Market Intelligence" />
  <meta property="og:description" content="A public archive of editorial-style research pages for Indian market participants." />
  <meta property="og:url" content="{html.escape(_SITE_URL)}/insights/research/" />
  <meta property="og:image" content="{html.escape(featured_image)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400..600;1,6..72,400..560&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
  <script type="application/ld+json">{schema}</script>
  <style>
{_HUB_EDITORIAL_CSS}
  </style>
  <script>
    /* Reveal-state opt-in: opt INTO the hidden state only if motion is allowed
       AND the page is being viewed by a real user. A safety timer guarantees
       all data-reveal elements become visible within 800 ms even if any later
       JS errors out — the page is never stuck blank. */
    (function () {{
      var html = document.documentElement;
      var ok = !window.matchMedia || !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (ok) html.classList.add('pre-reveal');
      // Hard safety: force-reveal everything no matter what after 800 ms.
      setTimeout(function () {{
        var nodes = document.querySelectorAll('[data-reveal], [data-reveal-stagger]');
        for (var i = 0; i < nodes.length; i++) nodes[i].classList.add('in');
      }}, 800);
    }})();
  </script>
</head>
<body>

<!-- Ticker -->
<div class="ticker" aria-hidden="true">
  <div class="ticker-track" id="ticker-track"></div>
</div>

<!-- Header -->
<header class="site-head">
  <div class="wrap head-inner">
    <a class="brand" href="/{html.escape(route_base)}/research/" aria-label="ProspektLab Research home">
      <span class="mk-dot"></span>
      <span class="mk-name">ProspektLab</span>
      <span class="mk-sub">Research</span>
    </a>
    <nav class="nav" aria-label="Primary">
      <a href="/{html.escape(route_base)}/research/" class="is-current">Dashboard</a>
      <a href="#contact">Contact</a>
      <span class="magnetic nav-cta" data-mag="0.35"><a href="#archive" class="btn btn--sm">Open Archive <span class="arrow">&#x2192;</span></a></span>
    </nav>
    <button class="burger" id="burger-btn" aria-label="Menu" aria-expanded="false">
      <span></span><span></span><span></span>
    </button>
  </div>
</header>

<!-- Mobile nav -->
<div class="m-nav" id="m-nav">
  <a href="/{html.escape(route_base)}/research/"><span class="n-num">01</span>Dashboard</a>
  <a href="#archive"><span class="n-num">02</span>Archive</a>
  <a href="#contact"><span class="n-num">03</span>Contact</a>
</div>

<main>
  <!-- HERO -->
  <section class="section hero">
    <div class="wrap hero-grid">
      <div class="hero-head" data-reveal>
        <span class="eyebrow"><span class="dot"></span> Public Research</span>
        <h1 class="display">Indian market stories with the <span class="it">context</span> serious readers actually need.</h1>
        <p class="lede hero-lede">Earnings, regulation, company moves, and sector shifts are published here as clean, searchable pages built for fast reading, deeper context, and repeat discovery.</p>
        <div class="hero-actions">
          <span class="magnetic" data-mag="0.3"><a href="#archive" class="btn">Browse the archive <span class="arrow">&#x2192;</span></a></span>
          <span class="magnetic" data-mag="0.3"><a href="{html.escape(latest_href)}" class="btn btn--ghost">Read latest story</a></span>
        </div>
      </div>
      <aside class="snap" data-reveal>
        <div class="snap-head">
          <span class="eyebrow" style="font-size:.62rem">Market Snapshot</span>
          <span class="snap-live"><span class="pulse"></span> Live</span>
        </div>
        <div class="idx-row">
          <div class="idx-meta"><div class="idx-name">NIFTY 50</div><div class="idx-sub">NSE &middot; INDEX</div></div>
          <canvas class="idx-spark" data-spark="100,101,99,102,103,101,104,106,105,108" data-dir="up" id="spark-nifty50"></canvas>
          <div class="idx-val"><div class="idx-px" id="px-nifty50" data-count="24218.45" data-dec="2">24,218.45</div><div class="idx-chg up" id="chg-nifty50">+0.94%</div></div>
        </div>
        <div class="idx-row">
          <div class="idx-meta"><div class="idx-name">SENSEX</div><div class="idx-sub">BSE &middot; INDEX</div></div>
          <canvas class="idx-spark" data-spark="100,100.5,101,100.2,101.5,102,101.8,103,102.6,103.4" data-dir="up" id="spark-sensex"></canvas>
          <div class="idx-val"><div class="idx-px" id="px-sensex" data-count="79476.19" data-dec="2">79,476.19</div><div class="idx-chg up" id="chg-sensex">+0.81%</div></div>
        </div>
        <div class="idx-row">
          <div class="idx-meta"><div class="idx-name">BANK NIFTY</div><div class="idx-sub">NSE &middot; INDEX</div></div>
          <canvas class="idx-spark" data-spark="100,99,98.5,99.2,98,97.4,98.1,97,96.4,96.8" data-dir="down" id="spark-banknifty"></canvas>
          <div class="idx-val"><div class="idx-px" id="px-banknifty" data-count="52104.30" data-dec="2">52,104.30</div><div class="idx-chg down" id="chg-banknifty">&#x2212;0.37%</div></div>
        </div>
        <div class="idx-row">
          <div class="idx-meta"><div class="idx-name">INR / USD</div><div class="idx-sub">FX &middot; SPOT</div></div>
          <canvas class="idx-spark" data-spark="100,100.1,100.05,100.2,100.3,100.25,100.4,100.5,100.45,100.6" data-dir="up" id="spark-inrusd"></canvas>
          <div class="idx-val"><div class="idx-px" id="px-inrusd" data-count="83.42" data-dec="2">83.42</div><div class="idx-chg up" id="chg-inrusd">+0.06%</div></div>
        </div>
      </aside>
    </div>
  </section>

  <hr class="divider wrap" style="background:transparent" />

  <!-- PUBLISHING MODEL -->
  <section class="section pubmodel">
    <div class="wrap pubmodel-grid">
      <div data-reveal>
        <span class="eyebrow"><span class="dot"></span> Publishing Model</span>
        <h2 class="h2" style="margin-top:.5em; max-width:14ch;">Built for search, reading, and <span class="serif-it">trust</span>.</h2>
      </div>
      <div data-reveal>
        <p class="lede">Each article lives at a direct route, carries search metadata, and keeps the focus on the story rather than the workflow behind it.</p>
        <div class="chips-wrap">
          <span class="chip">Evidence-led reporting</span>
          <span class="chip">Continuous market watch</span>
          <span class="chip">Verified company context</span>
          <span class="chip">Compliance-safe language</span>
        </div>
      </div>
    </div>
  </section>

  <!-- LATEST RESEARCH -->
  <section id="archive" class="section archive-section">
    <div class="wrap">
      <div class="sec-head" data-reveal>
        <div>
          <span class="eyebrow"><span class="dot"></span> Latest Research</span>
          <h2 class="h2 sec-title" style="margin-top:.4em">Filter by topic, company, or coverage angle.</h2>
        </div>
        <span class="magnetic" data-mag="0.3"><a href="#archive" class="btn btn--ghost btn--sm">All research <span class="arrow">&#x2192;</span></a></span>
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:12px">
        <input type="search" id="archive-search" placeholder="Search company, theme, or keyword&hellip;" />
        <span id="story-count" style="font-family:var(--mono);font-size:0.72rem;color:var(--ink-3)">{published_count} stories</span>
      </div>
      <div class="filter-strip">{filter_buttons}</div>

      <div class="stories" style="margin-top:clamp(28px,3.5vw,48px)" data-reveal-stagger data-stagger="90">
        {stories_html_v3}
      </div>
      <div id="archive-empty" style="display:none;text-align:center;padding:60px 20px;border:1px dashed var(--line);border-radius:var(--radius-lg);margin-top:24px">
        <div class="eyebrow" style="justify-content:center;margin-bottom:14px"><span class="dot"></span>No matches</div>
        <h2 style="font-family:var(--serif);font-size:clamp(1.6rem,2.5vw,2.2rem);letter-spacing:-0.04em">No stories match that filter.</h2>
        <p style="color:var(--ink-2);max-width:44ch;margin:12px auto;font-size:0.98rem;line-height:1.65">Try a different keyword or reset the filter to see all published research.</p>
      </div>
    </div>
  </section>

  <!-- PRINCIPLES -->
  <section class="section principles" style="background:var(--paper-2); border-top:1px solid var(--line); border-bottom:1px solid var(--line)">
    <div class="wrap">
      <div class="sec-head" data-reveal>
        <span class="eyebrow"><span class="dot"></span> Editorial Standards</span>
        <span class="sec-num">How pages are built</span>
      </div>
      <div class="principle-grid" data-reveal-stagger data-stagger="110">
        <div class="principle">
          <span class="p-num">01 &mdash; Evidence first</span>
          <h3>Primary-source bias is deliberate.</h3>
          <p>Official filings, exchange disclosures, company material, and transcripts outrank generic summaries. The archive is designed to make that discipline easy to spot.</p>
        </div>
        <div class="principle">
          <span class="p-num">02 &mdash; Context where useful</span>
          <h3>Company context appears only when it adds real depth.</h3>
          <p>Ownership, governance, and filing context should sharpen the story, not decorate it. Thin coverage should stay clearly disclosed.</p>
        </div>
        <div class="principle">
          <span class="p-num">03 &mdash; Editorial finish</span>
          <h3>The output should feel publishable on first open.</h3>
          <p>Sharper typography, calmer hierarchy, and clearer routes make the archive feel closer to a financial publication than a content dump.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- CONTACT -->
  <section class="section contact" id="contact">
    <div class="wrap">
      <div class="contact-card" data-reveal>
        <div>
          <span class="eyebrow"><span class="dot"></span> Contact</span>
          <h2>Research pages should feel deliberate and trustworthy.</h2>
          <p class="c-lede">Have a correction, a filing we should cover, or a partnership question? Reach the desk directly &mdash; we read everything.</p>
          <div class="c-details">
            <div class="c-detail"><div class="cd-k">Editorial desk</div><div class="cd-v">desk@prospektlab.in</div></div>
            <div class="c-detail"><div class="cd-k">Corrections</div><div class="cd-v">corrections@prospektlab.in</div></div>
            <div class="c-detail"><div class="cd-k">Location</div><div class="cd-v">Mumbai &middot; Bengaluru</div></div>
          </div>
        </div>
        <form class="contact-form" onsubmit="event.preventDefault();this.reset();this.querySelector('.btn').textContent='Sent \u2014 thank you';">
          <div class="field"><label>Name</label><input type="text" placeholder="Your name" required /></div>
          <div class="field"><label>Email</label><input type="email" placeholder="you@firm.com" required /></div>
          <div class="field"><label>Message</label><textarea placeholder="What should we look into?" required></textarea></div>
          <button type="submit" class="btn btn--accent">Send message <span class="arrow">&#x2192;</span></button>
        </form>
      </div>
    </div>
  </section>
</main>

<!-- FOOTER -->
<footer class="foot">
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <a class="brand" href="/{html.escape(route_base)}/research/"><span class="mk-dot"></span><span class="mk-name">ProspektLab</span><span class="mk-sub">Research</span></a>
        <p class="foot-disc" style="margin-top:18px; max-width:42ch">Educational content only. No buy, sell, hold, or target-price language is published here. Research pages are informational and not investment advice.</p>
      </div>
      <div class="foot-col">
        <h4>Platform</h4>
        <ul>
          <li><a href="/{html.escape(route_base)}/research/">Dashboard</a></li>
          <li><a href="#archive">Research Archive</a></li>
          <li><a href="#contact">Contact</a></li>
        </ul>
      </div>
      <div class="foot-col">
        <h4>Coverage</h4>
        <ul>
          <li><a href="#archive">SEBI &amp; Regulation</a></li>
          <li><a href="#archive">Earnings</a></li>
          <li><a href="#archive">Banking &amp; NBFC</a></li>
          <li><a href="#archive">Sectors</a></li>
        </ul>
      </div>
    </div>
    <div class="foot-base">
      <span>&copy; 2026 ProspektLab Research</span>
      <span>Built for fast reading, deeper context, repeat discovery.</span>
    </div>
  </div>
</footer>

<script>
/* ─── ProspektLab Hub — interactions + live data ─── */
(function(){{
  "use strict";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── Sticky header ── */
  var head = document.querySelector(".site-head");
  function onScroll(){{ if(head) head.classList.toggle("is-stuck", window.scrollY > 8); }}
  window.addEventListener("scroll", onScroll, {{passive:true}});
  onScroll();

  /* ── Mobile burger ── */
  var burger = document.getElementById("burger-btn");
  var mnav = document.getElementById("m-nav");
  if(burger && mnav){{
    burger.addEventListener("click", function(){{
      var open = mnav.classList.toggle("is-open");
      burger.classList.toggle("is-open", open);
      burger.setAttribute("aria-expanded", open ? "true" : "false");
      document.body.style.overflow = open ? "hidden" : "";
    }});
    mnav.querySelectorAll("a").forEach(function(a){{
      a.addEventListener("click", function(){{
        mnav.classList.remove("is-open");
        burger.classList.remove("is-open");
        document.body.style.overflow = "";
      }});
    }});
  }}

  /* ── Visibility engine ── */
  var watchers = [];
  function watch(el, cb, ratio){{ watchers.push({{el:el, cb:cb, off:ratio==null?0.88:ratio, done:false}}); }}
  function inView(el, ratio){{
    var r = el.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    if(r.height===0 && r.width===0) return false;
    return r.top < vh * ratio && r.bottom > -40;
  }}
  var ticking = false;
  function checkWatchers(){{
    ticking = false;
    for(var i=0;i<watchers.length;i++){{
      var w=watchers[i]; if(w.done) continue;
      if(inView(w.el, w.off)){{ w.done=true; w.cb(w.el); }}
    }}
  }}
  function onWatchScroll(){{ if(!ticking){{ ticking=true; requestAnimationFrame(checkWatchers); setTimeout(checkWatchers,60); }} }}
  window.addEventListener("scroll", onWatchScroll, {{passive:true}});
  window.addEventListener("resize", onWatchScroll, {{passive:true}});
  if (document.readyState === "complete") {{ onWatchScroll(); }}
  else {{ window.addEventListener("load", onWatchScroll); }}

  /* ── Scroll reveal ── */
  function finalizeReveal(el){{
    el.style.transition="none"; el.style.opacity="1"; el.style.transform="none";
    if(el.hasAttribute("data-reveal-stagger")){{
      for(var i=0;i<el.children.length;i++){{
        var c=el.children[i]; c.style.transition="none"; c.style.opacity="1"; c.style.transform="none";
      }}
    }}
  }}
  document.querySelectorAll("[data-reveal], [data-reveal-stagger]").forEach(function(el){{
    if(reduce){{ el.classList.add("in"); finalizeReveal(el); return; }}
    watch(el, function(t){{
      if(t.hasAttribute("data-reveal-stagger")){{
        var kids=t.children, base=parseFloat(t.getAttribute("data-stagger"))||80;
        for(var i=0;i<kids.length;i++) kids[i].style.transitionDelay=(i*base)+"ms";
      }}
      t.classList.add("in");
      var delay=t.hasAttribute("data-reveal-stagger")?1100+t.children.length*90:1050;
      setTimeout(function(){{ finalizeReveal(t); }}, delay);
    }});
  }});

  /* ── Animated counters ── */
  function fmtNum(n, dec, prefix, suffix){{
    var s = n.toLocaleString("en-IN", {{minimumFractionDigits:dec, maximumFractionDigits:dec}});
    return prefix + s + suffix;
  }}
  function animateCount(el){{
    if (el.getAttribute("data-count") === null) return;
    var target = parseFloat(el.getAttribute("data-count"));
    var dec = parseInt(el.getAttribute("data-dec")||"0", 10);
    var prefix = el.getAttribute("data-prefix")||"";
    var suffix = el.getAttribute(\"data-suffix\")||\"\";\r\n    var from = el._lastValue || 0;\r\n    var dur = 1300, start = null;
    if(el._countRAF){{ cancelAnimationFrame(el._countRAF); el._countRAF = null; }}\r\n    if(el._countTimer){{ clearTimeout(el._countTimer); el._countTimer = null; }}\r\n    el._countTimer = setTimeout(function(){{ el.textContent = fmtNum(target,dec,prefix,suffix); el._countTimer = null; }}, 1450);
    if(reduce){{ el.textContent = fmtNum(target,dec,prefix,suffix); return; }}
    function step(ts){{
      if(!start) start=ts;
      var p = Math.min((ts-start)/dur, 1);
      var eased = 1-Math.pow(1-p,3);
      el.textContent = fmtNum(from + (target-from)*eased, dec, prefix, suffix);
      if(p<1){{ el._countRAF = requestAnimationFrame(step); }}
      else {{ el._countRAF = null; el._lastValue = target; }}\r\n    }}\r\n    el._countRAF = requestAnimationFrame(step);
  }}
  document.querySelectorAll("[data-count]").forEach(function(el){{ watch(el, animateCount, 0.97); }});

  /* ── Sparklines ── */
  function drawSpark(canvas, animate){{
    var raw = canvas.getAttribute("data-spark"); if(!raw) return;
    var pts = raw.split(",").map(parseFloat);
    var up = canvas.getAttribute("data-dir") !== "down";
    var color = up ? "#34D399" : "#FB7185";
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = rect.width || 96, h = rect.height || 34;
    canvas.width = Math.round(w*dpr); canvas.height = Math.round(h*dpr);
    var ctx = canvas.getContext("2d"); ctx.scale(dpr,dpr);
    var mn=Math.min.apply(null,pts), mx=Math.max.apply(null,pts), rng=mx-mn||1, pad=3;
    function x(i){{ return pad+(i/(pts.length-1))*(w-pad*2); }}
    function y(v){{ return h-pad-((v-mn)/rng)*(h-pad*2); }}
    function render(prog){{
      ctx.clearRect(0,0,w,h);
      var n = Math.max(2, Math.round(pts.length*prog));
      var grad = ctx.createLinearGradient(0,0,0,h);
      grad.addColorStop(0, color+"33"); grad.addColorStop(1, color+"00");
      ctx.beginPath(); ctx.moveTo(x(0),y(pts[0]));
      for(var i=1;i<n;i++) ctx.lineTo(x(i),y(pts[i]));
      ctx.lineTo(x(n-1),h); ctx.lineTo(x(0),h); ctx.closePath();
      ctx.fillStyle=grad; ctx.fill();
      ctx.beginPath(); ctx.moveTo(x(0),y(pts[0]));
      for(var j=1;j<n;j++) ctx.lineTo(x(j),y(pts[j]));
      ctx.strokeStyle=color; ctx.lineWidth=1.6; ctx.lineJoin="round"; ctx.lineCap="round"; ctx.stroke();
      ctx.beginPath(); ctx.arc(x(n-1),y(pts[n-1]),2.2,0,Math.PI*2); ctx.fillStyle=color; ctx.fill();
    }}
    render(reduce||!animate ? 1 : 0.001);
    if(reduce||!animate) return;
    var stt=null, dur=850, raf;
    function stepFn(ts){{ if(!stt) stt=ts; var p=Math.min((ts-stt)/dur,1); render(1-Math.pow(1-p,2)); if(p<1) raf=requestAnimationFrame(stepFn); }}
    raf = requestAnimationFrame(stepFn);
    setTimeout(function(){{ if(raf) cancelAnimationFrame(raf); render(1); }}, 950);
  }}
  var sparkEls = document.querySelectorAll("[data-spark]");
  sparkEls.forEach(function(c){{ watch(c, function(t){{ drawSpark(t,true); }}, 0.97); }});
  function redrawSparks(){{ sparkEls.forEach(function(c){{ drawSpark(c,false); }}); }}
  window.addEventListener("resize", function(){{ clearTimeout(window._sparkTimer); window._sparkTimer = setTimeout(redrawSparks,200); }});

  /* ── Custom cursor ── */
  if(!window.matchMedia("(pointer: coarse)").matches){{
    var dot=document.createElement("div"); dot.className="cursor-dot";
    var ring=document.createElement("div"); ring.className="cursor-ring";
    document.body.appendChild(dot); document.body.appendChild(ring);
    var mx=0,my=0,rx=0,ry=0;
    document.addEventListener("mousemove", function(e){{
      mx=e.clientX; my=e.clientY;
      dot.style.transform="translate("+mx+"px,"+my+"px) translate(-50%,-50%)";
    }});
    (function loop(){{ rx+=(mx-rx)*0.18; ry+=(my-ry)*0.18; ring.style.transform="translate("+rx+"px,"+ry+"px) translate(-50%,-50%)"; requestAnimationFrame(loop); }})();
    document.querySelectorAll("a,button,.chip,.story-card,[data-cursor]").forEach(function(el){{
      el.addEventListener("mouseenter",function(){{ring.classList.add("is-hover");}});
      el.addEventListener("mouseleave",function(){{ring.classList.remove("is-hover");}});
    }});
  }}

  /* ── Magnetic buttons ── */
  if(!reduce && !window.matchMedia("(pointer: coarse)").matches){{
    document.querySelectorAll(".magnetic").forEach(function(el){{
      var str = parseFloat(el.getAttribute("data-mag"))||0.3;
      el.addEventListener("mousemove",function(e){{
        var r=el.getBoundingClientRect();
        var mx2=e.clientX-(r.left+r.width/2), my2=e.clientY-(r.top+r.height/2);
        el.style.transform="translate("+mx2*str+"px,"+my2*str+"px)";
        var inn=el.firstElementChild; if(inn) inn.style.transform="translate("+mx2*str*0.5+"px,"+my2*str*0.5+"px)";
      }});
      el.addEventListener("mouseleave",function(){{
        el.style.transform=""; var inn=el.firstElementChild; if(inn) inn.style.transform="";
      }});
    }});
  }}

  /* ── Ticker + Live quotes ── */
  function buildTickerHtml(data){{
    return data.map(function(d){{
      return '<span class="tk"><span class="sym">'+d[0]+'</span><span class="px">'+d[1]+'</span><span class="chg '+d[3]+'"><span class="tri">'+(d[3]==="up"?"&#x25B2;":"&#x25BC;")+'</span>'+d[2]+'</span></span>';
    }}).join("");
  }}
  var tt = document.getElementById("ticker-track");
  if(tt){{ tt.innerHTML='<span class="tk"><span class="sym">LIVE MARKET DATA</span><span class="px">Loading...</span></span>'; }}

  /* ── Archive filter + search ── */
  window.__plArchive = true;
  (function(){{
    var search = document.getElementById("archive-search");
    var chips = document.querySelectorAll("[data-filter]");
    var items = document.querySelectorAll("[data-story]");
    var countEl = document.getElementById("story-count");
    var empty = document.getElementById("archive-empty");
    var active = "all", q = "";
    function apply(){{
      var n=0;
      items.forEach(function(it){{
        var type = it.getAttribute("data-type")||"";
        var ikg = it.getAttribute("data-ikg")||"no";
        var text = (it.getAttribute("data-search")||"").toLowerCase();
        var mf = active==="all" ? true : active==="ikg" ? ikg==="yes" : type===active;
        var ms = !q || text.indexOf(q)>-1;
        it.style.display = (mf&&ms) ? "" : "none";
        if(mf&&ms) n++;
      }});
      if(countEl) countEl.textContent = n+" "+(n===1?"story":"stories");
      if(empty) empty.style.display = (items.length>0&&n===0)?"block":"none";
    }}
    if(search) search.addEventListener("input", function(){{ q=search.value.toLowerCase().trim(); apply(); }});
    chips.forEach(function(c){{
      c.addEventListener("click", function(){{
        chips.forEach(function(x){{x.classList.remove("is-active");}});
        c.classList.add("is-active");
        active = c.getAttribute("data-filter");
        apply();
      }});
    }});
    apply();
  }})();

  /* ── Init ── */
  checkWatchers();
  setTimeout(checkWatchers, 120);
  setTimeout(checkWatchers, 600);
}})();

/* ─────────────────────────────────────────────────────────────────────────
   LIVE MARKET DATA — hydrates the marquee ticker + Snapshot grid from
   /public/market/ticker. Re-polls every 60 s. Graceful fallback to the
   server-rendered placeholders if the endpoint is unreachable.
   ───────────────────────────────────────────────────────────────────────── */
(function () {{
  var DARK_UP = "#34D399", DARK_DOWN = "#FB7185", ACCENT = "#60A5FA";

  function drawSparkFromPoints(canvas, pts, isUp) {{
    if (!pts || pts.length < 2) return;
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = rect.width || 140, h = rect.height || 30;
    canvas.width = w * dpr; canvas.height = h * dpr;
    var ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
    var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
    var range = (max - min) || 1, pad = 2;
    var color = isUp ? DARK_UP : DARK_DOWN;
    function x(i) {{ return pad + (i / (pts.length - 1)) * (w - pad * 2); }}
    function y(v) {{ return h - pad - ((v - min) / range) * (h - pad * 2); }}
    var grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, color + "33"); grad.addColorStop(1, color + "00");
    ctx.beginPath(); ctx.moveTo(x(0), y(pts[0]));
    for (var i = 1; i < pts.length; i++) ctx.lineTo(x(i), y(pts[i]));
    ctx.lineTo(x(pts.length - 1), h); ctx.lineTo(x(0), h); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); ctx.moveTo(x(0), y(pts[0]));
    for (var j = 1; j < pts.length; j++) ctx.lineTo(x(j), y(pts[j]));
    ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.stroke();
    ctx.beginPath(); ctx.arc(x(pts.length - 1), y(pts[pts.length - 1]), 2.2, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill();
  }}

  function fmtChg(item) {{
    var n = Number(item.changePct);
    if (!isFinite(n)) return item.change || "—";
    var sign = n > 0 ? "+" : (n < 0 ? "" : "");
    return sign + n.toFixed(2) + "%";
  }}

  function renderTicker(items) {{
    var track = document.getElementById("ticker-track");
    if (!track) return;
    var rows = items.map(function (it) {{
      var up = Number(it.changePct) >= 0;
      var cls = up ? "up" : "down";
      var pct = Math.abs(Number(it.changePct) || 0).toFixed(2);
      var arrow = up ? '&#x25B2;' : '&#x25BC;';
      var sign = up ? '+' : '&#x2212;';
      return '<span class="tk"><span class="sym">' + esc(it.symbol) + '</span>' +
             '<span class="px">' + esc(it.value) + '</span>' +
             '<span class="chg ' + cls + '"><span class="tri">' + arrow + '</span>' + sign + pct + '%</span></span>';
    }}).join("");
    // duplicate sequence so the CSS animation loops without visible seam
    track.innerHTML = rows + rows;
    var count = Math.max(1, items.length);
    var seconds = Math.max(14, Math.min(28, count * 2));
    track.style.animationDuration = seconds + "s";
  }}

  function renderSnapshot(items) {{
    var grid = document.getElementById("snap-grid");
    if (!grid) return;
    var html = items.map(function (it, idx) {{
      var up = Number(it.changePct) >= 0;
      var cls = up ? "up" : "down";
      var pct = Math.abs(Number(it.changePct) || 0).toFixed(2);
      var arrow = up ? "▲" : "▼";
      return '<div class="snap-card" data-idx="' + idx + '">' +
        '<div class="sc-name">' + esc(it.symbol) + '</div>' +
        '<canvas class="sc-spark" aria-hidden="true"></canvas>' +
        '<div class="sc-row"><span class="sc-val">' + esc(it.value) + '</span>' +
        '<span class="sc-chg ' + cls + '">' + arrow + ' ' + (up ? "+" : "−") + pct + '%</span></div>' +
        '</div>';
    }}).join("");
    grid.innerHTML = html;
    // draw sparklines after layout
    items.forEach(function (it, idx) {{
      var card = grid.querySelector('[data-idx="' + idx + '"]');
      if (!card) return;
      var canvas = card.querySelector(".sc-spark");
      var pts = Array.isArray(it.sparkData) ? it.sparkData.filter(function (v) {{ return typeof v === "number" && isFinite(v); }}) : [];
      if (pts.length >= 2) drawSparkFromPoints(canvas, pts, Number(it.changePct) >= 0);
    }});
  }}

  function applyLiveToHero(items) {{
    var HERO = {{
      "NIFTY 50": {{ px: "px-nifty50", chg: "chg-nifty50", kind: "idx" }},
      "SENSEX": {{ px: "px-sensex", chg: "chg-sensex", kind: "idx" }},
      "NIFTY BANK": {{ px: "px-banknifty", chg: "chg-banknifty", kind: "idx" }},
      "USD/INR": {{ px: "px-inrusd", chg: "chg-inrusd", kind: "idx" }},
      "NIFTY IT": {{ px: "mb-niftyit", chg: "mbchg-niftyit", kind: "mb" }},
      "NIFTY AUTO": {{ px: "mb-niftyauto", chg: "mbchg-niftyauto", kind: "mb" }},
      "NIFTY FMCG": {{ px: "mb-niftyfmcg", chg: "mbchg-niftyfmcg", kind: "mb" }},
      "CRUDE OIL": {{ px: "mb-crude", chg: "mbchg-crude", kind: "mb" }},
      "GOLD": {{ px: "mb-gold", chg: "mbchg-gold", kind: "mb" }},
      "INDIA 10Y": {{ px: "mb-in10y", chg: "mbchg-in10y", kind: "mb" }}
    }};

    var HERO_ALIASES = {{
      "BANK NIFTY": "NIFTY BANK",
      "NIFTYBANK": "NIFTY BANK",
      "USDINR": "USD/INR",
      "USD INR": "USD/INR",
      "GOLD (10G)": "GOLD",
      "CRUDE": "CRUDE OIL",
      "CRUDE (WTI)": "CRUDE OIL",
      "INDIA 10Y YIELD": "INDIA 10Y"
    }};

    function updateChange(el, up, pct, kind) {{
      if (!el) return;
      var abs = Math.abs(pct || 0).toFixed(2);
      el.className = (kind === "mb" ? "mb-chg " : "idx-chg ") + (up ? "up" : "down");
      el.textContent = kind === "mb"
        ? (up ? "▲ +" : "▼ −") + abs + "%"
        : (up ? "+" : "−") + abs + "%";
    }}

    items.forEach(function (it) {{
      var sym = String(it.symbol || "").toUpperCase();
      var map = HERO[sym] || HERO[HERO_ALIASES[sym] || ""];
      if (!map) return;
      var pxEl = document.getElementById(map.px);
      var chgEl = document.getElementById(map.chg);
      if (!pxEl) return;
      var up = Number(it.changePct) >= 0;
      var pct = Number(it.changePct) || 0;
      if (pxEl._countTimer) {{ clearTimeout(pxEl._countTimer); pxEl._countTimer = null; }}
      if (pxEl._countRAF) {{ cancelAnimationFrame(pxEl._countRAF); pxEl._countRAF = null; }}
      var dec = parseInt(pxEl.getAttribute("data-dec") || "0", 10);
      var prefix = pxEl.getAttribute("data-prefix") || "";
      var suffix = pxEl.getAttribute("data-suffix") || "";
      var rawVal = String(it.value || "").replace(/[^0-9.\-]/g, "");
      var numVal = parseFloat(rawVal);
      if (isFinite(numVal)) {{ var oldVal = pxEl._lastValue || parseFloat(String(pxEl.textContent).replace(/[^0-9.\-]/g, "")) || 0; pxEl.setAttribute("data-count", numVal); pxEl._lastValue = oldVal; if (inView(pxEl, 0.97)) {{ animateCount(pxEl); }} else {{ pxEl.textContent = fmtNum(numVal, dec, prefix, suffix); pxEl._lastValue = numVal; }} }} else {{ pxEl.textContent = it.value; pxEl.removeAttribute("data-count"); }}
      updateChange(chgEl, up, pct, map.kind);
      var card = pxEl.closest ? (pxEl.closest(".idx-row") || pxEl.closest(".mb-card")) : null;
      if (card && Array.isArray(it.sparkData) && it.sparkData.length >= 2) {{
        var canvas = card.querySelector("canvas[data-spark]");
        if (canvas) {{
          canvas.setAttribute("data-spark", it.sparkData.join(","));
          canvas.setAttribute("data-dir", up ? "up" : "down");
        }}
      }}
    }});
  }}

  function applyLiveToStoryCards(items) {{
    var bySymbol = {{}};
    var byNorm = {{}};
    function normSymbol(v) {{ return String(v || "").toUpperCase().replace(/[^A-Z0-9]/g, ""); }}
    items.forEach(function (it) {{
      if (!(it && it.symbol)) return;
      var raw = String(it.symbol).toUpperCase();
      bySymbol[raw] = it;
      byNorm[normSymbol(raw)] = it;
    }});
    document.querySelectorAll("[data-live-symbol]").forEach(function (card) {{
      var sym = String(card.getAttribute("data-live-symbol") || "").toUpperCase();
      var it = bySymbol[sym] || byNorm[normSymbol(sym)];
      if (!it) {{
        card.querySelectorAll("[data-live-price]").forEach(function (el) {{ el.textContent = "Live unavailable"; }});
        card.querySelectorAll("[data-live-marketcap]").forEach(function (el) {{ el.textContent = "Not available"; }});
        card.querySelectorAll("[data-live-move]").forEach(function (el) {{
          el.textContent = "?";
          el.classList.remove("up");
          el.classList.remove("down");
        }});
        card.querySelectorAll(".story-live-spark").forEach(function (canvas) {{
          var ctx = canvas.getContext && canvas.getContext("2d");
          if (ctx) ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0);
        }});
        return;
      }}
      var up = Number(it.changePct) >= 0;
      var move = fmtChg(it);
      card.querySelectorAll("[data-live-price]").forEach(function (el) {{
        el.textContent = it.value || "Unavailable";
      }});
      card.querySelectorAll("[data-live-marketcap]").forEach(function (el) {{
        el.textContent = it.marketCap || "Not available";
      }});
      card.querySelectorAll("[data-live-move]").forEach(function (el) {{
        el.textContent = move;
        el.classList.toggle("up", up);
        el.classList.toggle("down", !up);
      }});
      card.querySelectorAll(".story-live-spark").forEach(function (canvas) {{
        var pts = Array.isArray(it.sparkData)
          ? it.sparkData.filter(function (v) {{ return typeof v === "number" && isFinite(v); }})
          : [];
        if (pts.length >= 2) drawSparkFromPoints(canvas, pts, up);
      }});
    }});
  }}

  function esc(s) {{
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {{
      return {{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}}[c];
    }});
  }}

  var marketRefreshBusy = false;

  function refresh() {{
    if (marketRefreshBusy) return;
    marketRefreshBusy = true;

    var controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var timeout = setTimeout(function () {{ if (controller) controller.abort(); }}, 12000);

    fetch("/public/market/ticker", {{ credentials: "omit", signal: controller ? controller.signal : undefined }})
      .then(function (r) {{ return r.ok ? r.json() : null; }})
      .then(function (data) {{
        if (!data || !Array.isArray(data.items) || data.items.length === 0) return;
        renderTicker(data.items);
        renderSnapshot(data.items);
        applyLiveToHero(data.items);
        applyLiveToStoryCards(data.items);
      }})
      .catch(function () {{
        var track = document.getElementById("ticker-track");
        if (track && !track.children.length) {{
          track.innerHTML = '<span class="tk"><span class="sym">LIVE MARKET DATA</span><span class="px">Unavailable</span></span>';
        }}
      }})
      .finally(function () {{
        clearTimeout(timeout);
        marketRefreshBusy = false;
      }});
  }}

  refresh();
  // poll every 60 s while the tab is visible
  var pollTimer = setInterval(function () {{
    if (document.visibilityState === "visible") refresh();
  }}, 60000);
  document.addEventListener("visibilitychange", function () {{
    if (document.visibilityState === "visible") refresh();
  }});
  // redraw on resize so sparkline canvases stay crisp
  var resizeTimer;
  window.addEventListener("resize", function () {{
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(refresh, 220);
  }});
}})();
</script>
</body>
</html>
"""
async def _build_ikg_context(target: str) -> dict[str, Any]:
    """
    Pull IKG structured data for the target entity. Degrades gracefully if
    the entity is not IKG-covered (e.g., trend/macro topics).
    """
    try:
        from finagent.ikg.service import get_ikg_service
    except Exception:
        return {}

    try:
        svc = get_ikg_service()
        bundle = await svc.build_company_bundle(identifier=target, depth="standard")
        entity = bundle.entity or {}
        cin = entity.get("cin")
        if not entity.get("resolved") or not cin:
            return {}

        ownership = bundle.ownership or {}
        governance = bundle.governance or {}
        risk = bundle.risk or {}
        documents = bundle.documents or {}
        coverage = bundle.coverage or {}
        company = bundle.company or {}

        ctx: dict[str, Any] = {
            "cin": cin,
            "covered": True,
            "company": company,
            "entity": entity,
            "coverage": coverage,
            "warnings": bundle.warnings or [],
            "ownership": ownership,
            "auditors": governance.get("auditors") or [],
            "related_party_transactions": risk.get("related_party_transactions") or [],
            "concall_transcripts": documents.get("concall_transcripts") or [],
            "enforcement_actions": risk.get("enforcement_actions") or [],
        }

        parts: list[str] = []
        entity_name = entity.get("name") or company.get("company_name") or target
        identity_bits = [f"IKG resolved {entity_name} to CIN {cin}"]
        if entity.get("isin"):
            identity_bits.append(f"ISIN {entity['isin']}")
        if entity.get("nse_symbol"):
            identity_bits.append(f"NSE symbol {entity['nse_symbol']}")
        parts.append(", ".join(identity_bits) + ".")

        promoters = ownership.get("promoters") or []
        promoter_chain = ownership.get("promoter_chain") or []
        pledge_summary = ownership.get("pledge_summary") or {}
        promoter_holding = float(pledge_summary.get("total_promoter_holding_pct") or 0.0)
        pledge_pct = float(pledge_summary.get("total_pledge_pct") or 0.0)
        owner_name = ""
        if promoter_chain:
            owner_name = str(promoter_chain[0].get("owner_name") or "").strip()
            promoter_holding = promoter_holding or float(promoter_chain[0].get("holding_pct") or 0.0)
        elif promoters:
            owner_name = str(promoters[0].get("owner_name") or "").strip()
            promoter_holding = promoter_holding or float(promoters[0].get("holding_pct") or 0.0)
        if promoter_holding > 0:
            owner_prefix = f"Promoter/major holder {owner_name}" if owner_name else "Promoter/major holder"
            parts.append(f"{owner_prefix} is visible in IKG at about {promoter_holding:.2f}% holding.")
            if pledge_pct > 0:
                parts.append(f"Promoter pledge visible in IKG at about {pledge_pct:.2f}% of holding.")

        auditors = governance.get("auditors") or []
        if auditors:
            latest = auditors[0]
            parts.append(
                f"Statutory auditor: {latest.get('auditor_name', 'N/A')} "
                f"(FY {latest.get('fiscal_year', 'N/A')})."
            )
            unique_auditors = {row.get("auditor_name") for row in auditors if row.get("auditor_name")}
            if len(unique_auditors) >= 2:
                parts.append(f"Auditor changed {len(unique_auditors) - 1} time(s) in {len(auditors)} years on record.")

        rpts = risk.get("related_party_transactions") or []
        if rpts:
            parts.append(f"Related-party coverage in IKG: {len(rpts)} fact(s).")

        enforcement = risk.get("enforcement_actions") or []
        if enforcement:
            parts.append(f"Regulatory or enforcement records in IKG: {len(enforcement)} item(s).")

        transcripts = documents.get("concall_transcripts") or []
        if transcripts:
            parts.append(f"Concall transcript coverage in IKG: {len(transcripts)} session(s).")

        sparse_layers = [
            name for name in ("ownership", "governance", "risk", "documents")
            if coverage.get(name) == "missing"
        ]
        if sparse_layers:
            parts.append(
                "IKG coverage is currently thin on "
                + ", ".join(sparse_layers)
                + " for this entity, so those angles should be cross-checked against primary filings."
            )

        ctx["narrative"] = " ".join(parts)
        return ctx

    except Exception:
        logger.exception("IKG context build failed for %r", target)
        return {}


# ── BUS helpers ───────────────────────────────────────────────────────────────

def _harvest_final_event(job_id: str) -> dict[str, Any]:
    """Scan BUS history for the 'final' event and return its payload."""
    for _idx, event in reversed(BUS.history(job_id, limit=5000)):
        if event.type == "final":
            return dict(event.payload)
    return {}


def _harvest_memo(job_id: str) -> str:
    """Try to harvest memo text from BUS final event or memo file."""
    final = _harvest_final_event(job_id)
    memo = (
        final.get("memo")
        or final.get("memo_preview")
        or final.get("answer")
        or final.get("text")
        or final.get("content")
        or ""
    )
    if not memo:
        try:
            from finagent.paths import finagent_data_path
            p = finagent_data_path("memos") / f"{job_id}.md"
            if p.is_file():
                memo = p.read_text(encoding="utf-8")
        except Exception:
            pass
    return memo


# ── Article assembly ──────────────────────────────────────────────────────────

def _split_memo_to_sections(memo: str) -> list[ContentArticleSection]:
    """Parse a markdown memo into ContentArticleSection list.

    Handles both ## (standard) and #### (news-brief) heading styles.
    """
    sections: list[ContentArticleSection] = []
    heading: str | None = None
    paragraphs: list[str] = []
    bullets: list[str] = []
    # Match ## and #### headings (news brief uses ####)
    _HEADING_RE = re.compile(r"^#{2,4}\s+(.+)")

    def _flush() -> None:
        if heading and (paragraphs or bullets):
            safe_paragraphs = list(paragraphs[:4])
            if not safe_paragraphs:
                if bullets:
                    safe_paragraphs = [bullets[0][:900]]
                else:
                    safe_paragraphs = [
                        "This section summarizes the filing-backed context captured in the research notes."
                    ]
            sections.append(ContentArticleSection(
                heading=heading[:140],
                paragraphs=safe_paragraphs,
                bullets=bullets[:6],
            ))

    for line in (memo or "").splitlines():
        s = line.strip()
        m = _HEADING_RE.match(s)
        if m:
            _flush()
            heading = m.group(1).strip()[:140]
            paragraphs = []
            bullets = []
        elif (s.startswith("- ") or s.startswith("* ")) and heading:
            text = s[2:].strip()
            if text and len(bullets) < 6:
                bullets.append(text[:300])
        elif s.startswith("|") and heading:
            # Table rows — treat each cell as a bullet for content
            pass
        elif s and heading and not s.startswith("#") and len(paragraphs) < 4:
            # Skip markdown table separators
            if not re.match(r"^\|[-| ]+\|$", s):
                paragraphs.append(s[:900])

    _flush()
    return sections[:10]


def _extract_faqs(memo: str) -> list[ContentArticleFaq]:
    """Extract FAQ Q&A pairs from memo text."""
    faqs: list[ContentArticleFaq] = []
    pattern = re.compile(
        r"(?:Q:|Question:|\*\*Q\*\*:?)?\s*([^\n]{8,180}\?)\s*\n+\s*(?:A:|Answer:|\*\*A\*\*:?)?\s*([^\n]{24,900})",
        re.IGNORECASE,
    )
    for m in pattern.finditer(memo or ""):
        q = m.group(1).strip()[:180]
        a = m.group(2).strip()[:900]
        if q and a:
            faqs.append(ContentArticleFaq(question=q, answer=a))
        if len(faqs) >= 6:
            break
    return faqs


_DEFAULT_FAQS = [
    ContentArticleFaq(
        question="Is this investment advice?",
        answer=(
            "No. This article is independent research for informational purposes only and does not "
            "constitute investment advice or a transaction recommendation for any security. "
            "Consult a SEBI-registered investment advisor before making investment decisions."
        ),
    ),
    ContentArticleFaq(
        question="Where does ProspektLab source its data?",
        answer=(
            "ProspektLab aggregates data from BSE, NSE, and SEBI official filings, XBRL financial "
            "reports, company press releases, and concall transcripts, then cross-checks material claims "
            "Knowledge Graph — a proprietary property graph covering listed Indian companies."
        ),
    ),
    ContentArticleFaq(
        question="How accurate is AI-generated financial analysis?",
        answer=(
            "ProspektLab's multi-pass pipeline cross-validates every claim across official filings, "
            "exchange announcements, and the IKG. Numbers are sourced from deterministic datasets "
            "(XBRL, BSE/NSE disclosures) — not generated by the model. Each article cites its "
            "sources and flags any estimate as such."
        ),
    ),
]

# Override default FAQ copy with clean public wording (no internal framework labels).
_DEFAULT_FAQS = [
    ContentArticleFaq(
        question="Is this investment advice?",
        answer=(
            "No. This article is independent research for informational purposes only and does not "
            "constitute investment advice or a transaction recommendation for any security. "
            "Consult a SEBI-registered investment advisor before making investment decisions."
        ),
    ),
    ContentArticleFaq(
        question="Where does ProspektLab source its data?",
        answer=(
            "ProspektLab aggregates data from BSE, NSE, and SEBI official filings, XBRL financial "
            "reports, company press releases, and concall transcripts, then cross-checks material claims "
            "against verified corporate records before publication."
        ),
    ),
    ContentArticleFaq(
        question="How accurate is AI-generated financial analysis?",
        answer=(
            "ProspektLab cross-validates every material claim across official filings and exchange "
            "announcements. Numbers are sourced from deterministic datasets (XBRL and BSE/NSE "
            "disclosures), and any estimate is explicitly labeled."
        ),
    ),
]


def _normalise_section_dicts(
    sections_raw: Any,
    *,
    target_display: str,
) -> list[dict[str, Any]]:
    """Coerce section payload to satisfy ContentArticleSection constraints."""
    sections: list[dict[str, Any]] = []
    for section in list(sections_raw or [])[:10]:
        if not isinstance(section, dict):
            continue
        heading = sanitize_public_text(str(section.get("heading") or "")).strip()[:140]
        if len(heading) < 3:
            continue
        paragraphs = [
            sanitize_public_text(str(paragraph)).strip()[:900]
            for paragraph in list(section.get("paragraphs") or [])[:4]
            if sanitize_public_text(str(paragraph)).strip()
        ]
        bullets = [
            sanitize_public_text(str(bullet)).strip()[:300]
            for bullet in list(section.get("bullets") or [])[:6]
            if sanitize_public_text(str(bullet)).strip()
        ]
        if not paragraphs:
            if bullets:
                paragraphs = [bullets[0]]
            else:
                paragraphs = [
                    f"This section consolidates source-backed context for {target_display} with a focus on material updates."
                ]
        if len(paragraphs) == 1:
            paragraphs.append(
                f"This analysis anchors each point to disclosed evidence and highlights what should be monitored next for {target_display}."
            )
        sections.append(
            {
                "heading": heading,
                "paragraphs": paragraphs,
                "bullets": bullets,
            }
        )
    return sections


def _coerce_article_payload(
    data: dict[str, Any],
    *,
    slug: str,
    target_display: str,
    label: str,
) -> dict[str, Any]:
    """Repair partial/malformed JSON-model output into schema-valid article payload."""
    payload = dict(data or {})
    payload["slug"] = slug
    payload["title"] = sanitize_public_text(str(payload.get("title") or f"{target_display} - {label}"))[:120]
    payload["description"] = sanitize_public_text(str(payload.get("description") or ""))[:220]
    if len(payload["description"]) < 80:
        payload["description"] = (
            f"In-depth {label.lower()} for {target_display}, with evidence-backed metrics, context, and watchpoints."
        )[:220]

    payload["hero_eyebrow"] = sanitize_public_text(str(payload.get("hero_eyebrow") or label))[:60]
    payload["hero_title"] = sanitize_public_text(str(payload.get("hero_title") or target_display))[:120]
    payload["hero_summary"] = sanitize_public_text(str(payload.get("hero_summary") or payload["description"]))[:360]
    if len(payload["hero_summary"]) < 80:
        payload["hero_summary"] = (
            f"This report synthesizes official disclosures, structured evidence, and market context for {target_display}."
        )[:360]

    sections = _normalise_section_dicts(payload.get("sections"), target_display=target_display)
    while len(sections) < 4:
        sections.append(
            {
                "heading": "Key research context",
                "paragraphs": [
                    f"This section captures material developments for {target_display} from official updates and supporting evidence."
                ],
                "bullets": [],
            }
        )
    payload["sections"] = sections[:10]

    faqs_raw = list(payload.get("faqs") or [])
    clean_faqs: list[dict[str, str]] = []
    for item in faqs_raw[:6]:
        if not isinstance(item, dict):
            continue
        question = sanitize_public_text(str(item.get("question") or "")).strip()[:180]
        answer = sanitize_public_text(str(item.get("answer") or "")).strip()[:900]
        if len(question) >= 8 and len(answer) >= 24:
            clean_faqs.append({"question": question, "answer": answer})
    for faq in _DEFAULT_FAQS:
        if len(clean_faqs) >= 4:
            break
        clean_faqs.append({"question": faq.question, "answer": faq.answer})
    payload["faqs"] = clean_faqs[:6]
    return payload


def _company_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    return [
        token
        for token in tokens
        if len(token) >= 3 and token not in _COMPANY_NAME_NOISE_TOKENS
    ]


def _extract_company_hint(req: "FlashGenerationRequest", meta: dict[str, Any]) -> str:
    candidates = [
        str(meta.get("company_name") or ""),
        str(meta.get("entity_name") or ""),
        str(req.target or ""),
    ]
    for candidate in candidates:
        text = sanitize_public_text(candidate).strip()
        if not text:
            continue
        # Common monitor target pattern: "... for <company>"
        for_match = re.search(r"\bfor\s+(.+)$", text, flags=re.IGNORECASE)
        cleaned = for_match.group(1).strip() if for_match else text
        cleaned = re.sub(r"[:\-|].*$", "", cleaned).strip()
        if len(cleaned) >= 4:
            return cleaned[:140]
    return ""


def _filter_sources_for_company(
    sources: list[dict[str, str]],
    *,
    company_hint: str,
) -> list[dict[str, str]]:
    tokens = _company_tokens(company_hint)
    if not tokens:
        return sources

    filtered: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        evidence_type = str(source.get("evidence_type") or "")
        source_kind = str(source.get("kind") or "")
        if source_kind == "primary_seed":
            filtered.append(source)
            continue
        haystack = " ".join(
            [
                str(source.get("title") or ""),
                str(source.get("snippet") or ""),
                url,
            ]
        ).lower()
        token_match = any(token in haystack for token in tokens)
        if evidence_type in {"official_document", "official_attachment"}:
            if token_match:
                filtered.append(source)
            continue
        if evidence_type == "company_context":
            filtered.append(source)
            continue
        if token_match:
            filtered.append(source)

    # Never return an empty list if upstream already found evidence.
    return filtered or sources[:6]


def _assemble_article_from_pipeline(
    memo: str | None,
    ikg_ctx: dict[str, Any],
    req: FlashGenerationRequest,
    slug: str,
    quality_score: float,
    content_type: str | None = None,
) -> ContentArticlePackage:
    """
    Build a ContentArticlePackage from the synthesis memo.
    - First attempts JSON parse (the synthesis objective requests JSON output).
    - Falls back to markdown splitting if JSON parse fails.
    - Injects IKG context block in both paths.
    """
    ikg_section_dict = None
    if ikg_ctx.get("narrative"):
        ikg_section_dict = {
            "heading": "What verified ownership and governance records show",
            "paragraphs": [
                ikg_ctx["narrative"],
                (
                    "These records track corporate governance structures, "
                    "promoter networks, auditor tenure, related-party transactions, and SEBI regulatory "
                    "actions for listed Indian companies — providing a verified layer of intelligence "
                    "not available from public data sources alone."
                ),
            ],
            "bullets": [],
        }

    if memo:
        # Strip markdown fences if present
        cleaned = memo.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.MULTILINE)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        try:
            data = json.loads(cleaned)
            data = _coerce_article_payload(
                data,
                slug=slug,
                target_display=req.target[:80],
                label=_label_for_content_type((content_type or req.content_type or "manual").strip().lower()),
            )
            # Inject IKG section
            if ikg_section_dict:
                existing_sections: list[dict] = data.get("sections") or []
                # Check if IKG section already present
                has_ikg = any(
                    "knowledge graph" in str(s.get("heading", "")).lower()
                    for s in existing_sections
                )
                if not has_ikg and existing_sections:
                    existing_sections.insert(
                        max(0, len(existing_sections) - 1), ikg_section_dict
                    )
                    data["sections"] = existing_sections
            data = _coerce_article_payload(
                data,
                slug=slug,
                target_display=req.target[:80],
                label=_label_for_content_type((content_type or req.content_type or "manual").strip().lower()),
            )
            return ContentArticlePackage.model_validate(data)
        except Exception:
            logger.debug("Memo JSON parse failed for %r — using markdown fallback", slug)

    # ── Markdown fallback ─────────────────────────────────────────────────────
    effective_content_type = (content_type or req.content_type or "manual").strip().lower()
    label = _label_for_content_type(effective_content_type)
    target_display = req.target[:80]

    sections = _split_memo_to_sections(memo or "")
    if ikg_section_dict:
        sections.append(
            ContentArticleSection(
                heading=ikg_section_dict["heading"],
                paragraphs=ikg_section_dict["paragraphs"],
                bullets=[],
            )
        )
    # Ensure minimum depth
    while len(sections) < 4:
        sections.append(ContentArticleSection(
            heading="Key Takeaways",
            paragraphs=[
                f"The above analysis covers key developments for {target_display} based on "
                f"official exchange filings, regulatory disclosures, and verified governance records.",
            ],
            bullets=[],
        ))

    faqs = _extract_faqs(memo or "")
    faqs.extend(_DEFAULT_FAQS)
    faqs = faqs[:6]

    title = f"{target_display} — {label} | ProspektLab"[:120]
    description = (
        f"In-depth {label.lower()} of {target_display} from official filings, "
        f"verified governance records, and ProspektLab's editorial research workflow."
    )[:220]

    return ContentArticlePackage(
        slug=slug,
        title=title,
        description=description,
        hero_eyebrow=label,
        hero_title=target_display[:120],
        hero_summary=description[:360],
        audience="Indian investors and market researchers",
        keywords=[target_display, label, "India markets", "ProspektLab",
                  "financial analysis", effective_content_type, "BSE", "NSE", "SEBI"][:12],
        key_takeaways=[
            {
                "heading": "What changed",
                "detail": f"Latest update for {target_display} summarized from verified records and supporting context.",
            },
            {
                "heading": "Why it matters",
                "detail": "The article links event-level developments to business and investor-relevant implications.",
            },
        ],
        sections=sections[:10],
        faqs=faqs,
        cta_label="Explore ProspektLab",
        cta_href="/#/contact",
        image_prompt=(
            f"Premium editorial cover for '{target_display}', styled for the ProspektLab dark research terminal. "
            "Composition: 3:2 ratio, deep navy and near-black backdrop with subtle cyan and violet glow highlights, "
            "layered floating financial UI panels (charts, ticker rows, document snippets), one strong central subject "
            "tied to the story, soft volumetric lighting from a single accent source. Aesthetic: Bloomberg-meets-LiveMint, "
            "premium dark-mode financial journalism, India market context (Nifty, BSE, SEBI references where relevant). "
            "No headline text, no watermark, no logos. Generous margins so the subject reads cleanly inside a card."
        ),
    )


# ── Direct JSON article synthesis (post-research pass) ────────────────────────

def _synth_model_candidates(primary_model: str) -> list[str]:
    candidates = [
        str(primary_model or "").strip(),
        str(os.getenv("OPENAI_CHAT_MODEL") or "").strip(),
        "gpt-5.4-mini",
        "gpt-4.1-mini",
    ]
    ordered: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered or ["gpt-5.4-mini"]


def _required_section_headings(content_type: str) -> list[str]:
    common = [
        "What changed now",
        "Historical context and trendline",
        "Management and execution signals",
        "Risks, governance, and disclosures",
        "What to monitor next",
    ]
    if content_type == "earnings":
        return common + ["Quarter scorecard with YoY and QoQ deltas"]
    if content_type == "sebi":
        return common + ["Regulatory timeline and case status"]
    if content_type == "trend":
        return common + ["Sector map and transmission channels"]
    if content_type == "company":
        return common + ["Business model and competitive position"]
    return common


def _build_primary_evidence_context(req: "FlashGenerationRequest") -> str:
    meta = req.source_evidence_meta or {}
    lines: list[str] = []
    source_url = str(req.source_url or meta.get("source_url") or "").strip()
    if source_url:
        lines.append(f"Primary URL: {source_url}")

    doc_type = str(meta.get("attachment_document_type") or "").strip()
    extraction_status = str(meta.get("attachment_extraction_status") or "").strip()
    parser_name = str(meta.get("attachment_parser") or "").strip()
    if doc_type:
        lines.append(f"Attachment type: {doc_type}")
    if extraction_status:
        lines.append(f"Attachment extraction status: {extraction_status}")
    if parser_name:
        lines.append(f"Attachment parser: {parser_name}")

    structured_facts = meta.get("attachment_structured_facts")
    if isinstance(structured_facts, dict) and structured_facts:
        lines.append("Structured facts from attachment:")
        for key, value in list(structured_facts.items())[:30]:
            k = sanitize_public_text(str(key).replace("_", " ").strip())[:120]
            v = sanitize_public_text(str(value).strip())[:240]
            if k and v:
                lines.append(f"- {k}: {v}")

    table_count = len(list(meta.get("attachment_tables") or []))
    if table_count:
        lines.append(f"Attachment tables detected: {table_count}")

    markdown_excerpt = sanitize_public_text(str(req.source_markdown or "")).strip()
    attachment_text = sanitize_public_text(str(meta.get("attachment_text") or "")).strip()
    if markdown_excerpt:
        lines.append("\nPrimary source excerpt:")
        lines.append(markdown_excerpt[:6000])
    if attachment_text:
        lines.append("\nAttachment extraction excerpt:")
        lines.append(attachment_text[:7000])

    return "\n".join(lines).strip()


async def _direct_json_article_call(
    memo: str,
    ikg_ctx: dict[str, Any],
    req: "FlashGenerationRequest",
    slug: str,
    content_type: str | None = None,
    revision_note: str | None = None,
) -> ContentArticlePackage | None:
    """
    Use a direct OpenAI call (JSON mode) to convert the collected research memo
    into a structured ContentArticlePackage.  This is called AFTER the research
    pipeline completes — it's a lightweight format-conversion step that bypasses
    the synthesiser's fixed markdown templates.

    Returns None if the call fails so the caller can fall back to the existing
    markdown parser.
    """
    try:
        import openai  # type: ignore
    except ImportError:
        return None

    llm_cfg = resolve_openai_config(complexity="moderate")
    if not llm_cfg:
        return None

    primary_model = os.getenv("FINAGENT_SYNTH_MODEL") or llm_cfg.model or "gpt-5.4-mini"
    model_candidates = _synth_model_candidates(primary_model)

    effective_content_type = (content_type or req.content_type or "manual").strip().lower()
    label = _label_for_content_type(effective_content_type)
    target_display = req.target[:80]

    # Build IKG context injection
    ikg_block = ""
    if ikg_ctx.get("narrative"):
        ikg_block = (
            f"\n\n[IKG CONTEXT — must be included in article as a dedicated section]\n"
            f"{ikg_ctx['narrative']}\n"
            f"Supporting record identifier: CIN {ikg_ctx.get('cin')}"
        )
    primary_evidence_block = _build_primary_evidence_context(req)
    section_headings = _required_section_headings(effective_content_type)
    heading_line = ", ".join(section_headings)

    system_prompt = (
        "You are a senior markets correspondent at a top Indian business daily (LiveMint / Hindu BusinessLine). "
        "Convert research notes into a structured JSON article with professional editorial voice.\n\n"
        "VOICE RULES:\n"
        "- LEDE: Open with the single most important number or event and why it matters to the reader RIGHT NOW.\n"
        "- PARAGRAPH 2: 'Why now' — the specific catalyst or trigger that makes this story timely.\n"
        "- Each substantive section: at least one historical comparison or sector benchmark with specific numbers.\n"
        "- Attribute all sentiment: 'the street had expected', 'management guided for', 'analysts pencilled in'.\n"
        "- Close with a forward-looking paragraph: upcoming catalysts, next data point, what to watch.\n"
        "- BANNED: 'significant growth', 'strong performance', 'notable development', 'robust numbers', "
        "'going forward', 'it remains to be seen', 'only time will tell'. Replace with concrete figures.\n\n"
        "SEBI compliance: Do NOT use buy, sell, hold, accumulate, exit, target price, or rebalancing. "
        "Use only the evidence present in the notes; cite the source of each important number inline. "
        "Do not pad with textbook company descriptions or stale market-cap trivia. "
        "Return ONLY valid JSON — no markdown, no code fences, no explanation."
    )

    schema_description = """Return JSON with EXACTLY these fields:
{
  "slug": "<URL-safe identifier, 2-80 chars — use the provided slug>",
  "title": "<SEO title 50-70 chars — include company/topic name>",
  "description": "<meta description 140-170 chars — what the article covers>",
  "hero_eyebrow": "<short category label max 40 chars e.g. Earnings Analysis>",
  "hero_title": "<compelling headline max 100 chars>",
  "hero_summary": "<2-3 engaging sentences 100-300 chars summarising key insight>",
  "audience": "<target reader e.g. Indian retail investors>",
  "keywords": ["<8-12 precise search terms>"],
  "key_takeaways": [
    {"heading": "<short takeaway title>", "detail": "<what changed and why it matters>"}
  ],
  "metrics": [
    {"label": "<metric name>", "value": "<metric value>", "change": "<optional delta>", "period": "<optional period>", "source": "<optional source cue>"}
  ],
  "tables": [
    {"title": "<table title>", "columns": ["<col1>", "<col2>"], "rows": [["<r1c1>", "<r1c2>"]], "footnote": "<optional caveat/source>"}
  ],
  "visuals": [
    {"kind": "bar", "title": "<visual title>", "points": [{"label": "<point>", "value": 123.4}], "note": "<optional visual note>"}
  ],
  "timeline": [
    {"date": "<date label>", "event": "<milestone>", "detail": "<optional detail>", "source": "<optional source>"}
  ],
  "evidence_notes": [
    {"claim": "<claim text>", "source_title": "<source title>", "source_url": "<source url>"}
  ],
  "sections": [
    {
      "heading": "<section title>",
      "paragraphs": ["<paragraph 1>", "<paragraph 2>"],
      "bullets": ["<bullet point 1>", "<bullet point 2>"]
    }
  ],
  "faqs": [
    {"question": "<question retail investors actually ask?>", "answer": "<data-backed answer>"}
  ],
  "cta_label": "<call-to-action text max 40 chars>",
  "cta_href": "/#/contact",
  "image_prompt": "<detailed visual description for cover image generation>"
}

Requirements:
- sections: 5-7 sections with 2-3 paragraphs each (not 1 paragraph). Use ALL research data.
- faqs: 4-5 questions real retail investors ask about this topic
- key_takeaways: 3-6 items
- metrics: 4-8 source-backed items
- tables: at least 1 semantic table when numbers exist
- visuals: at least 1 visual block with numeric points
- timeline: required for regulatory/order topics
- Every factual claim must include the source inline in the text (e.g. "according to NSE filing...")
- Zero filler sentences — every sentence must add information
- SEBI compliance: NO buy/sell/hold/accumulate/exit/target price/rebalancing
- Include ALL significant data points from the research notes"""

    ikg_section_instruction = ""
    if ikg_ctx.get("narrative"):
        ikg_section_instruction = (
            '\n- One section MUST be titled "What the ProspektLab Knowledge Graph shows" '
            "containing the IKG context block provided"
        )
    structure_instruction = _article_structure_brief(
        effective_content_type,
        target_display,
        bool(ikg_ctx.get("narrative")),
    )

    user_prompt = (
        f"Convert the following research notes into a publication-ready financial article.\n\n"
        f"Topic: {target_display}\n"
        f"Content type: {effective_content_type}\n"
        f"Slug to use: {slug}\n"
        f"Category label: {label}\n"
        f"Required section headings (use exact or near-exact wording): {heading_line}\n"
        f"Minimum total body depth target: 1200+ words with concrete evidence density.\n"
        f"{schema_description}{ikg_section_instruction}\n\n"
        f"{structure_instruction}\n\n"
        f"RESEARCH NOTES:\n{memo[:12000]}{ikg_block}\n\n"
        f"PRIMARY EVIDENCE:\n{primary_evidence_block[:12000]}\n\n"
        f"REVISION NOTE:\n{sanitize_public_text(str(revision_note or '')).strip()[:800]}\n\n"
        f"Return ONLY the JSON object. No markdown fences. No explanation."
    )

    client = openai.AsyncOpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url)
    last_exc: Exception | None = None
    for model_name in model_candidates:
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_completion_tokens=5000,
                response_format={"type": "json_object"},
                timeout=80,
            )
            raw = response.choices[0].message.content or ""
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.MULTILINE)
                cleaned = re.sub(r"\n?```\s*$", "", cleaned)
            data = json.loads(cleaned)
            data = _coerce_article_payload(
                data,
                slug=slug,
                target_display=target_display,
                label=label,
            )
            return ContentArticlePackage.model_validate(data)
        except Exception as exc:
            last_exc = exc
            logger.warning("Direct JSON article call failed on %s: %s", model_name, exc)
            continue
    if last_exc:
        logger.warning("Direct JSON article call exhausted all model candidates: %s", last_exc)
    return None


# ── Scoring ───────────────────────────────────────────────────────────────────

_ADVISORY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(strong buy|buy|accumulate|sell|hold|exit|target price|price target)\b", re.I),
    re.compile(r"\b(undervalued|overvalued|fairly valued)\b", re.I),
)

_NON_ADVISORY_CONTEXT_HINTS: tuple[str, ...] = (
    "not investment advice",
    "does not constitute investment advice",
    "informational purposes only",
    "not a recommendation",
    "no recommendation",
)


def _domain(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def _is_official_source_url(url: str) -> bool:
    host = _domain(url)
    return bool(host) and any(
        host == hint or host.endswith(f".{hint}")
        for hint in _OFFICIAL_DOMAIN_HINTS
    )


def _is_trusted_supporting_source_url(url: str) -> bool:
    host = _domain(url)
    if not host:
        return False
    return any(host == hint or host.endswith(f".{hint}") for hint in _TRUSTED_SUPPORTING_DOMAIN_HINTS)


def _normalise_source_entry(
    *,
    title: str,
    url: str,
    kind: str,
    evidence_type: str,
    snippet: str = "",
) -> dict[str, str]:
    return {
        "title": sanitize_public_text(str(title or "").strip())[:220],
        "url": str(url or "").strip()[:1200],
        "kind": str(kind or "secondary").strip()[:40],
        "evidence_type": str(evidence_type or "supporting").strip()[:80],
        "snippet": sanitize_public_text(str(snippet or "").strip())[:360],
    }


def _dedupe_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in sources:
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip().lower()
        key = url.lower() if url else f"title:{title}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _is_official_update_request(req: FlashGenerationRequest) -> bool:
    if req.source_evidence_meta:
        return True
    source_url = str(req.source_url or "").strip()
    if source_url and _is_official_source_url(source_url):
        return True
    return req.content_type in {"earnings", "sebi"}


def _build_evidence_pack(
    req: FlashGenerationRequest,
    ikg_ctx: dict[str, Any],
    final_event: dict[str, Any],
) -> dict[str, Any]:
    official_evidence: list[dict[str, str]] = []
    supporting_sources: list[dict[str, str]] = []
    research_sources: list[dict[str, str]] = []
    company_context: list[dict[str, str]] = []
    source_candidates: list[dict[str, str]] = []

    meta = req.source_evidence_meta or {}
    source_url = str(req.source_url or "").strip()
    attachment_url = str(meta.get("attachment_url") or "").strip()
    source_page_url = str(meta.get("source_url") or source_url).strip()
    attachment_text = str(meta.get("attachment_text") or "").strip()
    attachment_tables = list(meta.get("attachment_tables") or [])
    attachment_structured_facts = meta.get("attachment_structured_facts")
    source_markdown = str(req.source_markdown or "").strip()

    if source_page_url:
        official_evidence.append(
            _normalise_source_entry(
                title="Official disclosure page",
                url=source_page_url,
                kind="primary_seed",
                evidence_type="official_document",
                snippet=source_markdown[:320],
            )
        )
    if attachment_url:
        official_evidence.append(
            _normalise_source_entry(
                title=f"Official attachment ({str(meta.get('attachment_document_type') or 'document')})",
                url=attachment_url,
                kind="primary_seed",
                evidence_type="official_attachment",
                snippet=attachment_text[:320],
            )
        )

    citation_sources = list(final_event.get("citation_sources") or [])
    for source in citation_sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or "Research source")
        kind = str(source.get("kind") or "secondary")
        entry = _normalise_source_entry(
            title=title,
            url=url,
            kind=kind,
            evidence_type="trusted_supporting"
            if _is_trusted_supporting_source_url(url)
            else ("official_document" if _is_official_source_url(url) else "research_context"),
        )
        if entry["evidence_type"] == "official_document":
            official_evidence.append(entry)
        elif entry["evidence_type"] == "trusted_supporting":
            supporting_sources.append(entry)
        else:
            research_sources.append(entry)

    if ikg_ctx.get("covered") and (ikg_ctx.get("cin") or ikg_ctx.get("entity")):
        cin = str(ikg_ctx.get("cin") or "")
        company_context.append(
            _normalise_source_entry(
                title="Verified company records",
                url=f"ikg://company/{cin or slugify(req.target)}",
                kind="derived",
                evidence_type="company_context",
                snippet=str(ikg_ctx.get("narrative") or "")[:320],
            )
        )

    source_candidates.extend(official_evidence)
    source_candidates.extend(supporting_sources)
    source_candidates.extend(research_sources)
    source_candidates.extend(company_context)
    source_candidates = _dedupe_sources(source_candidates)
    company_hint = _extract_company_hint(req, meta)
    source_candidates = _filter_sources_for_company(source_candidates, company_hint=company_hint)

    document_status = "ready"
    if req.source_evidence_meta:
        extraction_status = str(meta.get("attachment_extraction_status") or "").strip().lower()
        text_sufficient = bool(meta.get("attachment_text_sufficient"))
        inferred_sufficient = bool(
            text_sufficient
            or attachment_text
            or source_markdown
            or (isinstance(attachment_structured_facts, dict) and len(attachment_structured_facts) > 0)
            or (isinstance(attachment_tables, list) and len(attachment_tables) > 0)
        )
        if extraction_status != "ok" or not inferred_sufficient:
            document_status = "failed"
        elif not attachment_text and not source_markdown and not inferred_sufficient:
            document_status = "insufficient"
    elif _is_official_update_request(req):
        document_status = "missing"

    context_status = "ready" if (ikg_ctx.get("covered") or len(research_sources) >= 2) else "missing"
    research_status = "ready" if citation_sources else "limited"

    return {
        "official_document_evidence": _dedupe_sources(official_evidence),
        "company_context": _dedupe_sources(company_context),
        "research_pipeline_context": _dedupe_sources(research_sources),
        "trusted_supporting_sources": _dedupe_sources(supporting_sources),
        "attachment_tables": attachment_tables[:6],
        "attachment_structured_facts": attachment_structured_facts,
        "sources_used": source_candidates,
        "summary": {
            "document_evidence_status": document_status,
            "context_enrichment_status": context_status,
            "research_context_status": research_status,
            "official_source_count": len(_dedupe_sources(official_evidence)),
            "trusted_supporting_source_count": len(_dedupe_sources(supporting_sources)),
            "research_source_count": len(_dedupe_sources(research_sources)),
            "company_context_count": len(_dedupe_sources(company_context)),
            "source_count": len(source_candidates),
            "attachment_table_count": len(attachment_tables),
            "attachment_structured_fact_count": len(attachment_structured_facts) if isinstance(attachment_structured_facts, dict) else 0,
        },
    }


def _evidence_pack_prompt_block(evidence_pack: dict[str, Any]) -> str:
    summary = evidence_pack.get("summary") or {}
    parts: list[str] = [
        "[EVIDENCE PACK - use this as priority input]",
        (
            f"Document evidence status: {summary.get('document_evidence_status', 'unknown')}; "
            f"Context enrichment status: {summary.get('context_enrichment_status', 'unknown')}; "
            f"Trusted supporting sources: {summary.get('trusted_supporting_source_count', 0)}."
        ),
        (
            "Write with this structure: what happened, why it matters, business context, "
            "financial/regulatory impact, what changed from prior context, watchpoints, and clear limitations. "
            "Also emit structured presentation blocks: key_takeaways, metrics, tables, visuals, timeline, evidence_notes."
        ),
    ]
    if evidence_pack.get("official_document_evidence"):
        source_urls = [str(item.get("url") or "") for item in evidence_pack["official_document_evidence"][:4]]
        parts.append("Official evidence URLs: " + ", ".join(url for url in source_urls if url))
    return "\n".join(part for part in parts if part).strip()


def _extract_numeric_metrics(article: ContentArticlePackage) -> list[dict[str, str]]:
    metrics: list[dict[str, str]] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for section in article.sections:
        candidates.extend(section.bullets)
        candidates.extend(section.paragraphs)
    pattern = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/\-]{2,60}):\s*([^()]+?)(?:\s*\(([+\-][^)]+)\))?\s*$")
    for raw in candidates:
        line = sanitize_public_text(str(raw))
        match = pattern.match(line)
        if not match:
            continue
        label = match.group(1).strip()
        value = match.group(2).strip()
        change = (match.group(3) or "").strip()
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        metrics.append({"label": label[:80], "value": value[:80], "change": change[:40]})
        if len(metrics) >= 10:
            break
    return metrics


def _normalize_attachment_tables(meta: dict[str, Any]) -> list[dict[str, Any]]:
    tables = list(meta.get("attachment_tables") or [])
    normalized: list[dict[str, Any]] = []
    for index, table in enumerate(tables[:3], start=1):
        if isinstance(table, dict):
            columns = [sanitize_public_text(str(col))[:80] for col in list(table.get("columns") or [])[:10]]
            rows_raw = list(table.get("rows") or [])
            if not columns and rows_raw and isinstance(rows_raw[0], list):
                columns = [f"Column {i+1}" for i in range(min(10, len(rows_raw[0])))]
            rows: list[list[str]] = []
            for row in rows_raw[:20]:
                if not isinstance(row, list):
                    continue
                rows.append([sanitize_public_text(str(cell))[:140] for cell in row[:10]])
            if columns and rows:
                normalized.append(
                    {
                        "title": sanitize_public_text(str(table.get("title") or f"Attachment table {index}"))[:120],
                        "columns": columns,
                        "rows": rows,
                        "footnote": sanitize_public_text(str(table.get("note") or ""))[:300],
                    }
                )
        elif isinstance(table, list) and table:
            width = min(10, len(table[0]) if isinstance(table[0], list) else 0)
            if width <= 1:
                continue
            columns = [f"Column {i+1}" for i in range(width)]
            rows = []
            for row in table[:20]:
                if isinstance(row, list):
                    rows.append([sanitize_public_text(str(cell))[:140] for cell in row[:width]])
            if rows:
                normalized.append(
                    {
                        "title": f"Attachment table {index}",
                        "columns": columns,
                        "rows": rows,
                        "footnote": "",
                    }
                )
    return normalized


def _normalized_public_text(*values: Any) -> str:
    chunks: list[str] = []
    for value in values:
        if value is None:
            continue
        chunks.append(sanitize_public_text(str(value)))
    return re.sub(r"\s+", " ", " ".join(chunks)).strip().lower()


def _contains_diagnostic_public_text(*values: Any) -> bool:
    text = _normalized_public_text(*values)
    if not text:
        return False
    return any(token in text for token in _DIAGNOSTIC_PUBLIC_TOKENS)


def _is_business_numeric_signal(label: str, value: Any, *context: Any) -> bool:
    value_text = str(value or "")
    if _contains_diagnostic_public_text(label, value_text, *context):
        return False
    match = re.search(r"[-+]?\d*\.?\d+", value_text.replace(",", ""))
    if not match:
        return False
    combined = _normalized_public_text(label, value_text, *context)
    if any(hint in combined for hint in _BUSINESS_NUMERIC_HINTS):
        return True
    if re.search(r"(?:%|bps|crore|cr|lakh|million|billion|mn|bn|rs\.?|inr|usd|\$|₹|x)", value_text.lower()):
        return True
    return False


def _structured_visuals_from_metrics(metrics: list[dict[str, str]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        if not _is_business_numeric_signal(
            str(metric.get("label") or ""),
            metric.get("value"),
            metric.get("source"),
            metric.get("period"),
            metric.get("change"),
        ):
            continue
        value = str(metric.get("value") or "")
        value_clean = value.replace(",", "")
        match = re.search(r"[-+]?\d*\.?\d+", value_clean)
        if not match:
            continue
        try:
            numeric = float(match.group(0))
        except ValueError:
            continue
        points.append({"label": str(metric.get("label") or "")[:30], "value": numeric})
        if len(points) >= 8:
            break
    if len(points) < 2:
        return []
    return [
        {
            "kind": "bar",
            "title": "Quantitative signal map",
            "points": points,
            "note": "Derived from source-backed metrics in this article.",
        }
    ]


def _structured_visuals_from_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for table in tables:
        if not isinstance(table, dict):
            continue
        if _contains_diagnostic_public_text(table.get("title")):
            continue
        columns = list(table.get("columns") or [])
        rows = list(table.get("rows") or [])
        if len(columns) < 2 or len(rows) < 2:
            continue
        points: list[dict[str, Any]] = []
        for row in rows[:8]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            label = sanitize_public_text(str(row[0]))[:30].strip()
            raw = str(row[1]).replace(",", "")
            if not _is_business_numeric_signal(label, raw, table.get("title"), columns):
                continue
            match = re.search(r"[-+]?\d*\.?\d+", raw)
            if not label or not match:
                continue
            try:
                value = float(match.group(0))
            except ValueError:
                continue
            points.append({"label": label, "value": value})
        if len(points) >= 2:
            return [
                {
                    "kind": "bar",
                    "title": sanitize_public_text(str(table.get("title") or "Data trend"))[:120],
                    "points": points,
                    "note": "Visual derived from table values captured in source evidence.",
                }
            ]
    return []


def _inject_structured_presentation(
    article: ContentArticlePackage,
    *,
    req: FlashGenerationRequest,
    evidence_pack: dict[str, Any],
    evidence_claims: list[dict[str, str]],
) -> ContentArticlePackage:
    data = article.model_dump()
    meta = req.source_evidence_meta or {}
    content_type = _effective_content_type(req)

    if not data.get("key_takeaways"):
        takeaways: list[dict[str, str]] = []
        for section in list(data.get("sections") or [])[:4]:
            if not isinstance(section, dict):
                continue
            heading = sanitize_public_text(str(section.get("heading") or "")).strip()
            para = ""
            paragraphs = list(section.get("paragraphs") or [])
            if paragraphs:
                para = sanitize_public_text(str(paragraphs[0]))[:260]
            if heading and para:
                takeaways.append({"heading": heading[:120], "detail": para})
        data["key_takeaways"] = takeaways[:6]

    metrics = list(data.get("metrics") or [])
    clean_metrics: list[dict[str, str]] = []
    seen_metric_keys: set[str] = set()

    def _push_metric(label: str, value: str, change: str = "", period: str = "", source: str = "") -> None:
        label_clean = sanitize_public_text(str(label)).strip()[:80]
        value_clean = sanitize_public_text(str(value)).strip()[:80]
        if not label_clean or not value_clean:
            return
        if _contains_diagnostic_public_text(label_clean, value_clean, change, period, source):
            return
        key = re.sub(r"\W+", " ", label_clean.lower()).strip()
        if not key or key in seen_metric_keys:
            return
        seen_metric_keys.add(key)
        clean_metrics.append(
            {
                "label": label_clean,
                "value": value_clean,
                "change": sanitize_public_text(str(change)).strip()[:40],
                "period": sanitize_public_text(str(period)).strip()[:60],
                "source": sanitize_public_text(str(source)).strip()[:180],
            }
        )

    for metric in metrics[:12]:
        if not isinstance(metric, dict):
            continue
        _push_metric(
            str(metric.get("label") or ""),
            str(metric.get("value") or ""),
            str(metric.get("change") or ""),
            str(metric.get("period") or ""),
            str(metric.get("source") or ""),
        )

    if len(clean_metrics) < 4:
        for metric in _extract_numeric_metrics(article):
            _push_metric(
                str(metric.get("label") or ""),
                str(metric.get("value") or ""),
                str(metric.get("change") or ""),
                str(metric.get("period") or ""),
                str(metric.get("source") or "Derived from article evidence"),
            )
            if len(clean_metrics) >= 10:
                break

    if len(clean_metrics) < 4:
        structured_facts = meta.get("attachment_structured_facts")
        if isinstance(structured_facts, dict):
            for key, value in list(structured_facts.items())[:24]:
                _push_metric(
                    str(key).replace("_", " ").title(),
                    str(value),
                    "",
                    "",
                    "Attachment facts",
                )
                if len(clean_metrics) >= 10:
                    break

    if len(clean_metrics) < 4:
        claim_pattern = re.compile(
            r"([A-Za-z][A-Za-z0-9 /&().%-]{3,70})\s*[:\-]\s*([\-+]?[\d,]+(?:\.\d+)?(?:\s*(?:%|bps|x|crore|cr|lakh|million|billion|bn|mn))?)",
            re.IGNORECASE,
        )
        for claim in evidence_claims:
            text = sanitize_public_text(str(claim.get("claim") or ""))
            match = claim_pattern.search(text)
            if not match:
                continue
            _push_metric(
                match.group(1),
                match.group(2),
                "",
                "",
                str(claim.get("source_title") or claim.get("source_url") or "Evidence note"),
            )
            if len(clean_metrics) >= 10:
                break

    metrics = clean_metrics[:10]
    data["metrics"] = metrics

    tables = list(data.get("tables") or [])
    filtered_existing_tables: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        title = sanitize_public_text(str(table.get("title") or "")).strip()[:120]
        if _contains_diagnostic_public_text(title):
            continue
        columns = [sanitize_public_text(str(col)).strip()[:80] for col in list(table.get("columns") or [])[:10]]
        rows: list[list[str]] = []
        for row in list(table.get("rows") or [])[:20]:
            if not isinstance(row, list):
                continue
            cleaned = [sanitize_public_text(str(cell)).strip()[:140] for cell in row[:10]]
            if _contains_diagnostic_public_text(title, columns, cleaned):
                continue
            rows.append(cleaned)
        if len(columns) < 2 or len(rows) < 1:
            continue
        if not any(
            _is_business_numeric_signal(str(row[0] if row else ""), str(row[1] if len(row) > 1 else ""), title, columns)
            for row in rows
        ):
            continue
        filtered_existing_tables.append(
            {
                "title": title,
                "columns": columns,
                "rows": rows,
                "footnote": sanitize_public_text(str(table.get("footnote") or ""))[:300],
            }
        )
    tables = filtered_existing_tables
    existing_rows = sum(len(list(table.get("rows") or [])) for table in tables if isinstance(table, dict))
    if not tables or existing_rows < 2:
        attachment_tables = _normalize_attachment_tables(meta)
        if attachment_tables:
            tables = attachment_tables[:3]
        elif metrics:
            rows = [
                [str(metric.get("label") or ""), str(metric.get("value") or ""), str(metric.get("change") or "")]
                for metric in metrics[:10]
            ]
            tables = [{
                "title": "Key reported metrics",
                "columns": ["Metric", "Value", "Change"],
                "rows": rows,
                "footnote": "Compiled from source-backed metrics in this article.",
            }]
    data["tables"] = tables

    visuals = list(data.get("visuals") or [])
    filtered_existing_visuals: list[dict[str, Any]] = []
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        title = sanitize_public_text(str(visual.get("title") or ""))[:120]
        note = sanitize_public_text(str(visual.get("note") or ""))[:220]
        if _contains_diagnostic_public_text(title, note):
            continue
        points_raw = list(visual.get("points") or [])
        points: list[dict[str, Any]] = []
        for point in points_raw[:12]:
            if not isinstance(point, dict):
                continue
            label = sanitize_public_text(str(point.get("label") or ""))[:80]
            value = point.get("value")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not _is_business_numeric_signal(label, numeric, title, note):
                continue
            points.append({"label": label, "value": numeric})
        if len(points) < 2:
            continue
        filtered_existing_visuals.append(
            {
                "kind": sanitize_public_text(str(visual.get("kind") or "bar"))[:20] or "bar",
                "title": title or "Data trend",
                "points": points,
                "note": note,
            }
        )
    visuals = filtered_existing_visuals
    if not visuals:
        visuals = _structured_visuals_from_metrics(metrics)
    if not visuals:
        visuals = _structured_visuals_from_tables(tables)
    data["visuals"] = visuals

    timeline = list(data.get("timeline") or [])
    if not timeline and content_type in {"sebi", "earnings", "company"}:
        timeline = [{
            "date": datetime.now(timezone.utc).date().isoformat(),
            "event": "Latest filing/update processed",
            "detail": sanitize_public_text(req.target)[:180],
            "source": str(req.source_url or meta.get("source_url") or "")[:180],
        }]
        data["timeline"] = timeline

    if not data.get("evidence_notes"):
        notes = []
        for claim in evidence_claims[:10]:
            notes.append(
                {
                    "claim": sanitize_public_text(str(claim.get("claim") or ""))[:420],
                    "source_title": sanitize_public_text(str(claim.get("source_title") or ""))[:220],
                    "source_url": str(claim.get("source_url") or "")[:1200],
                }
            )
        data["evidence_notes"] = notes

    # Ensure missing research dimensions are explicitly covered in output structure.
    try:
        staged = ContentArticlePackage.model_validate(data)
        coverage = _research_dimension_coverage(staged)
        section_dicts = list(data.get("sections") or [])
        if not coverage.get("historical"):
            section_dicts.append(
                {
                    "heading": "Historical context and trendline",
                    "paragraphs": [
                        f"This update is interpreted against prior disclosed context for {sanitize_public_text(req.target)[:120]}, not as a standalone headline.",
                        "Readers should compare this filing with prior quarter disclosures, management commentary, and earlier governance signals to assess trajectory.",
                    ],
                    "bullets": [
                        "Track YoY and QoQ continuity where numeric disclosures are available.",
                        "Verify whether prior stated assumptions remain valid in this update.",
                    ],
                }
            )
        if not coverage.get("sentiment"):
            section_dicts.append(
                {
                    "heading": "Sentiment and narrative read-through",
                    "paragraphs": [
                        "Narrative risk is evaluated from disclosure tone, follow-on coverage patterns, and the balance between official facts and market interpretation.",
                        "This section avoids price calls and focuses on what sentiment signals may imply for risk perception and information efficiency.",
                    ],
                    "bullets": [
                        "Separate filing-confirmed facts from commentary-driven market narratives.",
                        "Watch for contradiction between management messaging and subsequent disclosures.",
                    ],
                }
            )
        if not coverage.get("watchpoints"):
            section_dicts.append(
                {
                    "heading": "What to monitor next quarter",
                    "paragraphs": [
                        "The next disclosure cycle should be monitored for execution confirmation, guidance consistency, and governance continuity.",
                        "If new filings alter assumptions used in this article, the thesis should be updated with fresh evidence.",
                    ],
                    "bullets": [
                        "Management follow-through vs announced intent.",
                        "Any new regulatory or compliance disclosures.",
                        "Change in key operating or funding indicators.",
                    ],
                }
            )
        data["sections"] = section_dicts[:10]
    except Exception:
        pass

    return ContentArticlePackage.model_validate(data)


def _article_word_count(article: ContentArticlePackage) -> int:
    chunks: list[str] = [article.title, article.description, article.hero_summary]
    for takeaway in article.key_takeaways:
        chunks.append(takeaway.heading)
        chunks.append(takeaway.detail)
    for metric in article.metrics:
        chunks.append(metric.label)
        chunks.append(metric.value)
        chunks.append(metric.change)
        chunks.append(metric.period)
        chunks.append(metric.source)
    for table in article.tables:
        chunks.append(table.title)
        chunks.extend(table.columns)
        for row in table.rows:
            chunks.extend(str(cell) for cell in row)
        chunks.append(table.footnote)
    for visual in article.visuals:
        chunks.append(visual.title)
        chunks.append(visual.note)
        for point in visual.points:
            chunks.append(point.label)
            chunks.append(str(point.value))
    for event in article.timeline:
        chunks.append(event.date)
        chunks.append(event.event)
        chunks.append(event.detail)
        chunks.append(event.source)
    for note in article.evidence_notes:
        chunks.append(note.claim)
        chunks.append(note.source_title)
        chunks.append(note.source_url)
    chunks.extend(section.heading for section in article.sections)
    for section in article.sections:
        chunks.extend(section.paragraphs)
        chunks.extend(section.bullets)
    for faq in article.faqs:
        chunks.append(faq.question)
        chunks.append(faq.answer)
    return len(re.findall(r"\b[\w%-]+\b", " ".join(chunks)))


def _substantive_section_count(article: ContentArticlePackage) -> int:
    count = 0
    for section in article.sections:
        para_words = sum(len(re.findall(r"\b[\w%-]+\b", paragraph)) for paragraph in section.paragraphs)
        bullet_words = sum(len(re.findall(r"\b[\w%-]+\b", bullet)) for bullet in section.bullets)
        if len(section.paragraphs) >= 2 and (para_words + bullet_words) >= 55:
            count += 1
    return count


def _article_plain_text(article: ContentArticlePackage) -> str:
    parts = [article.title, article.description, article.hero_summary]
    for takeaway in article.key_takeaways:
        parts.append(takeaway.heading)
        parts.append(takeaway.detail)
    for metric in article.metrics:
        parts.append(metric.label)
        parts.append(metric.value)
        parts.append(metric.change)
    for table in article.tables:
        parts.append(table.title)
        parts.extend(table.columns)
        for row in table.rows:
            parts.extend(str(cell) for cell in row)
    for visual in article.visuals:
        parts.append(visual.title)
        parts.extend(point.label for point in visual.points)
    for event in article.timeline:
        parts.append(event.date)
        parts.append(event.event)
        parts.append(event.detail)
    for note in article.evidence_notes:
        parts.append(note.claim)
        parts.append(note.source_title)
    for section in article.sections:
        parts.append(section.heading)
        parts.extend(section.paragraphs)
        parts.extend(section.bullets)
    for faq in article.faqs:
        parts.append(faq.question)
        parts.append(faq.answer)
    return "\n".join(part for part in parts if part).strip()


def _advisory_language_present(article: ContentArticlePackage) -> bool:
    # Ignore FAQ disclaimers; enforce advisory policy on analytical copy.
    parts: list[str] = [article.title, article.description, article.hero_summary]
    for takeaway in article.key_takeaways:
        parts.append(takeaway.heading)
        parts.append(takeaway.detail)
    for section in article.sections:
        parts.append(section.heading)
        parts.extend(section.paragraphs)
        parts.extend(section.bullets)
    for note in article.evidence_notes:
        parts.append(note.claim)

    text = "\n".join(part for part in parts if part)
    lowered = text.lower()
    for pattern in _ADVISORY_PATTERNS:
        for match in pattern.finditer(text):
            left = max(0, match.start() - 80)
            right = min(len(lowered), match.end() + 80)
            window = lowered[left:right]
            if any(hint in window for hint in _NON_ADVISORY_CONTEXT_HINTS):
                continue
            return True
    return False


def _split_sentences(text: str, *, max_count: int = 80) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [part.strip() for part in parts if len(part.strip()) >= 24]
    return sentences[:max_count]


def _pick_claim_source(claim: str, evidence_pack: dict[str, Any]) -> dict[str, str] | None:
    lower = claim.lower()
    official = list(evidence_pack.get("official_document_evidence") or [])
    trusted = list(evidence_pack.get("trusted_supporting_sources") or [])
    research = list(evidence_pack.get("research_pipeline_context") or [])
    company = list(evidence_pack.get("company_context") or [])

    if any(token in lower for token in ("sebi", "nse", "bse", "disclosure", "filing", "order", "adjudication")) and official:
        return official[0]
    if any(token in lower for token in ("promoter", "governance", "ownership", "related party", "auditor")) and company:
        return company[0]
    if trusted:
        return trusted[0]
    if official:
        return official[0]
    if research:
        return research[0]
    if company:
        return company[0]
    return None


def _build_evidence_claims(article: ContentArticlePackage, evidence_pack: dict[str, Any]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    seen_claims: set[str] = set()
    text = _article_plain_text(article)
    for sentence in _split_sentences(text, max_count=140):
        claim = sentence.strip()
        claim_key = re.sub(r"\W+", " ", claim.lower()).strip()
        if len(claim_key) < 30 or claim_key in seen_claims:
            continue
        if not re.search(r"\d", claim) and not any(pattern.search(claim) for pattern in _SOURCE_SIGNAL_PATTERNS):
            continue
        source = _pick_claim_source(claim, evidence_pack)
        if not source:
            continue
        seen_claims.add(claim_key)
        claims.append(
            {
                "claim": sanitize_public_text(claim)[:420],
                "source_url": str(source.get("url") or "")[:1200],
                "source_title": sanitize_public_text(str(source.get("title") or ""))[:220],
                "evidence_type": str(source.get("evidence_type") or "supporting"),
                "evidence_snippet": sanitize_public_text(str(source.get("snippet") or ""))[:380],
            }
        )
        if len(claims) >= 28:
            break
    return claims


def _compute_depth_score(article: ContentArticlePackage) -> int:
    section_count = len(article.sections)
    paragraph_count = sum(len(section.paragraphs) for section in article.sections)
    words = _article_word_count(article)
    substantive_sections = _substantive_section_count(article)
    score = 0.0
    score += min(section_count, 9) / 9 * 32
    score += min(paragraph_count, 24) / 24 * 28
    score += min(substantive_sections, 8) / 8 * 25
    score += min(words, 1600) / 1600 * 15
    return int(round(min(score, 100)))


def _compute_source_score(sources_used: list[dict[str, str]], editorial_source_score: int) -> int:
    if not sources_used:
        return 0
    source_count = len(sources_used)
    unique_domains = {domain for domain in (_domain(item.get("url") or "") for item in sources_used) if domain}
    official_sources = sum(1 for source in sources_used if _is_official_source_url(str(source.get("url") or "")))
    trusted_sources = sum(1 for source in sources_used if _is_trusted_supporting_source_url(str(source.get("url") or "")))

    base = 0.0
    base += min(source_count, 8) / 8 * 32
    base += min(len(unique_domains), 6) / 6 * 28
    base += min(official_sources, 2) / 2 * 24
    base += min(trusted_sources, 4) / 4 * 16
    weighted = int(round((base * 0.65) + (max(0, min(editorial_source_score, 100)) * 0.35)))
    return min(weighted, 100)


def _compute_evidence_score(
    evidence_pack: dict[str, Any],
    evidence_claims: list[dict[str, str]],
    *,
    is_official_update: bool,
) -> int:
    summary = evidence_pack.get("summary") or {}
    score = 0.0
    if summary.get("document_evidence_status") == "ready":
        score += 38
    elif summary.get("document_evidence_status") == "insufficient":
        score += 16
    elif not is_official_update:
        score += 20
    if summary.get("context_enrichment_status") == "ready":
        score += 20
    score += min(int(summary.get("trusted_supporting_source_count") or 0), 4) / 4 * 16
    score += min(int(summary.get("source_count") or 0), 8) / 8 * 14
    score += min(len(evidence_claims), 16) / 16 * 12
    return int(round(min(score, 100)))


def _unsupported_claims_present(
    article: ContentArticlePackage,
    evidence_claims: list[dict[str, str]],
    sources_used: list[dict[str, str]],
) -> bool:
    text = _article_plain_text(article)
    numeric_sentences = [
        sentence for sentence in _split_sentences(text, max_count=220)
        if re.search(r"\d", sentence)
    ]
    if numeric_sentences and not sources_used:
        return True
    if len(numeric_sentences) >= 6 and len(evidence_claims) < max(4, len(numeric_sentences) // 3):
        return True
    return False


def _structured_presentation_counts(article: ContentArticlePackage) -> dict[str, int]:
    table_count = len(article.tables or [])
    table_rows = sum(len(table.rows or []) for table in (article.tables or []))
    metric_count = len(article.metrics or [])
    visual_count = len(article.visuals or [])
    timeline_count = len(article.timeline or [])
    evidence_note_count = len(article.evidence_notes or [])
    return {
        "table_count": table_count,
        "table_rows": table_rows,
        "metric_count": metric_count,
        "visual_count": visual_count,
        "timeline_count": timeline_count,
        "evidence_note_count": evidence_note_count,
    }


def _research_dimension_coverage(article: ContentArticlePackage) -> dict[str, bool]:
    headings = " ".join(str(section.heading or "") for section in article.sections).lower()
    body = _article_plain_text(article).lower()
    return {
        "historical": any(token in body for token in ("historical", "previous quarter", "yoy", "qoq", "year-on-year")),
        "management": any(token in body for token in ("management", "concall", "guidance", "analyst meet", "investor meet")),
        "sentiment": any(token in body for token in ("sentiment", "market reaction", "investor reaction", "narrative")),
        "governance": any(token in body for token in ("governance", "regulatory", "sebi", "compliance", "promoter")),
        "watchpoints": any(token in headings or token in body for token in ("watch", "monitor", "what to track", "next quarter")),
    }


def _evidence_has_numeric_signals(evidence_pack: dict[str, Any], evidence_claims: list[dict[str, str]]) -> bool:
    summary = evidence_pack.get("summary") or {}
    if int(summary.get("attachment_table_count") or 0) > 0:
        return True
    if int(summary.get("attachment_structured_fact_count") or 0) > 0:
        return True
    for claim in evidence_claims:
        claim_text = str(claim.get("claim") or "")
        if _contains_diagnostic_public_text(claim_text):
            continue
        if re.search(r"\d", claim_text) and _is_business_numeric_signal(
            str(claim.get("source_title") or "Evidence"),
            claim_text,
            claim.get("source_url"),
        ):
            return True
    return False


def _evaluate_publish_gate(
    *,
    req: FlashGenerationRequest,
    article: ContentArticlePackage,
    editorial_review: Any,
    quality_score: float,
    evidence_pack: dict[str, Any],
    evidence_claims: list[dict[str, str]],
) -> dict[str, Any]:
    is_official_update = _is_official_update_request(req)
    effective_content_type = _effective_content_type(req)
    sources_used = _dedupe_sources(list(evidence_pack.get("sources_used") or []))
    word_count = _article_word_count(article)
    section_count = len(article.sections)
    substantive_sections = _substantive_section_count(article)
    editorial_score = int(getattr(editorial_review, "total_score", 0) or 0)
    editorial_source_score = int(getattr(editorial_review, "source_score", 0) or 0)
    depth_score = _compute_depth_score(article)
    source_score = _compute_source_score(sources_used, editorial_source_score)
    evidence_score = _compute_evidence_score(
        evidence_pack,
        evidence_claims,
        is_official_update=is_official_update,
    )
    structured_counts = _structured_presentation_counts(article)
    research_dimensions = _research_dimension_coverage(article)
    numeric_evidence_present = _evidence_has_numeric_signals(evidence_pack, evidence_claims)
    confidence = int(
        round(
            max(0.0, min(quality_score, 100.0)) * 0.15
            + editorial_score * 0.35
            + source_score * 0.20
            + depth_score * 0.15
            + evidence_score * 0.15
        )
    )
    confidence = max(0, min(confidence, 100))

    reasons: list[str] = []
    article_text = _article_plain_text(article)
    lower_text = article_text.lower()

    summary = evidence_pack.get("summary") or {}
    if not sources_used:
        reasons.append("missing_source_evidence")
    if not evidence_claims:
        reasons.append("missing_evidence_claims")
    if is_official_update and str(summary.get("document_evidence_status") or "") != "ready":
        reasons.append("missing_official_document_evidence")
    if is_official_update and word_count < 1200:
        reasons.append("official_article_too_short")
    if effective_content_type in {"earnings", "company", "trend"} and word_count < 1300:
        reasons.append("research_article_too_short")
    if substantive_sections < 6:
        reasons.append("insufficient_substantive_sections")
    if contains_internal_language(article_text):
        reasons.append("internal_language")
    if _advisory_language_present(article) and not is_ra_licensed():
        reasons.append("advisory_language")
    limited_data_hits = sum(1 for pattern in _LIMITED_DATA_PATTERNS if pattern.search(article_text))
    if limited_data_hits >= 2:
        reasons.append("limited_data_copy")
    filler_hits = sum(1 for pattern in _FILLER_PATTERNS if pattern.search(lower_text))
    if filler_hits >= 2:
        reasons.append("filler_copy")
    if _unsupported_claims_present(article, evidence_claims, sources_used):
        reasons.append("unsupported_claims")
    if is_official_update and str(summary.get("context_enrichment_status") or "") != "ready":
        reasons.append("context_enrichment_missing")
    if is_official_update and word_count < 700:
        reasons.append("insufficient_structured_evidence")
    if effective_content_type in {"earnings", "sebi", "company"} and numeric_evidence_present:
        if structured_counts["table_count"] == 0 or structured_counts["table_rows"] == 0:
            reasons.append("missing_metrics_table")
        if structured_counts["visual_count"] == 0:
            reasons.append("visual_block_not_available")
    if effective_content_type == "sebi" and structured_counts["timeline_count"] == 0:
        reasons.append("timeline_missing")
    if numeric_evidence_present and structured_counts["metric_count"] < 3:
        reasons.append("insufficient_metric_coverage")
    if numeric_evidence_present and structured_counts["evidence_note_count"] == 0:
        reasons.append("missing_evidence_notes")
    if effective_content_type in {"earnings", "company", "sebi", "trend"}:
        missing_dimensions = [name for name, present in research_dimensions.items() if not present]
        if "historical" in missing_dimensions:
            reasons.append("missing_company_history")
        if "management" in missing_dimensions:
            reasons.append("missing_management_context")
        if len(missing_dimensions) >= 3:
            reasons.append("missing_research_dimensions")

    threshold_checks = {
        "publish_gate_score": confidence >= _PUBLISH_GATE_THRESHOLDS["publish_gate_score"],
        "confidence": confidence >= _PUBLISH_GATE_THRESHOLDS["confidence"],
        "editorial_score": editorial_score >= _PUBLISH_GATE_THRESHOLDS["editorial_score"],
        "source_score": source_score >= _PUBLISH_GATE_THRESHOLDS["source_score"],
        "depth_score": depth_score >= _PUBLISH_GATE_THRESHOLDS["depth_score"],
        "evidence_score": evidence_score >= _PUBLISH_GATE_THRESHOLDS["evidence_score"],
    }
    for metric, passed in threshold_checks.items():
        if not passed:
            reasons.append(f"{metric}_below_threshold")

    if not bool(getattr(editorial_review, "ready_to_publish", False)):
        reasons.append("editorial_revision_pending")

    unique_reasons: list[str] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    publish = not unique_reasons
    review_reason = "" if publish else unique_reasons[0]

    metrics = {
        "confidence": confidence,
        "editorial_score": editorial_score,
        "source_score": source_score,
        "depth_score": depth_score,
        "evidence_score": evidence_score,
        "word_count": word_count,
        "section_count": section_count,
        "substantive_sections": substantive_sections,
        "source_count": len(sources_used),
        "evidence_claim_count": len(evidence_claims),
        "official_source_count": int(summary.get("official_source_count") or 0),
        "trusted_supporting_source_count": int(summary.get("trusted_supporting_source_count") or 0),
        "document_evidence_status": str(summary.get("document_evidence_status") or ""),
        "context_enrichment_status": str(summary.get("context_enrichment_status") or ""),
        "research_context_status": str(summary.get("research_context_status") or ""),
        "table_count": structured_counts["table_count"],
        "table_rows": structured_counts["table_rows"],
        "metric_count": structured_counts["metric_count"],
        "visual_count": structured_counts["visual_count"],
        "timeline_count": structured_counts["timeline_count"],
        "evidence_note_count": structured_counts["evidence_note_count"],
        "numeric_evidence_present": numeric_evidence_present,
        "research_dimensions": research_dimensions,
        "content_type": effective_content_type,
        "is_official_update": is_official_update,
    }

    return {
        "status": "publish" if publish else "draft",
        "score": confidence,
        "reasons": unique_reasons,
        "metrics": metrics,
        "review_reason": review_reason,
        "sources_used": sources_used,
    }


# ── Core generation function ──────────────────────────────────────────────────

async def generate_flash_article(
    req: FlashGenerationRequest,
    *,
    job_id: str,
    requested_by: str,
) -> ContentAutomationResult:
    """
    Run the flash/deep content pipeline and produce a publishable article.
    Called from the async background task started by POST /api/content/flash/generate.
    """
    route_base = _safe_route_base(req.route_base)
    effective_content_type = _effective_content_type(req)
    ikg_target = _normalise_ikg_target(req.target, effective_content_type)
    editorial_mode = "research"

    # Build slug from target + content_type
    slug_src = req.objective[:80] if req.objective else req.target[:80]
    slug = slugify(f"{req.content_type}-{slug_src}")

    # Return existing if no overwrite; version up if overwriting
    is_update = False
    from finagent.content_automation import load_generated_article
    if not req.overwrite:
        existing = load_generated_article(slug, route_base=route_base)
        if existing:
            return ContentAutomationResult.model_validate(existing)
    else:
        existing = load_generated_article(slug, route_base=route_base)
        if existing:
            is_update = True
            version = 2
            while load_generated_article(f"{slug}-v{version}", route_base=route_base):
                version += 1
            slug = f"{slug}-v{version}"

    if req.mode == "flash":
        objectives = _CONTENT_FLASH_OBJECTIVES
        wall_limit = _FLASH_WALL_SECONDS
    else:
        objectives = _CONTENT_DEEP_OBJECTIVES
        wall_limit = _DEEP_WALL_SECONDS
    total_passes = len(objectives)

    BUS.emit(
        job_id, "phase",
        phase="content_generation",
        note=f"{req.mode.upper()} mode — {total_passes} passes for '{req.target[:60]}'",
    )

    # ── IKG context (parallel pre-fetch) ─────────────────────────────────────
    ikg_ctx: dict[str, Any] = {}
    if ikg_target:
        try:
            ikg_ctx = await _build_ikg_context(ikg_target)
            if ikg_ctx.get("covered"):
                BUS.emit(job_id, "log", source="flash_engine", level="info",
                         message=f"Verified record coverage found: CIN={ikg_ctx.get('cin')} target='{ikg_target}'")
            else:
                BUS.emit(job_id, "log", source="flash_engine", level="info",
                         message=f"IKG not covering '{req.target}' — proceeding without IKG block")
        except Exception as exc:
            logger.warning("Verified records context failed: %s", exc)

    # ── Assemble enriched base objective ─────────────────────────────────────
    type_prefix_map = {
        "earnings": (
            f"Earnings analysis: '{req.target}'. "
            "Focus: quarterly/annual results, what changed versus the previous quarter and year, "
            "segment and geography drivers, margins, cash conversion, hiring/attrition, order book, "
            "and management commentary from official materials."
        ),
        "sebi": (
            f"SEBI regulatory article: '{req.target}'. "
            "Focus: the order timeline, enforcement actions, compliance implications, market impact, investor relevance, "
            "and whether this changes the risk profile or disclosure burden."
        ),
        "trend": (
            f"Market trend analysis: '{req.target}'. "
            "Focus: sector dynamics, macro drivers, institutional flows, thematic catalysts, official policy signals, "
            "and the listed companies most affected."
        ),
        "company": (
            f"Company intelligence article: '{req.target}'. "
            "Focus: business model, financials, governance, risks, catalysts, market positioning."
        ),
        "manual": (
            f"Financial article: '{req.target}'. "
            "Infer whether this is best treated as an earnings, company, or market-structure story and write accordingly."
        ),
    }
    base_obj = req.objective or type_prefix_map.get(effective_content_type, f"Article: '{req.target}'")
    initial_evidence_pack = _build_evidence_pack(req, ikg_ctx, {})

    extra_ctx = ""
    if req.source_markdown:
        extra_ctx += f"\n\n[PRIMARY SOURCE MATERIAL]\n{req.source_markdown[:14000]}"
    if req.source_evidence_meta:
        evidence_meta = {
            "document_type": req.source_evidence_meta.get("attachment_document_type"),
            "parser": req.source_evidence_meta.get("attachment_parser"),
            "attachment_required": req.source_evidence_meta.get("attachment_required"),
            "extraction_status": req.source_evidence_meta.get("attachment_extraction_status"),
            "sufficiency_reason": req.source_evidence_meta.get("attachment_sufficiency_reason"),
            "source_uid": req.source_evidence_meta.get("source_uid"),
        }
        extra_ctx += f"\n\n[PRIMARY SOURCE PROVENANCE]\n{json.dumps(evidence_meta, ensure_ascii=True, default=str)}"
    if req.source_url:
        extra_ctx += f"\n\n[SOURCE URL]: {req.source_url}"
    if ikg_ctx.get("narrative"):
        extra_ctx += (
            f"\n\n[COMPANY CONTEXT - complementary background only]\n{ikg_ctx['narrative']}\n"
            f"Context source: verified company records (CIN: {ikg_ctx.get('cin')})"
        )
    evidence_prompt_block = _evidence_pack_prompt_block(initial_evidence_pack)
    if evidence_prompt_block:
        extra_ctx += f"\n\n{evidence_prompt_block}"

    enriched_objective = base_obj + extra_ctx

    synth_model = os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-5.4-mini"
    fast_model = os.getenv("FINAGENT_SYNTH_MODEL_FAST") or "gpt-5.4-mini"

    # ── Pass runner ───────────────────────────────────────────────────────────
    async def _run_pass(i: int) -> None:
        is_last = (i == total_passes - 1)
        pass_label = "Final synthesis" if is_last else f"Research pass {i + 1}/{total_passes - 1}"
        pass_obj = objectives[i]

        BUS.emit(job_id, "flash_pass",
                 pass_number=i + 1,
                 total_passes=total_passes,
                 objective=pass_obj[:80],
                 label=pass_label,
                 status="running")

        cfg = AgentLoopConfig(
            max_steps=32 if is_last else 16,
            session_id=job_id,
            auto_depth=False,
            # Content generation is not a user chat session
            enable_memory=False,
            memory_recall_limit=0,
            enable_reflection=is_last,
            reflection_max_rounds=2 if is_last else 0,
            quality_threshold=70.0,
            reflection_per_query_limit=3 if is_last else 0,
            reflection_max_new_docs=24 if is_last else 0,
            reflection_max_queries_per_round=3 if is_last else 0,
            reflection_wall_clock_seconds=40.0 if is_last else 0.0,
            reflection_early_accept_margin=2.0,
            reflection_min_score_gain=0.75,
            enable_multi_agent=True,
            agent_deadline_ms=42_000 if is_last else 22_000,
            # Blindspot pass only on synthesis
            enable_blindspot=is_last,
            blindspot_max_queries=4 if is_last else 0,
            blindspot_per_query_timeout=15.0,
            # Models
            synth_model=synth_model if is_last else fast_model,
            response_depth="deep" if is_last else "standard",
            # For synthesis pass: output_mode=None so the objective text drives
            # format (the objective explicitly asks for JSON). Using "news_brief"
            # was causing the synthesiser's template to override the JSON instruction
            # and produce markdown instead of ContentArticlePackage JSON.
            output_mode=(
                None if is_last  # synthesis pass — objective drives JSON format
                else None  # research passes — no template override needed
            ),
            emit_memo=is_last,
            close_bus_on_finish=False,
            # Timeouts — tighter than full deep research
            breadth_search_timeout=70.0 if is_last else 22.0,
            followup_search_timeout=28.0 if is_last else 8.0,
            news_timeout=16.0 if is_last else 5.0,
            fast_mode=False,
            peer_targets=[],
            user_email=requested_by,
        )

        full_obj = f"{enriched_objective}\n\n{pass_label} — {pass_obj}"
        await run_research_session(
            req.target,
            full_obj,
            loop_config=cfg,
            is_followup=(i > 0),
        )

        BUS.emit(job_id, "flash_pass",
                 pass_number=i + 1,
                 total_passes=total_passes,
                 objective=pass_obj[:80],
                 label=pass_label,
                 status="done")

    # ── Execute passes ────────────────────────────────────────────────────────
    started_at = asyncio.get_running_loop().time()
    parallel_count = total_passes - 1

    if parallel_count > 0:
        BUS.emit(job_id, "phase", phase="content_generation",
                 note=f"Running {parallel_count} research passes in parallel")
        parallel_tasks = [asyncio.create_task(_run_pass(i)) for i in range(parallel_count)]
        parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
        for outcome in parallel_results:
            if isinstance(outcome, Exception):
                logger.warning("Research pass failed for job %s: %s", job_id, outcome)
                BUS.emit(job_id, "log", source="flash_engine", level="warning",
                         message=f"Research pass failed but synthesis will continue: {outcome}")

    elapsed = asyncio.get_running_loop().time() - started_at
    if elapsed > wall_limit:
        logger.warning(
            "Flash job %s hit wall limit %.0fs — synthesising with available context", job_id, wall_limit
        )

    await asyncio.sleep(0.3)
    BUS.emit(job_id, "phase", phase="content_generation", note="Running final article synthesis")
    await _run_pass(total_passes - 1)

    # ── Harvest memo + quality score ──────────────────────────────────────────
    memo = _harvest_memo(job_id)
    final_event = _harvest_final_event(job_id)
    quality_score = float(final_event.get("quality_score") or 0)
    evidence_pack = _build_evidence_pack(req, ikg_ctx, final_event)

    BUS.emit(job_id, "log", source="flash_engine", level="info",
             message=f"Synthesis complete — quality={quality_score:.1f}, memo_len={len(memo)}")

    # ── Assemble article ─────────────────────────────────────────────────────
    # Primary path: direct JSON call to OpenAI (structured article from research memo)
    # This bypasses the synthesiser's fixed markdown templates and produces proper
    # ContentArticlePackage JSON using the collected research as context.
    BUS.emit(job_id, "phase", phase="content_generation", note="Formatting article as structured JSON")
    article = await _direct_json_article_call(memo, ikg_ctx, req, slug, effective_content_type)

    if article is None:
        # Fallback: parse markdown memo into sections
        BUS.emit(job_id, "log", source="flash_engine", level="warning",
                 message="Direct JSON call failed — using markdown parser fallback")
        article = _assemble_article_from_pipeline(memo, ikg_ctx, req, slug, quality_score, effective_content_type)
    else:
        BUS.emit(job_id, "log", source="flash_engine", level="info",
                 message=f"Article JSON ready — {len(article.sections)} sections, {len(article.faqs)} FAQs")
    article = sanitize_article_package(article)
    baseline_words = _article_word_count(article)
    needs_revision = (
        baseline_words < 1100
        or len(article.sections) < 6
        or len(article.metrics) < 4
        or len(article.visuals) == 0
    )
    if needs_revision:
        BUS.emit(
            job_id,
            "log",
            source="flash_engine",
            level="info",
            message=(
                "Initial structured draft is thin; running one guided revision pass for depth, "
                "metrics coverage, and clearer watchpoints."
            ),
        )
        revision_note = (
            "Expand this into a full research article. Remove weak boilerplate and missing-data filler. "
            "Use concrete evidence and include historical framing, management commentary, market-sentiment read-through, "
            "governance or regulatory implications, and explicit watchpoints for next quarter. "
            "Ensure metrics >= 4, at least one meaningful table, and at least one numeric visual block."
        )
        revised_article = await _direct_json_article_call(
            memo,
            ikg_ctx,
            req,
            slug,
            effective_content_type,
            revision_note=revision_note,
        )
        if revised_article is not None:
            revised_article = sanitize_article_package(revised_article)
            revised_words = _article_word_count(revised_article)
            if (
                revised_words >= baseline_words
                or len(revised_article.metrics) > len(article.metrics)
                or len(revised_article.visuals) > len(article.visuals)
            ):
                article = revised_article
                BUS.emit(
                    job_id,
                    "log",
                    source="flash_engine",
                    level="info",
                    message=(
                        f"Guided revision accepted (words {baseline_words} -> {revised_words}; "
                        f"metrics {len(article.metrics)}; visuals {len(article.visuals)})."
                    ),
                )
    # ── Specialist research wave (10 parallel agents) ────────────────────────
    specialist_summary: dict[str, Any] = {}
    specialist_quality = 0
    if os.getenv("FINAGENT_SPECIALIST_WAVE_DISABLED", "").lower() not in {"1", "true", "yes"}:
        try:
            from finagent.content.specialist_agents import (
                run_specialist_wave,
                summarise_wave,
                wave_to_prompt_block,
            )
            llm_cfg_wave = resolve_openai_config(complexity="moderate")
            if llm_cfg_wave is not None:
                try:
                    import openai as _openai_wave
                    wave_client = _openai_wave.AsyncOpenAI(
                        api_key=llm_cfg_wave.api_key,
                        base_url=llm_cfg_wave.base_url,
                    )

                    async def _wave_llm(system_prompt: str, user_prompt: str) -> str:
                        resp = await wave_client.chat.completions.create(
                            model=os.getenv("FINAGENT_SPECIALIST_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or llm_cfg_wave.model or "gpt-5.4-mini",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=0.25,
                            max_completion_tokens=900,
                            response_format={"type": "json_object"},
                            timeout=40,
                        )
                        return (resp.choices[0].message.content or "").strip()

                    context_blob = (req.source_markdown or "")[:3500]
                    if ikg_ctx.get("narrative"):
                        context_blob += "\n\n" + str(ikg_ctx.get("narrative") or "")[:2500]
                    memos = await run_specialist_wave(req.target, context_blob, _wave_llm, timeout_s=42.0)
                    specialist_summary = summarise_wave(memos)
                    specialist_quality = int(specialist_summary.get("quality_score") or 0)
                    wave_block = wave_to_prompt_block(memos)
                    if wave_block:
                        evidence_pack.setdefault("summary", {})
                        evidence_pack["summary"]["specialist_kinds_covered"] = specialist_summary.get("kinds_covered", [])
                        evidence_pack["specialist_memos"] = [m.to_dict() for m in memos.values()]
                    BUS.emit(
                        job_id, "log", source="flash_engine", level="info",
                        message=(
                            f"Specialist wave covered {len(specialist_summary.get('kinds_covered') or [])}/10; "
                            f"quality_score={specialist_quality}"
                        ),
                    )
                except Exception as exc:
                    logger.warning("Specialist wave failed: %s", exc)
        except Exception as exc:
            logger.warning("Specialist wave module unavailable: %s", exc)

    BUS.emit(job_id, "phase", phase="content_generation", note="Running editorial review and revision")
    # Strip any Livemint URLs from the evidence pack before review/gate — Livemint
    # is never an allowed source on the public surface, even when other trusted
    # press is permitted as supporting context.
    from finagent.content.livemint_blocker import sanitise_evidence_pack
    evidence_pack, livemint_dropped = sanitise_evidence_pack(evidence_pack)
    if livemint_dropped:
        BUS.emit(
            job_id,
            "log",
            source="flash_engine",
            level="warning",
            message=f"Dropped {livemint_dropped} Livemint source(s) from evidence pack before publish gate.",
        )
    pre_evidence_claims = _build_evidence_claims(article, evidence_pack)
    is_official_source = _is_official_update_request(req)
    blended_quality = max(int(round(max(quality_score, 0.0))), int(specialist_quality or 0))
    article, editorial_review = await run_editorial_revision_loop(
        article,
        target=req.target,
        max_rounds=4,
        is_official_source=is_official_source,
        quality_score=blended_quality,
        evidence_claim_count=len(pre_evidence_claims),
        livemint_source_violations=livemint_dropped,
    )
    article = sanitize_article_package(article)
    editorial_score = editorial_review.total_score
    urgency_score = editorial_review.urgency_score
    combined_quality = int(round((max(quality_score, 0.0) * 0.30) + (editorial_score * 0.70)))
    evidence_claims = _build_evidence_claims(article, evidence_pack)
    article = _inject_structured_presentation(
        article,
        req=req,
        evidence_pack=evidence_pack,
        evidence_claims=evidence_claims,
    )
    article = sanitize_article_package(article)
    evidence_claims = _build_evidence_claims(article, evidence_pack)

    # ── Fact triangulation ────────────────────────────────────────────────────
    article_text = _article_plain_text(article)
    fact_claims = extract_numeric_claims(article_text)
    enrichment_data = evidence_pack.get("enrichment") or evidence_pack.get("ikg") or {}
    if isinstance(enrichment_data, dict):
        fact_claims = triangulate_claims(fact_claims, enrichment_data)
    conflicting_facts = [c for c in fact_claims if c.status == "conflicting"]
    single_source_facts = [c for c in fact_claims if c.status == "single_source"]
    if conflicting_facts:
        logger.warning("[FACT-CHECK] %d conflicting claims found for %s", len(conflicting_facts), req.target)

    publish_gate = _evaluate_publish_gate(
        req=req,
        article=article,
        editorial_review=editorial_review,
        quality_score=combined_quality,
        evidence_pack=evidence_pack,
        evidence_claims=evidence_claims,
    )
    if specialist_summary:
        gate_metrics = publish_gate.setdefault("metrics", {})
        gate_metrics["specialist_quality_score"] = int(specialist_quality or 0)
        gate_metrics["specialist_kinds_covered"] = list(specialist_summary.get("kinds_covered") or [])
        gate_metrics["specialist_kinds_failed"] = list(specialist_summary.get("kinds_failed") or [])
    if livemint_dropped:
        publish_gate.setdefault("metrics", {})["livemint_sources_dropped"] = int(livemint_dropped)
    confidence = int(publish_gate.get("score") or 0)
    reasons = list(publish_gate.get("reasons") or [])
    publish_status = "published" if str(publish_gate.get("status") or "draft") == "publish" else "draft"
    review_reason = str(publish_gate.get("review_reason") or "")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if is_update:
        article = article.model_copy(update={
            "hero_summary": f"[Updated] {article.hero_summary}",
        })

    # ── Render HTML + image ───────────────────────────────────────────────────
    fake_req = ContentAutomationRequest(
        topic=req.target,
        slug=slug,
        include_image=bool(req.include_image or publish_status == "published"),
        route_base=route_base,
        force_publish=req.force_publish,
    )
    image_bytes, image_ext, image_mime, cover_provider = await _generate_cover_for_article(
        fake_req,
        article,
        route_base,
        publish_status=publish_status,
    )
    image_name = f"cover{image_ext}"
    public_url = f"{_SITE_URL}/{route_base}/{slug}/"
    img_href = f"/{route_base}/{slug}/{image_name}"
    html_text = render_article_html(
        article,
        public_url,
        img_href,
        generated_at,
        meta={
            "content_type": effective_content_type,
            "mode": editorial_mode,
            "quality_score": combined_quality,
            "ikg_covered": bool(ikg_ctx.get("covered")),
            "sources_used": list(evidence_pack.get("sources_used") or []),
            "hub_path": f"/{route_base}/research/" if route_base == "insights" else f"/{route_base}/",
        },
    )

    # ── Persist files ─────────────────────────────────────────────────────────
    adir = _article_dir(route_base, slug)
    html_path = adir / "index.html"
    json_path = adir / "article.json"
    img_path = adir / image_name
    _write_bytes(img_path, image_bytes)

    # ── Render real chart PNGs from article visuals ──────────────────────────
    try:
        from finagent.output.chart_generator import generate_article_visual
        article_visuals = list(article.visuals or []) if hasattr(article, "visuals") else []
        for vi, visual in enumerate(article_visuals):
            vdata = visual.model_dump() if hasattr(visual, "model_dump") else (visual if isinstance(visual, dict) else {})
            pts = vdata.get("points") or []
            if len(pts) < 2:
                continue
            chart_filename = f"chart_{vi}.png"
            chart_path = str(adir / chart_filename)
            result_chart = generate_article_visual(vdata, output_path=chart_path)
            if result_chart:
                if publish_status == "published":
                    for pub_dir in _public_article_dirs(route_base, slug):
                        pub_chart = pub_dir / chart_filename
                        pub_chart.parent.mkdir(parents=True, exist_ok=True)
                        import shutil
                        if Path(chart_path).exists():
                            shutil.copy2(chart_path, str(pub_chart))
    except Exception:
        logger.debug("Chart rendering skipped: %s", slug, exc_info=True)

    _write_text(html_path, html_text)

    # ── Score publishability ──────────────────────────────────────────────────
    if not reasons:
        reasons = [
            f"publish_gate_passed_{confidence}",
            f"editorial_{editorial_score}",
            f"urgency_{urgency_score}",
        ]

    # ── Mirror to public if publishing ────────────────────────────────────────
    public_mirror: str | None = None
    sitemap: str | None = None
    if publish_status == "published":
        try:
            pub_dirs = _public_article_dirs(route_base, slug)
            for pub_dir in pub_dirs:
                _write_text(pub_dir / "index.html", html_text)
                _write_bytes(pub_dir / image_name, image_bytes)
            public_mirror = str(pub_dirs[0])
            sitemap = _upsert_sitemap(route_base, slug)
            refresh_public_research_hub(route_base)
            submit_sitemap()
        except Exception:
            logger.exception("Public mirror failed for %s/%s", route_base, slug)

    result = ContentAutomationResult(
        slug=slug,
        title=article.title,
        description=article.description,
        route_base=route_base,
        public_url=public_url,
        html_path=str(html_path),
        json_path=str(json_path),
        image_path=str(img_path),
        image_mime=image_mime,
        cover_provider=cover_provider,
        generated_at=generated_at,
        sources_used=[
            {
                "title": str(source.get("title") or ""),
                "url": str(source.get("url") or ""),
            }
            for source in list(publish_gate.get("sources_used") or [])
        ],
        confidence_score=confidence,
        publish_status=publish_status,
        publish_reasons=reasons,
        mirrored_public_path=public_mirror,
        mirrored_sitemap=sitemap,
    )

    # Save JSON manifest
    manifest = {
        **result.model_dump(),
        "requested_by": requested_by,
        "job_id": job_id,
        "mode": editorial_mode,
        "content_type": effective_content_type,
        "requested_content_type": req.content_type,
        "quality_score": combined_quality,
        "image_mime": image_mime,
        "cover_provider": cover_provider,
        "ikg_covered": ikg_ctx.get("covered", False),
        "source_evidence_meta": req.source_evidence_meta or {},
        "publish_gate": publish_gate,
        "publish_gate_status": publish_gate.get("status") or "draft",
        "publish_gate_score": publish_gate.get("score") or 0,
        "evidence_pack_summary": evidence_pack.get("summary") or {},
        "evidence_claims": evidence_claims,
        "review_reason": review_reason,
        "sources_used": list(publish_gate.get("sources_used") or []),
        "editorial_review": editorial_review.to_dict(),
        "article": article.model_dump(),
    }
    _write_text(json_path, json.dumps(manifest, indent=2, ensure_ascii=True))

    BUS.emit(job_id, "content_done",
             slug=slug,
             title=article.title,
             public_url=public_url,
             publish_status=publish_status,
             publish_gate_status=publish_gate.get("status") or "draft",
             publish_gate_score=publish_gate.get("score") or 0,
             review_reason=review_reason,
             confidence_score=confidence,
             quality_score=combined_quality,
             editorial_score=editorial_score,
             urgency_score=urgency_score)

    return result


# ── Event ingestion (SEBI + earnings) via flash pipeline ─────────────────────

async def ingest_events_flash(
    req: FlashIngestRequest,
    *,
    requested_by: str,
    job_id: str,
) -> FlashIngestResult:
    """
    Discover SEBI / BSE / NSE events and route each one through the flash
    pipeline for high-quality article generation. Reuses v1 dedup state.
    """
    from finagent.news.sources.bse_announcements import fetch_bse_announcements
    from finagent.news.sources.nse_announcements import fetch_nse_announcements
    from finagent.news.sources.sebi_rss import fetch_sebi_news
    from finagent.content_automation import ContentEventWatch

    route_base = _safe_route_base(req.route_base)
    state = _load_event_state()
    seen_event_ids: dict[str, str] = state.setdefault("seen_event_ids", {})

    failures: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    discovered = skipped = generated = published_count = draft_count = 0

    events_queue: list[tuple[str, dict[str, Any], str, str]] = []
    # (source, raw_event, target_label, content_type)

    # ── Gather SEBI events ────────────────────────────────────────────────────
    if req.content_type in ("sebi", "trend"):
        try:
            items = await asyncio.to_thread(fetch_sebi_news, req.max_events_per_source)
            for item in items:
                discovered += 1
                watch = ContentEventWatch(source="sebi")
                fid = _event_fingerprint("sebi", item, watch)
                if seen_event_ids.get(fid):
                    skipped += 1
                    continue
                seen_event_ids[fid] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                title = str(item.get("title") or "SEBI Update")[:160]
                events_queue.append(("sebi", item, f"SEBI: {title}", "sebi"))
        except Exception as exc:
            failures.append({"source": "sebi", "error": str(exc)[:400]})

    # ── Gather BSE events ─────────────────────────────────────────────────────
    for code in req.bse_codes:
        try:
            items = await asyncio.to_thread(
                fetch_bse_announcements, code, req.max_events_per_source
            )
            for item in items:
                discovered += 1
                watch = ContentEventWatch(source="bse", bse_scrip_code=code)
                fid = _event_fingerprint("bse", item, watch)
                if seen_event_ids.get(fid):
                    skipped += 1
                    continue
                seen_event_ids[fid] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                title = str(item.get("title") or "BSE Announcement")[:160]
                events_queue.append(("bse", item, f"{code}: {title}", "earnings"))
        except Exception as exc:
            failures.append({"source": "bse", "code": code, "error": str(exc)[:400]})

    # ── Gather NSE events ─────────────────────────────────────────────────────
    for isin in req.isin_list:
        try:
            items = await asyncio.to_thread(
                fetch_nse_announcements, isin, req.max_events_per_source
            )
            for item in items:
                discovered += 1
                watch = ContentEventWatch(source="nse", isin=isin)
                fid = _event_fingerprint("nse", item, watch)
                if seen_event_ids.get(fid):
                    skipped += 1
                    continue
                seen_event_ids[fid] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                title = str(item.get("title") or "NSE Announcement")[:160]
                events_queue.append(("nse", item, f"{isin}: {title}", "earnings"))
        except Exception as exc:
            failures.append({"source": "nse", "isin": isin, "error": str(exc)[:400]})

    _save_event_state(state)

    if req.dry_run:
        return FlashIngestResult(
            route_base=route_base,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            discovered_events=discovered,
            skipped_seen=skipped,
            failures=failures,
        )

    # ── Process events via flash pipeline (bounded concurrency) ──────────────
    sem = asyncio.Semaphore(2)

    async def _process(src: str, event: dict, label: str, ctype: str) -> None:
        nonlocal generated, published_count, draft_count
        async with sem:
            sub_id = uuid.uuid4().hex[:12]
            BUS.open(sub_id, reset=True)
            try:
                gen_req = FlashGenerationRequest(
                    mode=req.mode,
                    content_type=ctype,  # type: ignore[arg-type]
                    target=label[:200],
                    source_url=str(event.get("url") or "") or None,
                    source_markdown=(event.get("snippet") or "")[:8000] or None,
                    route_base=route_base,
                    include_image=req.include_image,
                )
                r = await generate_flash_article(gen_req, job_id=sub_id, requested_by=requested_by)
                generated += 1
                if r.publish_status == "published":
                    published_count += 1
                else:
                    draft_count += 1
                results.append(r.model_dump())
                BUS.emit(job_id, "ingest_item_done",
                         slug=r.slug, title=r.title, publish_status=r.publish_status)
            except Exception as exc:
                logger.exception("Flash ingest failed for %r", label)
                failures.append({"target": label, "error": str(exc)[:400]})
            finally:
                BUS.close(sub_id)

    await asyncio.gather(
        *[_process(*e) for e in events_queue],
        return_exceptions=True,
    )

    return FlashIngestResult(
        route_base=route_base,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        discovered_events=discovered,
        generated_articles=generated,
        auto_published=published_count,
        drafts=draft_count,
        skipped_seen=skipped,
        failures=failures,
        items=results,
    )


# ── Public hub HTML builder ───────────────────────────────────────────────────

def build_insights_hub_html(route_base: str = "insights") -> str:
    """
    Render the SEO landing page at /insights/research/
    listing all published articles, styled to match the app theme.
    """
    return _build_insights_hub_html_editorial(route_base=route_base)

    from finagent.content_automation import list_generated_articles

    articles = list_generated_articles(route_base=route_base, limit=120)
    published = [
        a for a in articles
        if str(a.get("publish_status") or "").lower() == "published"
        and str(a.get("publish_gate_status") or "").lower() == "publish"
    ]
    drafts = [a for a in articles if a.get("publish_status") != "published"]
    total = len(articles)
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # ── helpers ──────────────────────────────────────────────────────────────
    _BADGE_COLORS = {
        "earnings": ("#34D399", "#0a2d1e"),
        "sebi":     ("#FB7185", "#2d0a12"),
        "trend":    ("#60A5FA", "#0a1a2d"),
        "company":  ("#A78BFA", "#1a0a2d"),
        "manual":   ("#94A3B8", "#141b24"),
    }

    def _type_badge(ct: str) -> str:
        fg, bg = _BADGE_COLORS.get(ct, ("#94A3B8", "#141b24"))
        label = html.escape(ct or "insight").upper()
        return (
            f'<span style="display:inline-block;font-size:10px;font-weight:700;'
            f'letter-spacing:.08em;color:{fg};padding:3px 9px;border-radius:5px;'
            f'background:{bg};border:1px solid {fg}33;">{label}</span>'
        )

    def _mode_icon(mode: str) -> str:
        return "⚡" if mode == "flash" else "🔬" if mode == "deep" else "📄"

    def _card(a: dict) -> str:
        title = html.escape(str(a.get("title") or "Untitled"))
        desc = html.escape(str(a.get("description") or a.get("meta_description") or "")[:160])
        url = html.escape(str(a.get("public_url") or "#"))
        date_str = str(a.get("generated_at") or "")[:10]
        score = int(a.get("confidence_score") or a.get("quality_score") or 0)
        ct = str(a.get("content_type") or "")
        mode = str(a.get("mode") or "")
        ikg = bool(a.get("ikg_covered"))
        badge = _type_badge(ct)
        mode_icon = _mode_icon(mode)
        score_color = "#34D399" if score >= 80 else "#60A5FA" if score >= 68 else "#94A3B8"
        ikg_badge = (
            '<span style="font-size:10px;color:#7dd3fc;background:rgba(125,211,252,.1);'
            'border:1px solid rgba(125,211,252,.25);padding:2px 7px;border-radius:4px;'
            'margin-left:4px;">IKG</span>'
            if ikg else ""
        )
        return (
            f'<a href="{url}" style="display:block;padding:24px;border-radius:16px;'
            f'border:1px solid rgba(145,180,230,.14);background:rgba(10,21,38,.85);'
            f'text-decoration:none;color:#f6f8fc;transition:border-color .18s,transform .15s;'
            f'backdrop-filter:blur(8px);" '
            f'onmouseover="this.style.borderColor=\'rgba(125,211,252,.35)\';this.style.transform=\'translateY(-2px)\'" '
            f'onmouseout="this.style.borderColor=\'rgba(145,180,230,.14)\';this.style.transform=\'none\'">'
            f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;">'
            f'{badge}{ikg_badge}'
            f'<span style="margin-left:auto;font-size:10px;color:#5f7a9a;">{html.escape(date_str)}</span>'
            f'<span style="font-size:11px;">{mode_icon}</span>'
            f'</div>'
            f'<div style="font-size:1rem;font-weight:600;line-height:1.35;margin-bottom:8px;">{title}</div>'
            f'<div style="font-size:.85rem;color:#aab6cb;line-height:1.5;margin-bottom:14px;">{desc}</div>'
            f'<div style="font-size:11px;color:{score_color};">Quality score: {score}</div>'
            f'</a>'
        )

    if published:
        cards_html = (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px;">'
            + "\n".join(_card(a) for a in published)
            + "</div>"
        )
    else:
        cards_html = (
            '<div style="text-align:center;padding:80px 0;">'
            '<div style="font-size:3rem;margin-bottom:16px;">🔬</div>'
            '<p style="color:#aab6cb;font-size:1.05rem;margin-bottom:8px;">No articles published yet.</p>'
            '<p style="color:#5f7a9a;font-size:.9rem;">The engine is running — check back soon or visit the '
            '<a href="/#/insights-studio" style="color:#7dd3fc;text-decoration:none;">Insights Studio</a> '
            'to generate and publish the first article.</p>'
            '</div>'
        )

    # Schema.org JSON-LD
    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": "ProspektLab AI Research Hub — Indian Market Intelligence",
        "description": (
            "The most accurate AI-generated financial analysis on Indian markets — "
            "earnings results, SEBI orders, sector trends — powered by the "
            "ProspektLab Indian Knowledge Graph and 8-phase research pipeline."
        ),
        "url": f"{_SITE_URL}/insights/research/",
        "publisher": {
            "@type": "Organization",
            "name": "ProspektLab",
            "url": f"{_SITE_URL}/",
        },
    }, ensure_ascii=True)

    return (
        "<!doctype html>\n"
        '<html lang="en-IN">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        '  <meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
        "  <title>ProspektLab AI Research Hub — Indian Market Intelligence</title>\n"
        f'  <meta name="description" content="The most accurate AI-generated financial analysis on Indian markets — earnings results, SEBI orders, sector trends — powered by the ProspektLab Indian Knowledge Graph and 8-phase research pipeline."/>\n'
        '  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1"/>\n'
        f'  <link rel="canonical" href="{html.escape(_SITE_URL)}/insights/research/"/>\n'
        '  <link rel="icon" type="image/svg+xml" href="/prospektlab-favicon-v2.svg"/>\n'
        '  <meta property="og:type" content="website"/>\n'
        '  <meta property="og:title" content="ProspektLab AI Research Hub — Indian Market Intelligence"/>\n'
        '  <meta property="og:description" content="Highest-accuracy AI financial analysis for Indian markets."/>\n'
        f'  <meta property="og:url" content="{html.escape(_SITE_URL)}/insights/research/"/>\n'
        '  <meta name="twitter:card" content="summary_large_image"/>\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
        '  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&amp;display=swap" rel="stylesheet"/>\n'
        f'  <script type="application/ld+json">{schema}</script>\n'
        "  <style>\n"
        "    * { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "    body {\n"
        "      font-family: Inter, -apple-system, BlinkMacSystemFont, Arial, sans-serif;\n"
        "      background: #03101f;\n"
        "      background-image: radial-gradient(ellipse at 20% 0%, rgba(96,165,250,.07) 0%, transparent 60%),\n"
        "                        radial-gradient(ellipse at 80% 20%, rgba(167,139,250,.05) 0%, transparent 50%);\n"
        "      color: #f6f8fc;\n"
        "      line-height: 1.7;\n"
        "      min-height: 100vh;\n"
        "    }\n"
        "    a { color: inherit; text-decoration: none; }\n"
        "    .shell { width: min(calc(100% - 32px), 1160px); margin: 0 auto; padding: 32px 0 80px; }\n"
        "    @media (max-width: 600px) { .stats-row { flex-wrap: wrap !important; gap: 16px !important; } }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="shell">\n'
        # ── NAV ──
        '  <nav style="display:flex;align-items:center;justify-content:space-between;'
        'padding:16px 0 36px;border-bottom:1px solid rgba(145,180,230,.1);margin-bottom:48px;">\n'
        '    <div style="display:flex;align-items:center;gap:10px;">\n'
        '      <div style="width:8px;height:8px;border-radius:50%;background:#7dd3fc;'
        'box-shadow:0 0 10px rgba(125,211,252,.5);"></div>\n'
        '      <span style="font-weight:800;font-size:14px;letter-spacing:.08em;'
        'text-transform:uppercase;color:#f6f8fc;">ProspektLab</span>\n'
        '    </div>\n'
        '    <div style="display:flex;gap:24px;align-items:center;">\n'
        f'      <a href="{html.escape(_SITE_URL)}/#/" style="font-size:13px;color:#aab6cb;'
        'transition:color .15s;" onmouseover="this.style.color=\'#7dd3fc\'" '
        'onmouseout="this.style.color=\'#aab6cb\'">App</a>\n'
        '    </div>\n'
        '  </nav>\n'
        # ── HERO ──
        '  <div style="text-align:center;padding:8px 0 56px;">\n'
        '    <div style="display:inline-flex;padding:5px 14px;border-radius:999px;'
        'background:rgba(96,165,250,.08);border:1px solid rgba(125,211,252,.2);'
        'color:#7dd3fc;font-size:11px;font-weight:700;text-transform:uppercase;'
        'letter-spacing:.12em;margin-bottom:24px;">ProspektLab AI Research</div>\n'
        '    <h1 style="font-size:clamp(2.2rem,5vw,3.8rem);font-weight:800;'
        'letter-spacing:-.04em;line-height:1.08;margin-bottom:18px;'
        'background:linear-gradient(135deg,#f6f8fc 30%,#7dd3fc);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;">'
        'Indian Market Intelligence Hub</h1>\n'
        '    <p style="color:#aab6cb;font-size:1.05rem;max-width:56ch;margin:0 auto 48px;line-height:1.65;">'
        'The most accurate AI-generated financial analysis — earnings results, SEBI orders, '
        'sector trends — powered by the ProspektLab Indian Knowledge Graph and 8-phase research pipeline.'
        '</p>\n'
        # ── STATS ──
        '    <div class="stats-row" style="display:flex;justify-content:center;gap:40px;margin-bottom:0;flex-wrap:wrap;">\n'
        f'      <div style="text-align:center;">'
        f'<div style="font-size:2.4rem;font-weight:800;color:#7dd3fc;letter-spacing:-.04em;">{len(published)}</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Articles Published</div>'
        '</div>\n'
        f'      <div style="text-align:center;">'
        '<div style="font-size:2.4rem;font-weight:800;color:#7dd3fc;letter-spacing:-.04em;">8</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Research Passes</div>'
        '</div>\n'
        f'      <div style="text-align:center;">'
        f'<div style="font-size:2.4rem;font-weight:800;color:#7dd3fc;letter-spacing:-.04em;">{total}</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Total Generated</div>'
        '</div>\n'
        '      <div style="text-align:center;">'
        '<div style="font-size:2.4rem;font-weight:800;color:#34D399;letter-spacing:-.04em;">IKG</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Knowledge Graph</div>'
        '</div>\n'
        '    </div>\n'
        '  </div>\n'
        # ── CAPABILITY PILLS ──
        '  <div style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:48px;">\n'
        + "".join(
            f'  <span style="padding:6px 14px;border-radius:999px;font-size:12px;font-weight:500;'
            f'background:rgba(145,180,230,.06);border:1px solid rgba(145,180,230,.12);color:#aab6cb;">'
            f'{label}</span>\n'
            for label in [
                "⚡ Flash mode (2 min)", "🔬 Deep mode (8 min)", "📊 SEBI-safe analysis",
                "🏦 IKG ownership data", "💰 Earnings deep-dives", "🚨 Regulatory orders",
            ]
        )
        + "  </div>\n"
        # ── DIVIDER / SECTION HEADING ──
        + (
            '  <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">\n'
            '    <div style="font-size:.75rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#5f7a9a;">Latest Research</div>\n'
            '    <div style="flex:1;height:1px;background:rgba(145,180,230,.1);"></div>\n'
            f'    <div style="font-size:.72rem;color:#5f7a9a;">Updated {html.escape(now_str)}</div>\n'
            '  </div>\n'
        )
        # ── ARTICLE GRID ──
        + f"  {cards_html}\n"
        # ── FOOTER ──
        + '  <footer style="padding:48px 0 24px;text-align:center;border-top:1px solid rgba(145,180,230,.08);margin-top:64px;">\n'
        f'    <div style="display:flex;justify-content:center;gap:24px;margin-bottom:16px;">\n'
        f'      <a href="{html.escape(_SITE_URL)}/#/" style="font-size:13px;color:#7dd3fc;">ProspektLab App</a>\n'
        f'      <a href="/{html.escape(route_base)}/" style="font-size:13px;color:#7dd3fc;">All Insights</a>\n'
        '    </div>\n'
        '    <p style="font-size:.75rem;color:#3a4d62;max-width:60ch;margin:0 auto;">\n'
        '      ProspektLab AI Research. Educational content only — not investment advice.\n'
        '      No buy/sell/hold recommendation is made or implied.\n'
        '    </p>\n'
        '  </footer>\n'
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


build_insights_hub_html = _build_insights_hub_html_editorial
