#!/usr/bin/env python3
"""
keep_alive.py — ping the Hugging Face Space so it never goes to sleep.

Free HF Spaces pause after a stretch of inactivity; a periodic request keeps the
container warm. This uses only the Python standard library (no pip installs).

Usage:
    python keep_alive.py                                   # uses the default URL below
    python keep_alive.py https://<user>-<space>.hf.space   # custom Space URL
    python keep_alive.py --interval 900                    # ping every 15 min
    python keep_alive.py --once                            # single ping (for cron/CI)

IMPORTANT — it must run on something that's always on:
  • a machine/server that stays powered, OR
  • a scheduler that runs it on a timer (cron, Windows Task Scheduler), OR
  • best "never sleeps" with nothing of your own always-on: a GitHub Actions
    cron workflow calling this with --once (see the snippet at the bottom).
"""
import argparse
import datetime
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://kuldeepmishra3-legal-rag.hf.space"


def ping(target, timeout=30):
    req = urllib.request.Request(target, headers={"User-Agent": "space-keep-alive/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def once(target):
    try:
        code = ping(target)
        print(f"[{stamp()}] {code} OK  {target}", flush=True)
        return 200 <= code < 400
    except urllib.error.HTTPError as e:
        print(f"[{stamp()}] HTTP {e.code}  {target}", flush=True)
        return False
    except Exception as e:
        print(f"[{stamp()}] error: {e}", flush=True)
        return False


def main():
    ap = argparse.ArgumentParser(description="Keep a Hugging Face Space awake.")
    ap.add_argument("url", nargs="?", default=DEFAULT_URL, help="Space base URL")
    ap.add_argument("--path", default="/health", help="endpoint to hit (default /health)")
    ap.add_argument("--interval", type=int, default=600, help="seconds between pings (default 600 = 10 min)")
    ap.add_argument("--once", action="store_true", help="ping a single time and exit (for cron/CI)")
    a = ap.parse_args()

    target = a.url.rstrip("/") + a.path
    if a.once:
        return 0 if once(target) else 1

    print(f"keep-alive → {target} every {a.interval}s (Ctrl+C to stop)", flush=True)
    while True:
        once(target)
        try:
            time.sleep(a.interval)
        except KeyboardInterrupt:
            print("\nstopped.", flush=True)
            return 0


if __name__ == "__main__":
    sys.exit(main())

# ----------------------------------------------------------------------------
# Truly "never sleeps" without keeping your own machine on — a GitHub Actions
# cron. Add this as .github/workflows/keep-alive.yml in any repo:
#
#   name: keep-space-alive
#   on:
#     schedule:
#       - cron: "*/15 * * * *"   # every 15 minutes
#     workflow_dispatch:
#   jobs:
#     ping:
#       runs-on: ubuntu-latest
#       steps:
#         - run: curl -fsS https://kuldeepmishra3-legal-rag.hf.space/health && echo OK
# ----------------------------------------------------------------------------
