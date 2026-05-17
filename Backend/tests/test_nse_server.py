"""
Test script for NSE MCP Server tools (NseIndiaApi).
Run: python -m tests.test_nse_server
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_servers.nse_server import (
    nse_get_quote,
    nse_get_trade_info,
    nse_get_historical,
    nse_get_shareholding,
    nse_get_actions,
)


def pp(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def test_quote():
    print("=" * 60)
    print("TEST: nse_get_quote('RELIANCE')")
    print("=" * 60)
    result = nse_get_quote("RELIANCE")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['company_name']} - Rs.{d['last_price']}")
        print(f"       Change: {d['change']} ({d['pct_change']}%)")
        print(f"       52W: Rs.{d['week_low_52']} - Rs.{d['week_high_52']}")
        print(f"       Sector PE: {d['sector_pe']} | Symbol PE: {d['symbol_pe']}")
        print(f"       Industry: {d['industry']}")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_quote_invalid():
    print("=" * 60)
    print("TEST: nse_get_quote('INVALIDXYZ123')")
    print("=" * 60)
    result = nse_get_quote("INVALIDXYZ123")
    if result.get("error"):
        print(f"  [OK] Correctly returned error: {result['message'][:80]}")
    else:
        print("  [FAIL] Should have returned error for invalid symbol")
    print()


def test_trade_info():
    print("=" * 60)
    print("TEST: nse_get_trade_info('TCS')")
    print("=" * 60)
    result = nse_get_trade_info("TCS")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] Market Cap: {d.get('total_market_cap')}")
        print(f"       Delivery %: {d.get('delivery_to_traded_pct')}")
        print(f"       Volatility: {d.get('daily_volatility')} (daily)")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_historical():
    print("=" * 60)
    print("TEST: nse_get_historical('INFY', days=30)")
    print("=" * 60)
    result = nse_get_historical("INFY", days=30)
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['symbol']} - {d['total_records']} records")
        print(f"       Range: {d['date_range']['start']} -> {d['date_range']['end']}")
        if d['records']:
            print(f"       Last: {d['records'][-1]}")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_shareholding():
    print("=" * 60)
    print("TEST: nse_get_shareholding('HDFCBANK')")
    print("=" * 60)
    result = nse_get_shareholding("HDFCBANK")
    if not result.get("error"):
        data = result["data"]
        if isinstance(data, list) and len(data) > 0:
            latest = data[0]
            print(f"  [OK] Latest quarter:")
            print(f"       Promoter: {latest.get('pr_and_prgrp', 'N/A')}%")
            print(f"       Public: {latest.get('public_val', 'N/A')}%")
        else:
            print(f"  [OK] Data returned (format may vary)")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


def test_actions():
    print("=" * 60)
    print("TEST: nse_get_actions()")
    print("=" * 60)
    result = nse_get_actions()
    if not result.get("error"):
        data = result["data"]
        count = len(data) if isinstance(data, list) else "N/A"
        print(f"  [OK] {count} upcoming corporate actions")
    else:
        print(f"  [FAIL] {result['message']}")
    print()


if __name__ == "__main__":
    print("\n>>> ORACLE NSE MCP Server (NseIndiaApi) - Tests\n")

    test_quote()
    test_quote_invalid()
    test_trade_info()
    test_historical()
    test_shareholding()
    test_actions()

    print("[OK] All tests completed!")
