"""
IKG Query Test v2 — tests post-fix IKG quality.
- Different company (HDFCBANK) for fresh perspective
- Checks graph build results (vertices/edges)
- Checks Qdrant indexing progress
- End-to-end answer quality check
"""
import json, os, sys, time, datetime, logging
import httpx

logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)

SYMBOL  = "HDFCBANK"
COMPANY = "HDFC Bank Ltd."
QUERY   = ("Analyse HDFC Bank's financial performance, NIM trends, deposit growth, "
           "credit quality and management commentary on loan book strategy")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
DB_URL     = os.environ.get("IKG_DATABASE_URL",
                "postgresql://ikg_user:ikg_password_change_me@postgres:5432/ikg")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
SYNTH_MODEL = os.environ.get("FINAGENT_SYNTH_MODEL", "gpt-4o")

print("=" * 72)
print("IKG END-TO-END QUERY TEST v2  (post-fix)")
print("=" * 72)
print("Company :", COMPANY, "(%s)" % SYMBOL)
print("Query   :", QUERY[:80])
print()

def epoch_ms_to_date(ms):
    try: return datetime.datetime.utcfromtimestamp(int(ms)/1000).strftime("%b %Y")
    except: return str(ms)

def cr(val):
    if val is None: return "N/A"
    try: return "%.0f Cr" % (float(val)/1e7)
    except: return str(val)

def pct(val):
    if val is None: return "N/A"
    try: return "%.1f%%" % float(val)
    except: return str(val)

# ── 1. IKG Graph Stats ────────────────────────────────────────────────────────
print("── 0. IKG Graph Stats (post graph-build fix)")
import psycopg
from psycopg.rows import dict_row
with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM ikg_vertices) AS vertices,
              (SELECT COUNT(*) FROM ikg_edges) AS edges,
              (SELECT COUNT(*) FROM ikg_facts) AS facts,
              (SELECT COUNT(*) FROM ikg_canonical_entities) AS entities,
              (SELECT COUNT(DISTINCT label) FROM ikg_vertices) AS vertex_types
        """)
        g = cur.fetchone()
print("  Vertices        :", g["vertices"])
print("  Edges           :", g["edges"])
print("  Facts           :", g["facts"])
print("  Canonical ents  :", g["entities"])
print("  Vertex types    :", g["vertex_types"])
print()

# ── 2. Qdrant Index Stats ─────────────────────────────────────────────────────
print("── 1. Qdrant Index Stats")
try:
    r = httpx.get(f"{QDRANT_URL}/collections/ikg_document_sections", timeout=10)
    if r.status_code == 200:
        info = r.json().get("result", {})
        pts = info.get("points_count") or info.get("vectors_count") or 0
        print("  Qdrant points   :", pts)
    else:
        print("  Qdrant HTTP", r.status_code)
except Exception as e:
    print("  Qdrant unavailable:", e)
print()

# ── 3. Entity Resolution ──────────────────────────────────────────────────────
print("── 2. Entity Resolution")
t0 = time.time()
from finagent.ikg.entity_resolver import get_entity_resolver
entity = get_entity_resolver().resolve(SYMBOL)
if entity is None:
    print("  ERROR: Entity not found for", SYMBOL)
    sys.exit(1)
bse   = getattr(entity, "bse_scrip_code", None) or ""
isin  = getattr(entity, "isin", None) or ""
cin   = getattr(entity, "cin", None) or ""
sector = getattr(entity, "sector", None) or ""
print("  BSE scrip :", bse, "| ISIN:", isin)
print("  CIN       :", cin or "N/A", "| Sector:", sector)
print("  Resolved in %.2fs" % (time.time()-t0))
print()

# ── 4. Financial Data ─────────────────────────────────────────────────────────
print("── 3. Financial Data (Postgres)")
with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              jsonb_each.key AS period_ms,
              jsonb_each.value AS metrics
            FROM company_financials cf,
                 jsonb_each(income_statement_json)
            WHERE cf.nse_symbol = %s
            ORDER BY jsonb_each.key::bigint DESC
            LIMIT 6
        """, (SYMBOL,))
        fin_rows = cur.fetchall()

