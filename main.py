import os
import sys

# Fix Windows UTF-8 before any imports (crawl4ai's Rich logger crashes on cp1252)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def main():
    print("Hello from prospektlab!")


if __name__ == "__main__":
    main()
