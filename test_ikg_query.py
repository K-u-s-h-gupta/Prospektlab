"""
IKG Standalone Query Test — runs inside IKG worker container.
Queries Postgres + Qdrant directly, then calls Claude API to generate answer.
"""
import json, os, sys, time, datetime, logging
import httpx

logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)

SYMBOL  = "APOLLOTYRE"
COMPANY = "Apollo Tyres Ltd."
QUERY   = ("Analyse Apollo Tyres financial performance, margins, debt position, "
           "and management commentary on strategy over the last 4 quarters")

QDRANT_URL       = os.environ.get("QDRANT_URL", "http://qdrant:6333")
DB_URL           = os.environ.get("IKG_DATABASE_URL",
                       "postgresql://ikg_user:ikg_password_change_me@postgres:5432/ikg")
OPENAI_KEY       = os.environ.get("OPENAI_API_KEY", "")

print("=" * 72)
print("IKG END-TO-END QUERY TEST")
print("=" * 72)
print("Company :", COMPANY, "(%s)" % SYMBOL)
print("Query   :", QUERY[:80])
print()

# ── helpers ──────────────────────────────────────────────────────────────────
def epoch_ms_to_date(ms):
    try:
        return datetime.datetime.utcfromtimestamp(int(ms) / 1000).strftime("%b %Y")
    except Exception:
        return str(ms)

def cr(val):
    """Convert raw rupees to Crores, formatted."""
    if val is None: return "N/A"
    try: return "%.0f Cr" % (float(val) / 1e7)
    except: return str(val)

def pct(val):
    if val is None: return "N/A"
    try: return "%.1f%%" % float(val)
    except: return str(val)

# ── 1. Entity Resolution ──────────────────────────────────────────────────────
print("── 1. Entity Resolution")
t0 = time.time()
from finagent.ikg.entity_resolver import get_entity_resolver
entity = get_entity_resolver().resolve(SYMBOL)
print("  %-20s %s" % ("Name:",        entity.name))
print("  %-20s %s" % ("CIN:",         entity.cin or "—"))
print("  %-20s %s" % ("BSE Scrip:",   entity.bse_scrip_code))
print("  %-20s %s" % ("ISIN:",        entity.isin))
print("  %-20s %s" % ("Sector:",      entity.sector))
print("  %-20s %.2fs" % ("Resolved in:", time.time() - t0))
print()

# ── 2. Connect Postgres ───────────────────────────────────────────────────────
import psycopg
conn = psycopg.connect(DB_URL)

# ── 3. Financial Data ─────────────────────────────────────────────────────────
print("── 2. Financial Data (Annual Income Statement)")
with conn.cursor() as cur:
    cur.execute("""
        SELECT key, value
        FROM company_financials,
             jsonb_each(income_statement_json)
        WHERE nse_symbol = %s
        ORDER BY key DESC
        LIMIT 6
    """, (SYMBOL,))
    rows = cur.fetchall()

fin_records = []
for epoch_str, data in rows:
    period_label = epoch_ms_to_date(epoch_str)
    revenue   = data.get("Total Revenue") or data.get("Operating Revenue")
    ebitda    = data.get("EBITDA") or data.get("Normalized EBITDA")
    pat       = data.get("Net Income")
    ebit      = data.get("EBIT")
    gross_p   = data.get("Gross Profit")
    int_exp   = data.get("Interest Expense")
    eps       = data.get("Diluted EPS")
    # margin calc
    ebitda_margin = None
    if ebitda and revenue and float(revenue or 0) > 0:
        ebitda_margin = 100.0 * float(ebitda) / float(revenue)
    gross_margin = None
    if gross_p and revenue and float(revenue or 0) > 0:
        gross_margin = 100.0 * float(gross_p) / float(revenue)
    fin_records.append({
        "period": period_label, "epoch": epoch_str,
        "revenue": revenue, "ebitda": ebitda, "pat": pat, "ebit": ebit,
        "gross_profit": gross_p, "int_expense": int_exp, "eps": eps,
        "ebitda_margin": ebitda_margin, "gross_margin": gross_margin,
    })

if fin_records:
    print("  %-12s %14s %12s %10s %10s %10s" % (
        "Period", "Revenue", "EBITDA", "EBITDA%", "PAT", "EPS"))
    print("  " + "-"*70)
    for f in fin_records:
        print("  %-12s %14s %12s %9s %10s %10s" % (
            f["period"], cr(f["revenue"]), cr(f["ebitda"]),
            pct(f["ebitda_margin"]), cr(f["pat"]),
            ("%.2f" % f["eps"]) if f["eps"] else "N/A"))
