"""Debug Tier 2 — see why the stealth browser fallback is failing."""
import asyncio
import sys
import logging
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(name)s %(levelname)s | %(message)s",
)
# Quiet down noisy modules
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)


async def main():
    from finagent.tools.web.exchange_fetcher import _tier2_browser_json, NSE_HOME

    print("=== Direct Tier 2 invocation against NSE marketStatus ===")
    result = await _tier2_browser_json(
        f"{NSE_HOME}/api/marketStatus",
        params={},
        referer=NSE_HOME + "/",
    )
    print(f"Result type: {type(result).__name__}")
    print(f"Result: {str(result)[:400] if result else None!r}")


if __name__ == "__main__":
    asyncio.run(main())