if fin_rows:
    print("  Found %d income statement periods:" % len(fin_rows))
    for r in fin_rows:
        m = r["metrics"] if isinstance(r["metrics"], dict) else json.loads(r["metrics"])
        # Case-insensitive key lookup for yfinance TitleCase vs screener snake_case
        m_lower = {k.lower(): v for k, v in m.items()}
        rev = (m_lower.get("total revenue") or m_lower.get("net_sales") or
               m_lower.get("net interest income") or m_lower.get("interest income") or
               m_lower.get("operating revenue"))
        pat = (m_lower.get("net income") or m_lower.get("net_profit") or
               m_lower.get("profit_after_tax"))
        print("    %s  Rev/NII: %s  PAT: %s" % (
            epoch_ms_to_date(r["period_ms"]), cr(rev), cr(pat)
        ))
else:
    print("  No financial data found for", SYMBOL)
print()

# ── 5. Concall Transcripts ────────────────────────────────────────────────────
print("── 4. Concall Transcripts")
with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT quarter_label, fiscal_year, announced_at, sentiment_label,
                   char_length(transcript_text) AS text_len,
                   intent_tags_json AS tags
            FROM concall_transcripts_raw
            WHERE symbol = %s
            ORDER BY announced_at DESC
            LIMIT 6
        """, (SYMBOL,))
        calls = cur.fetchall()
print("  Found %d concall transcripts" % len(calls))
for c in calls:
    print("    %s  %s  sentiment=%s  chars=%s  tags=%s" % (
        c["quarter_label"], c["fiscal_year"],
        c["sentiment_label"] or "?",
        c["text_len"],
        (c["tags"] or [])[:3]
    ))
print()

# ── 6. Shareholding Pattern ───────────────────────────────────────────────────
print("── 5. Shareholding Pattern")
with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT quarter, total_promoter_holding_pct, total_pledge_pct,
                   fii_holding_pct, dii_holding_pct, public_holding_pct
            FROM shp_raw
            WHERE scrip_code = %s
            ORDER BY quarter DESC
            LIMIT 6
        """, (bse,))
        shp = cur.fetchall()
print("  Found %d SHP quarters for scrip %s" % (len(shp), bse))
for s in shp:
    print("    Q%s  Promoter: %s  Pledge: %s  FII: %s  DII: %s  Public: %s" % (
        s["quarter"],
        pct(s["total_promoter_holding_pct"]),
        pct(s["total_pledge_pct"]),
        pct(s["fii_holding_pct"]),
        pct(s["dii_holding_pct"]),
        pct(s["public_holding_pct"])
    ))
print()

# ── 7. Qdrant Semantic Search ─────────────────────────────────────────────────
print("── 6. Qdrant Semantic Search")
embed_resp = httpx.post(
    "https://api.openai.com/v1/embeddings",
    headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
    json={"model": "text-embedding-3-small", "input": QUERY},
    timeout=30,
)
qdrant_chunks = []
if embed_resp.status_code == 200:
    vec = embed_resp.json()["data"][0]["embedding"]
    q_resp = httpx.post(
        f"{QDRANT_URL}/collections/ikg_document_sections/points/search",
        json={
            "vector": vec,
            "filter": {"must": [{"key": "nse_symbol", "match": {"value": SYMBOL}}]},
            "limit": 12,
            "with_payload": True,
        },
        timeout=30,
    )
    if q_resp.status_code == 200:
        qdrant_chunks = q_resp.json().get("result", [])
print("  Qdrant chunks found: %d" % len(qdrant_chunks))
for c in qdrant_chunks[:4]:
    pl = c.get("payload", {})
    print("    [%.3f] %s / %s | %d chars" % (
        c.get("score",0), pl.get("document_type","?"),
        pl.get("section_type","?"), len(pl.get("text",""))
    ))
print()

# ── 8. Synthesis with GPT-4o ──────────────────────────────────────────────────
print("── 7. GPT-4o Answer Synthesis")

# Build context from all data sources
context_parts = []

# Financial context
if fin_rows:
    fin_summary = []
    for r in fin_rows:
        m = r["metrics"] if isinstance(r["metrics"], dict) else json.loads(r["metrics"])
        fin_summary.append(f"Period {epoch_ms_to_date(r['period_ms'])}: " +
            ", ".join(f"{k}={cr(v)}" for k, v in list(m.items())[:8] if v is not None))
    context_parts.append("FINANCIAL DATA (Screener/YFinance):\n" + "\n".join(fin_summary))

