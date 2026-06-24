"""Free-proxy rotation control CLI.

Pipeline:
  1. refresh — pull proxy lists from TheSpeedX/PROXY-List into .proxy/proxies_raw.txt
  2. check   — health-probe a sample, writing live ones to .proxy/live.txt
  3. run     — launch the local mubeng rotator over live.txt on PROSPEKT_PROXY_URL

Then set env so the fetchers route through the rotator:
    PROSPEKT_PROXY_ENABLED=1
    PROSPEKT_PROXY_URL=http://127.0.0.1:8089

Usage:
    python scripts/proxy_rotator.py refresh
    python scripts/proxy_rotator.py check --max 400 --timeout 6
    python scripts/proxy_rotator.py run --addr 127.0.0.1:8089 --rotate 5
    python scripts/proxy_rotator.py all          # refresh + check + run
    python scripts/proxy_rotator.py daemon --interval 20   # keep live.txt fresh
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from finagent.tools.web import proxy_pool  # noqa: E402

MUBENG = ROOT / ".proxy" / "bin" / ("mubeng.exe" if sys.platform == "win32" else "mubeng")


def _run_mubeng(addr: str, rotate: int, method: str) -> int:
    live = proxy_pool.write_mubeng_file()
    if not live.exists() or not live.read_text(encoding="utf-8").strip():
        print(f"[run] no live proxies in {live} — run 'check' first.")
        return 2
    if not MUBENG.exists():
        print(f"[run] mubeng binary missing at {MUBENG}")
        return 2
    n = len(proxy_pool.get_live_proxies())
    print(f"[run] starting mubeng on {addr} over {n} live proxies (rotate every {rotate}, {method})")
    print(f"[run] point fetchers at: PROSPEKT_PROXY_ENABLED=1  PROSPEKT_PROXY_URL=http://{addr}")
    cmd = [str(MUBENG), "-a", addr, "-f", str(live), "-r", str(rotate), "-m", method, "--watch"]
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


def _daemon(interval_min: float, max_check: int, concurrency: int, timeout: float) -> int:
    """Keep live.txt fresh: loop refresh + (thread-based) check every N minutes.

    Uses proxy_pool.health_check_sync — NEVER an asyncio mass-checker, which
    storms the Windows Proactor loop and hangs for hours. Ctrl-C exits cleanly
    between cycles (and interrupts the inter-cycle sleep promptly via an Event).
    """
    stop = threading.Event()

    def _on_signal(signum, _frame):  # noqa: ANN001
        print(f"\n[daemon] signal {signum} received — stopping after current cycle.")
        stop.set()

    try:
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
    except (ValueError, OSError):
        # Not on the main thread / unsupported — fall back to KeyboardInterrupt.
        pass

    interval_s = max(1.0, interval_min * 60.0)
    print(f"[daemon] starting — refresh+check every {interval_min:g} min "
          f"(max_check={max_check}, workers={concurrency}, timeout={timeout}s). Ctrl-C to stop.")
    cycle = 0
    try:
        while not stop.is_set():
            cycle += 1
            started = time.perf_counter()
            try:
                n_raw = asyncio.run(proxy_pool.refresh_raw_lists())
                print(f"[daemon] cycle {cycle}: refreshed {n_raw} raw proxies")
            except Exception as exc:  # noqa: BLE001
                print(f"[daemon] cycle {cycle}: refresh failed: {exc!r}")
            try:
                # Thread-based, wall-bounded — never hangs.
                n_live = proxy_pool.health_check_sync(
                    max_check=max_check, workers=concurrency, timeout=timeout)
                print(f"[daemon] cycle {cycle}: {n_live} live -> {proxy_pool.live_file_path()}")
            except Exception as exc:  # noqa: BLE001
                print(f"[daemon] cycle {cycle}: check failed: {exc!r}")
            elapsed = time.perf_counter() - started
            if stop.is_set():
                break
            wait = max(0.0, interval_s - elapsed)
            print(f"[daemon] cycle {cycle} done in {elapsed:.1f}s; sleeping {wait:.0f}s")
            # Event.wait returns True if stop was set during the sleep → exit promptly.
            if stop.wait(wait):
                break
    except KeyboardInterrupt:
        print("\n[daemon] KeyboardInterrupt — stopping.")
    print("[daemon] stopped cleanly.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Free-proxy rotation control")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("refresh", help="download proxy lists")

    pc = sub.add_parser("check", help="health-check a sample -> live.txt")
    pc.add_argument("--max", type=int, default=400)
    pc.add_argument("--concurrency", type=int, default=60)
    pc.add_argument("--timeout", type=float, default=6.0)

    pr = sub.add_parser("run", help="launch mubeng rotator over live.txt")
    pr.add_argument("--addr", default="127.0.0.1:8089")
    pr.add_argument("--rotate", type=int, default=5)
    pr.add_argument("--method", default="random", choices=["random", "sequent"])

    pa = sub.add_parser("all", help="refresh + check + run")
    pa.add_argument("--max", type=int, default=400)
    pa.add_argument("--addr", default="127.0.0.1:8089")
    pa.add_argument("--rotate", type=int, default=5)
    pa.add_argument("--method", default="random", choices=["random", "sequent"])

    pd = sub.add_parser("daemon", help="loop refresh+check every N min to keep live.txt fresh")
    pd.add_argument("--interval", type=float, default=20.0, help="minutes between cycles (default 20)")
    pd.add_argument("--max", type=int, default=400)
    pd.add_argument("--concurrency", type=int, default=60)
    pd.add_argument("--timeout", type=float, default=6.0)

    args = ap.parse_args()

    if args.cmd == "refresh":
        n = asyncio.run(proxy_pool.refresh_raw_lists())
        print(f"[refresh] {n} raw proxies -> {proxy_pool.raw_file_path()}")
        return 0
    if args.cmd == "check":
        # Thread-based, wall-bounded — never hangs (unlike the old asyncio path).
        n = proxy_pool.health_check_sync(
            max_check=args.max, workers=args.concurrency, timeout=args.timeout)
        print(f"[check] {n} live -> {proxy_pool.live_file_path()}")
        return 0
    if args.cmd == "run":
        return _run_mubeng(args.addr, args.rotate, args.method)
    if args.cmd == "all":
        n_raw = asyncio.run(proxy_pool.refresh_raw_lists())
        print(f"[all] refreshed {n_raw} raw proxies")
        n_live = proxy_pool.health_check_sync(max_check=args.max)
        print(f"[all] {n_live} live proxies")
        if n_live == 0:
            print("[all] no live proxies — aborting run.")
            return 2
        return _run_mubeng(args.addr, args.rotate, args.method)
    if args.cmd == "daemon":
        return _daemon(args.interval, args.max, args.concurrency, args.timeout)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
