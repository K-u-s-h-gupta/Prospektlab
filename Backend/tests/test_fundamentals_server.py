"""
Test script for Fundamentals MCP Server (yfinance).
Run: python -m tests.test_fundamentals_server
No API key needed!
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_servers.fundamentals_server import (
    profile,
    income_statement,
    balance_sheet,
    cash_flow,
    key_metrics,
)


def pp(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def test_profile():
    print("=" * 60)
    print("TEST: profile('RELIANCE')")
    print("=" * 60)
    result = profile("RELIANCE", exchange="NSE")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['long_name']} ({d['symbol']})")
        print(f"       Sector: {d['sector']} | Industry: {d['industry']}")
        print(f"       Market Cap: {d['market_cap']}")
        print(f"       PE: {d['trailing_pe']} | PB: {d['price_to_book']}")
        print(f"       ROE: {d['return_on_equity']} | D/E: {d['debt_to_equity']}")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_income_statement():
    print("=" * 60)
    print("TEST: income_statement('TCS', annual)")
    print("=" * 60)
    result = income_statement("TCS", exchange="NSE", period="annual")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['symbol']} - {d['total_records']} periods")
        for stmt in d["statements"][:2]:
            rev = stmt.get("Total Revenue", stmt.get("totalRevenue", "N/A"))
            ni = stmt.get("Net Income", stmt.get("netIncome", "N/A"))
            print(f"       {stmt['date']}: Revenue={rev}, Net Income={ni}")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_balance_sheet():
    print("=" * 60)
    print("TEST: balance_sheet('HDFCBANK', annual)")
    print("=" * 60)
    result = balance_sheet("HDFCBANK", exchange="NSE", period="annual")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['symbol']} - {d['total_records']} periods")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_cash_flow():
    print("=" * 60)
    print("TEST: cash_flow('INFY', annual)")
    print("=" * 60)
    result = cash_flow("INFY", exchange="NSE", period="annual")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['symbol']} - {d['total_records']} periods")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_key_metrics():
    print("=" * 60)
    print("TEST: key_metrics('RELIANCE')")
    print("=" * 60)
    result = key_metrics("RELIANCE", exchange="NSE")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['symbol']}")
        print(f"       PE: {d['trailing_pe']} | PB: {d['price_to_book']}")
        print(f"       ROE: {d['roe']} | ROA: {d['roa']}")
        print(f"       D/E: {d['debt_to_equity']} | Current Ratio: {d['current_ratio']}")
        print(f"       Div Yield: {d['dividend_yield']} | Beta: {d['beta']}")
        print(f"       EV/EBITDA: {d['ev_to_ebitda']}")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_profile_us():
    print("=" * 60)
    print("TEST: profile('AAPL', exchange='US')")
    print("=" * 60)
    result = profile("AAPL", exchange="US")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['long_name']} ({d['symbol']})")
        print(f"       Market Cap: ${d['market_cap']}")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


if __name__ == "__main__":
    print("\n>>> ORACLE Fundamentals MCP Server (yfinance) - Tests\n")

    test_profile()
    test_income_statement()
    test_balance_sheet()
    test_cash_flow()
    test_key_metrics()
    test_profile_us()

    print("[OK] All tests completed!")