# Concall context
if calls:
    call_texts = []
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT quarter_label, announced_at, transcript_text
                FROM concall_transcripts_raw
                WHERE symbol = %s
                ORDER BY announced_at DESC
                LIMIT 3
            """, (SYMBOL,))
            for ct in cur.fetchall():
                snippet = (ct["transcript_text"] or "")[:2500]
                call_texts.append(f"[{ct['quarter_label']} concall]\n{snippet}")
    context_parts.append("CONCALL TRANSCRIPTS (recent 3):\n" + "\n\n---\n\n".join(call_texts))

# Qdrant semantic context
if qdrant_chunks:
    semantic_snippets = []
    for c in qdrant_chunks[:6]:
        pl = c.get("payload", {})
        text = (pl.get("text") or pl.get("tables_markdown") or "")[:800]
        semantic_snippets.append(f"[{pl.get('document_type','')}/{pl.get('section_type','')}]\n{text}")
    context_parts.append("SEMANTIC SEARCH RESULTS (Qdrant):\n" + "\n\n".join(semantic_snippets))

# SHP context
if shp:
    shp_text = "SHAREHOLDING PATTERN:\n" + "\n".join(
        f"  Q{s['quarter']}: Promoter {pct(s['total_promoter_holding_pct'])}, "
        f"Pledge {pct(s['total_pledge_pct'])}, FII {pct(s['fii_holding_pct'])}, "
        f"Public {pct(s['public_holding_pct'])}"
        for s in shp
    )
    context_parts.append(shp_text)

full_context = "\n\n" + ("=" * 60 + "\n").join(context_parts)

prompt = f"""You are a senior equity research analyst. Using the following IKG (Investment Knowledge Graph) data for {COMPANY}, provide a comprehensive analysis.

QUERY: {QUERY}

DATA FROM IKG:
{full_context[:12000]}

Provide:
1. Financial performance summary with specific numbers (revenue, PAT, margins)
2. Key trends and trajectory (improving/deteriorating)
3. Management commentary highlights from concalls
4. Capital structure and shareholding observations
5. Investment thesis (bull case + risks)

Be specific with numbers. Reference specific quarters/periods."""

t_synth = time.time()
resp = httpx.post(
    "https://api.openai.com/v1/chat/completions",
    headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
    json={
        "model": SYNTH_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1500,
    },
    timeout=90,
)

if resp.status_code != 200:
    print("  GPT-4o API error:", resp.status_code, resp.text[:300])
    sys.exit(1)

answer = resp.json()["choices"][0]["message"]["content"]
print("  Synthesis time: %.1fs" % (time.time()-t_synth))
print("  Answer length : %d chars" % len(answer))
print()
print("=" * 72)
print("ANSWER:")
print("=" * 72)
print(answer)
print()

# ── 9. Quality Scorecard ──────────────────────────────────────────────────────
print("=" * 72)
print("QUALITY SCORECARD")
print("=" * 72)
checks = [
    ("Has financial numbers (Cr)",   "Cr" in answer),
    ("Has percentage figures",        "%" in answer),
    ("Has quarter references",        any(q in answer for q in ["Q1", "Q2", "Q3", "Q4", "FY"])),
    ("Has management commentary",     any(w in answer.lower() for w in ["management", "commentary", "guidance", "ceo", "md"])),
    ("Has margins analysis",          any(w in answer.lower() for w in ["margin", "nim", "net interest", "spread"])),
    ("Has credit quality",            any(w in answer.lower() for w in ["npa", "credit", "loan", "advance", "asset quality", "gnpa", "slippage"])),
    ("Has deposit/liability data",    any(w in answer.lower() for w in ["deposit", "liability", "casa", "funding"])),
    ("Has investment thesis",         any(w in answer.lower() for w in ["bull", "risk", "thesis", "recommend", "outlook", "buy", "watch"])),
    ("Has promoter/SHP data",         any(w in answer.lower() for w in ["promoter", "shareholding", "stake", "pledge"])),
    ("Has specific year cited",       any(y in answer for y in ["2024", "2025", "2026", "FY24", "FY25", "FY26"])),
    ("Uses concall content",          any(w in answer.lower() for w in ["concall", "call", "transcript", "analyst", "management said", "conference"])),
]

passed = sum(1 for _, v in checks if v)
for label, ok in checks:
    print("  [%s] %s" % ("✓" if ok else "✗", label))
print()
print("SCORE: %d/%d" % (passed, len(checks)))
if passed >= 9:
    print(">> EXCELLENT — rich multi-source synthesis")
elif passed >= 7:
    print(">> GOOD — solid analysis with some gaps")
elif passed >= 5:
    print(">> FAIR — basic analysis, limited sources")
else:
    print(">> POOR — insufficient data or synthesis")
