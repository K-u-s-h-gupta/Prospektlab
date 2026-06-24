import sys
sys.path.insert(0, r"D:\PROSPEKTLAB\backend")
import time
from finagent.earnings import service

symbol = "VIKASLIFE"
date = "2026-06-24"
selected = service.parse_date(date)
for label, fn in [
    ("detail", lambda: service._query_detail_row(symbol, selected)),
    ("announcement", lambda: service._query_announcement_detail_row(symbol, selected)),
    ("history", lambda: service.get_earnings_history(symbol, limit=8, fallback_demo=False)),
    ("result", lambda: service.get_earnings_result(symbol, date)),
]:
    t0 = time.perf_counter()
    out = fn()
    elapsed = time.perf_counter() - t0
    print(label, round(elapsed, 3), type(out).__name__, bool(out))