else:
    print("  No annual financial data")
print()

# Balance sheet
print("── 3. Balance Sheet (Debt / Leverage)")
with conn.cursor() as cur:
    cur.execute("""
        SELECT key, value
        FROM company_financials,
             jsonb_each(balance_sheet_json)
        WHERE nse_symbol = %s
        ORDER BY key DESC
        LIMIT 4
    """, (SYMBOL,))
    bs_rows = cur.fetchall()

bs_records = []
for epoch_str, data in bs_rows:
    total_debt    = data.get("Total Debt") or data.get("Long Term Debt")
    cash          = data.get("Cash And Cash Equivalents") or data.get("Cash")
    total_assets  = data.get("Total Assets")
    equity        = data.get("Stockholders Equity") or data.get("Common Stock Equity")
    net_debt = None
    if total_debt is not None and cash is not None:
        try: net_debt = float(total_debt) - float(cash)
        except: pass
    bs_records.append({
        "period": epoch_ms_to_date(epoch_str),
        "total_debt": total_debt, "cash": cash,
        "net_debt": net_debt, "total_assets": total_assets, "equity": equity,
    })

if bs_records:
    print("  %-12s %14s %10s %14s %12s" % (
        "Period", "Total Debt", "Cash", "Net Debt", "Equity"))
    print("  " + "-"*65)
    for b in bs_records:
        print("  %-12s %14s %10s %14s %12s" % (
            b["period"], cr(b["total_debt"]), cr(b["cash"]),
            cr(b["net_debt"]), cr(b["equity"])))
else:
    print("  No balance sheet data")
print()

# ── 4. Validated Metrics ──────────────────────────────────────────────────────
print("── 4. Validated Key Metrics")
with conn.cursor() as cur:
    cur.execute("SELECT validated_metrics_json FROM company_financials WHERE nse_symbol=%s", (SYMBOL,))
    row = cur.fetchone()
vm = row[0] if row else {}
if vm:
    for key, val in vm.items():
        if isinstance(val, dict):
            v = val.get("value")
            src = val.get("source","")
            verified = val.get("verified", False)
            flag = "✓" if verified else "~"
            if v is not None:
                print("  [%s] %-38s %s  (src: %s)" % (flag, key, v, src))
        elif val is not None:
            print("  %-40s %s" % (key, val))
else:
    print("  No validated metrics")
print()

# ── 5. Shareholding Pattern ───────────────────────────────────────────────────
print("── 5. Shareholding Pattern")
with conn.cursor() as cur:
    cur.execute("""
        SELECT quarter, total_promoter_holding_pct, fii_holding_pct,
               dii_holding_pct, public_holding_pct, total_pledge_pct
        FROM shp_raw
        WHERE scrip_code = %s
        ORDER BY quarter DESC LIMIT 6
    """, (entity.bse_scrip_code,))
    shp_rows = cur.fetchall()

if shp_rows:
    print("  %-10s %10s %8s %8s %10s %8s" % (
        "Quarter", "Promoter", "FII", "DII", "Public", "Pledge"))
    print("  " + "-"*58)
    for r in shp_rows:
        print("  %-10s %9s%% %7s%% %7s%% %9s%% %7s%%" % (
            r[0], r[1] or "?", r[2] or "?", r[3] or "?", r[4] or "?", r[5] or "?"))
else:
    print("  No SHP data found (scrip: %s)" % entity.bse_scrip_code)
print()

# ── 6. Concall Transcripts ────────────────────────────────────────────────────
print("── 6. Concall Transcripts (most recent 5)")
with conn.cursor() as cur:
    cur.execute("""
        SELECT quarter_label, announced_at::date, sentiment_label,
               sentiment_score, text_length, intent_tags_json,
               LEFT(transcript_text, 2000) AS excerpt
        FROM concall_transcripts_raw
        WHERE symbol = %s AND extraction_status = 'ok' AND text_length > 500
        ORDER BY announced_at DESC LIMIT 5
    """, (SYMBOL,))
    concalls = cur.fetchall()

print("  Found: %d concall transcripts" % len(concalls))
for r in concalls:
    tags = r[5] or []
    print("  %s  [%s]  %s (%.2f)  %d chars  tags=%s" % (
        r[0], r[1], r[2], float(r[3] or 0), r[4] or 0, tags))
print()

