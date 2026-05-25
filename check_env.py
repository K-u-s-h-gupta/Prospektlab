"""Verify the server environment and print critical info.
Run this before starting the server to confirm everything is ready.
"""
from __future__ import annotations

import sys


def check():
    print("=" * 60)
    print("PROSPEKTLAB SERVER ENVIRONMENT CHECK")
    print("=" * 60)
    print(f"Python executable: {sys.executable}")
    print(f"Python version:  {sys.version}")
    print()

    critical = [
        "fastapi",
        "uvicorn",
        "fastmcp",
        "docling",
        "pypdf",
        "msoffcrypto",
        "pandas",
        "openpyxl",
        "yfinance",
        "numpy",
        "openai",
        "httpx",
        "jwt",
    ]

    optional = [
        "matplotlib",
        "feedparser",
        # tavily removed (replaced by self-hosted SearXNG)
    ]

    print("CRITICAL modules:")
    all_ok = True
    for mod in critical:
        try:
            __import__(mod)
            print(f"  [OK]  {mod}")
        except ImportError:
            print(f"  [MISSING] {mod}")
            all_ok = False

    print()
    print("Optional modules:")
    for mod in optional:
        try:
            __import__(mod)
            print(f"  [OK]  {mod}")
        except ImportError:
            print(f"  [MISSING] {mod}")

    print()
    if all_ok:
        print("RESULT: All critical modules found. Server should start correctly.")
    else:
        print("RESULT: Some critical modules are missing! Install them with:")
        print(f'  {sys.executable} -m pip install fastapi uvicorn docling pypdf msoffcrypto-tool pandas openpyxl yfinance numpy openai httpx PyJWT')

    print()
    print("=" * 60)
    print("IMPORTANT: Always start the server using the venv Python:")
    print(r'  D:\PROSPEKTLAB\.venv-prospektlab311b\Scripts\python.exe -m uvicorn finagent.gateway.run:app --reload')
    print("=" * 60)


if __name__ == "__main__":
    check()