# ── 7. Qdrant: indexed chunks for this company ───────────────────────────────
print("── 7. Qdrant Vector Store")
scroll = httpx.post(
    QDRANT_URL + "/collections/ikg_document_sections/points/scroll",
    json={
        "filter": {"must": [{"key": "nse_symbol", "match": {"value": SYMBOL}}]},
        "limit": 50, "with_payload": True, "with_vector": False,
    },
    timeout=20,
)
qdrant_pts = []
if scroll.status_code == 200:
    qdrant_pts = scroll.json().get("result", {}).get("points", [])
    by_type = {}
    for pt in qdrant_pts:
        dt = pt.get("payload", {}).get("document_type", "unknown")
        by_type[dt] = by_type.get(dt, 0) + 1
    print("  Total indexed chunks for %s: %d" % (SYMBOL, len(qdrant_pts)))
    for dt, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        print("    %-35s %d chunks" % (dt, cnt))
else:
    print("  Qdrant error: HTTP %d" % scroll.status_code)
print()

# ── 8. Recent Pipeline Run Status ────────────────────────────────────────────
print("── 8. Pipeline Run Health (last 48h)")
with conn.cursor() as cur:
    cur.execute("""
        SELECT source_name, COUNT(*) runs,
               SUM(records_stored) stored,
               COUNT(*) FILTER (WHERE success) ok,
               MAX(completed_at)::date last_run
        FROM ikg_pipeline_runs
        WHERE completed_at > NOW() - INTERVAL '48 hours'
        GROUP BY source_name
        ORDER BY last_run DESC, stored DESC
    """)
    runs = cur.fetchall()

for r in runs:
    status = "OK" if r[3] == r[1] else ("PARTIAL(%d/%d)" % (r[3], r[1]))
    print("  [%-8s] %-46s %6d stored  last: %s" % (
        status, r[0][:46], r[2] or 0, r[4]))
print()

conn.close()

# ── 9. Build LLM context ──────────────────────────────────────────────────────
print("── 9. Building LLM Context")
sections = []

# Financials table
if fin_records:
    t = "### Annual Financial Results (INR Crores)\n"
    t += "| Period | Revenue | EBITDA | EBITDA Margin | PAT | EPS |\n"
    t += "|--------|---------|--------|--------------|-----|-----|\n"
    for f in fin_records[:4]:
        t += "| %s | %s | %s | %s | %s | %s |\n" % (
            f["period"], cr(f["revenue"]), cr(f["ebitda"]),
            pct(f["ebitda_margin"]), cr(f["pat"]),
            ("%.2f" % f["eps"]) if f["eps"] else "N/A")
    sections.append(t)

if bs_records:
    t = "### Balance Sheet / Debt Position\n"
    t += "| Period | Total Debt | Cash | Net Debt | Equity |\n"
    t += "|--------|-----------|------|---------|--------|\n"
    for b in bs_records[:3]:
        t += "| %s | %s | %s | %s | %s |\n" % (
            b["period"], cr(b["total_debt"]), cr(b["cash"]),
            cr(b["net_debt"]), cr(b["equity"]))
    sections.append(t)

if shp_rows:
    t = "### Shareholding Pattern\n"
    t += "| Quarter | Promoter | FII | DII | Public | Pledge |\n"
    t += "|---------|----------|-----|-----|--------|--------|\n"
    for r in shp_rows[:4]:
        t += "| %s | %s%% | %s%% | %s%% | %s%% | %s%% |\n" % (
            r[0], r[1] or "?", r[2] or "?", r[3] or "?", r[4] or "?", r[5] or "?")
    sections.append(t)

if concalls:
    t = "### Management Commentary from Concall Transcripts\n\n"
    for c in concalls[:4]:
        q, dt, sentiment, score, tlen, tags, excerpt = c
        t += "#### %s  (sentiment: %s, score: %.2f)\n" % (q, sentiment, float(score or 0))
        t += (excerpt or "")[:1600] + "\n\n"
    sections.append(t)

full_ctx = "\n\n".join(sections)
print("  Context: %d chars, %d sections" % (len(full_ctx), len(sections)))

if len(full_ctx) < 300:
    print("\n  WARNING: Very little context — IKG may not have enough data yet")
    print("  fin=%d  bs=%d  shp=%d  concalls=%d" % (
        len(fin_records), len(bs_records), len(shp_rows), len(concalls)))
    sys.exit(0)

print()

# ── 10. Generate Answer ───────────────────────────────────────────────────────
print("── 10. Generating Answer (Claude Haiku)")
LLM_MODEL = os.environ.get("FINAGENT_SYNTH_MODEL", "gpt-4o")
print("  Calling OpenAI API (%s)..." % LLM_MODEL)

t0 = time.time()
resp = httpx.post(
    "https://api.openai.com/v1/chat/completions",
    headers={
        "Authorization": "Bearer " + OPENAI_KEY,
        "Content-Type": "application/json",
    },
    json={
        "model": LLM_MODEL,
        "max_tokens": 2200,
        "messages": [
            {
                "role": "system",
                "content": "You are a senior Indian equity research analyst. Be precise, data-driven, and cite specific numbers."
            },
            {
                "role": "user",
                "content": (
                    "RESEARCH QUERY: " + QUERY + "\n\n"
                    "DATA FROM INVESTMENT KNOWLEDGE GRAPH (IKG):\n\n"
                    + full_ctx[:7500] +
                    "\n\nInstructions:\n"
                    "- Lead with the most recent quarterly/annual financials with specific numbers\n"
                    "- Analyse revenue growth trajectory, EBITDA margin trend, and debt reduction/expansion\n"
                    "- Quote specific management commentary from concall transcripts (cite quarter)\n"
                    "- Discuss shareholding changes — promoter confidence, institutional interest\n"
                    "- End with a concise investment thesis (3-4 bullets: positives, risks, outlook)\n"
                    "- Use precise INR figures — Cr, %, bps. Avoid vague generalities."
                )
            }
        ],
    },
    timeout=90,
)
t1 = time.time()

if resp.status_code != 200:
    print("  API Error %d: %s" % (resp.status_code, resp.text[:200]))
    sys.exit(1)

data   = resp.json()
answer = data["choices"][0]["message"]["content"]
usage  = data.get("usage", {})

print("  Generated in %.1fs | %d chars | in=%d out=%d tokens" % (
    t1 - t0, len(answer),
    usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)))
print()
print("=" * 72)
print("GENERATED ANSWER")
print("=" * 72)
print(answer)
print()

# ── 11. Quality Scorecard ─────────────────────────────────────────────────────
print("=" * 72)
print("QUALITY SCORECARD")
print("=" * 72)
a_low = answer.lower()
checks = [
    ("Revenue / sales figures cited",         any(w in a_low for w in ["revenue","turnover","sales cr"])),
    ("EBITDA / margin analysis",              any(w in a_low for w in ["ebitda","margin","operating profit"])),
    ("Debt / leverage numbers",               any(w in a_low for w in ["debt","borrowing","leverage","net debt"])),
    ("Quarter-specific references (Q1-Q4/FY)",any(w in a_low for w in ["q1","q2","q3","q4","fy2","fy25","fy26"])),
    ("Management commentary cited",           any(w in a_low for w in ["management","guided","commentary","transcript","concall","call"])),
    ("Shareholding / promoter discussed",     any(w in a_low for w in ["promoter","shareholding","fii","dii","institutional"])),
    ("Specific numbers (digits present)",     any(c.isdigit() for c in answer)),
    ("Growth / trend analysis",               any(w in a_low for w in ["growth","increas","decreas","improved","declined","trend"])),
    ("Investment thesis / outlook",           any(w in a_low for w in ["outlook","thesis","catalyst","watch","positive","risk","concern"])),
    ("Substantial answer (>900 chars)",       len(answer) > 900),
    ("Very detailed answer (>1500 chars)",    len(answer) > 1500),
]
passed = sum(v for _, v in checks)
total  = len(checks)
print()
for label, result in checks:
    print("  [%s] %s" % ("PASS" if result else "FAIL", label))

print()
verdict = (
    "EXCELLENT — rich multi-source data, detailed analysis"  if passed >= 9 else
    "GOOD — solid depth, uses IKG data effectively"          if passed >= 7 else
    "PARTIAL — some IKG data used, but analysis is shallow"  if passed >= 5 else
    "WEAK — mostly generic, limited IKG data in answer"      if passed >= 3 else
    "POOR — IKG data not reaching the answer layer"
)
print("  Score:   %d / %d" % (passed, total))
print("  Verdict: %s" % verdict)
print()
print("DATA AVAILABILITY SUMMARY")
print("  Annual fin records : %d  (epochs: %s)" % (
    len(fin_records), ", ".join(f["period"] for f in fin_records[:4])))
print("  Balance sheet recs : %d" % len(bs_records))
print("  SHP quarters       : %d" % len(shp_rows))
print("  Concall transcripts: %d  (latest: %s)" % (
    len(concalls), concalls[0][0] if concalls else "none"))
print("  Qdrant chunks      : %d" % len(qdrant_pts))
