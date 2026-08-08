"""
Local equivalent of the .github/workflows/test-walmart-cookie-replay.yml
workflow_dispatch: runs test_walmart_cookie_replay.py's logic from YOUR
machine's IP (so the request isn't origin-pinned to GitHub Actions' flagged
runner IPs, where Walmart's PerimeterX returns px-captcha on every request
regardless of cookie validity).

Same env vars as the workflow, with these conveniences for local use:
  - If COOKIE_JSON is unset, auto-reads the LATEST entry of
    backend/.minted_walmart_cookies.json (your local cookie pool), so you
    can just run:  python run_walmart_replay_local.py
    with no arguments. Set MINT_INDEX to pick a different pool entry
    (default = last/newest entry).
  - UA auto-reads from the same pool entry if not set explicitly.
  - Same inputs as the workflow: COOKIE_JSON, UA, TERM, ITEM_COUNT,
    CONCURRENCY — so anything that worked in CI works identically here.

Usage (from repo root, venv active):
    python backend/run_walmart_replay_local.py                   # 1 request, "milk", newest pool cookie + its UA
    python backend/run_walmart_replay_local.py --term eggs       # 1 request, term=eggs
    python backend/run_walmart_replay_local.py --item-count 5    # 5 requests, concurrency=min(5,20)=5
    python backend/run_walmart_replay_local.py --item-count 25   # 25 requests, concurrency=20 (safe wall)
    python backend/run_walmart_replay_local.py --item-count 21 --concurrency 21   # cross the 20-wall (RISKY — see review doc)

    # Pick a specific pool cookie (0-indexed; default = last/newest):
    python backend/run_walmart_replay_local.py --mint-index 0

    # Override the cookie entirely (same as the workflow's cookie_json input):
    $env:COOKIE_JSON = '{"_px3":"...","_px2":"...",...}'
    python backend/run_walmart_replay_local.py

The actual replay work is delegated to test_walmart_cookie_replay.py — this
script just handles the local conveniences (pool auto-read, CLI args) and
then re-exports its env vars so it picks them up exactly as the GH job does.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).parent
_POOL_FILE = _BACKEND / ".minted_walmart_cookies.json"
_REPLAY_SCRIPT = _BACKEND / "test_walmart_cookie_replay.py"
_RESULTS_DIR = _BACKEND / "replay_results"
# Match the RESULT: lines emitted by test_walmart_cookie_replay.py.
# Single:    "RESULT: SUCCESS -- N products (X.XXs)"
# Single:    "RESULT: BLOCKED (px-captcha) status=200 (0.53s)"
# Batch:     "RESULT: 24/25 succeeded in 5.1s (first half completed: 12/12, second half: 12/13)"
_RESULT_RE = re.compile(r"^RESULT:\s*(.+)$", re.MULTILINE)


def _load_pool_entry(index: int | None) -> tuple[dict, str]:
    """Read .minted_walmart_cookies.json and return (cookies_dict, ua) for the
    entry at `index` (or the last/newest entry if index is None)."""
    if not _POOL_FILE.exists():
        sys.exit(f"No pool file at {_POOL_FILE}. Run mint_walmart_cookies.py first.")
    try:
        pool = json.loads(_POOL_FILE.read_text())
    except Exception as e:
        sys.exit(f"Pool file unreadable ({repr(e)[:120]}).")
    if not isinstance(pool, list) or not pool:
        sys.exit("Pool file is empty or not a JSON array.")
    if index is None:
        index = len(pool) - 1
    if not (0 <= index < len(pool)):
        sys.exit(f"MINT_INDEX {index} out of range (pool has {len(pool)} entries, 0..{len(pool)-1}).")
    entry = pool[index]
    cookies = entry.get("cookies")
    ua = entry.get("ua", "")
    if not isinstance(cookies, dict) or not cookies:
        sys.exit(f"Pool entry #{index} has no 'cookies' dict — malformed.")
    if "_px3" not in cookies:
        print(f"Warning: pool entry #{index} has no '_px3' cookie — likely not a valid PerimeterX session.", flush=True)
    saved_iso = entry.get("saved_at_iso", "?")
    print(f"Using pool entry #{index}/{len(pool)} (saved {saved_iso}).", flush=True)
    return cookies, ua


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Walmart cookie replay from YOUR IP (local equivalent of the GH workflow).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--term", default=os.environ.get("TERM", "milk"),
                        help="Search term (default 'milk'). Ignored if --item-count > 1.")
    parser.add_argument("--item-count", type=int, default=int(os.environ.get("ITEM_COUNT", "1")),
                        help="Number of requests (default 1). If >1, cycles built-in grocery terms.")
    parser.add_argument("--concurrency", type=int, default=None,
                        help="How many of --item-count fire at once. Default: min(item_count, 20) — the confirmed-safe Walmart wall.")
    parser.add_argument("--mint-index", type=int, default=None,
                        help="Index into .minted_walmart_cookies.json (default: last/newest entry). Ignored if COOKIE_JSON is set.")
    parser.add_argument("--python", default=sys.executable,
                        help="Python interpreter to use for the replay script (default: current).")
    args = parser.parse_args()

    env = os.environ.copy()

    if not env.get("COOKIE_JSON"):
        cookies, file_ua = _load_pool_entry(args.mint_index)
        env["COOKIE_JSON"] = json.dumps(cookies)
        if not env.get("UA") and file_ua:
            env["UA"] = file_ua

    if args.term and not env.get("TERM"):
        env["TERM"] = args.term
    env["ITEM_COUNT"] = str(args.item_count)
    if args.concurrency is not None:
        env["CONCURRENCY"] = str(args.concurrency)
    elif not env.get("CONCURRENCY"):
        env["CONCURRENCY"] = str(min(args.item_count, 20))

    run_config = {
        "term": env.get("TERM", "milk"),
        "item_count": env["ITEM_COUNT"],
        "concurrency": env["CONCURRENCY"],
        "mint_index": args.mint_index,
    }
    print(f"Replaying from local IP with: term={run_config['term']!r} "
          f"item_count={run_config['item_count']} concurrency={run_config['concurrency']}", flush=True)
    print("-" * 60, flush=True)

    cmd = [args.python, str(_REPLAY_SCRIPT)]
    proc = subprocess.run(cmd, env=env, cwd=str(_BACKEND),
                          capture_output=True, text=True)

    # Echo the replay's own output to the terminal so the original RESULT:
    # lines (and any warnings) are still visible exactly as in CI.
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    print("-" * 60, flush=True)

    # Extract the RESULT: line(s) for a clean inline summary.
    result_lines = _RESULT_RE.findall(proc.stdout)
    summary = result_lines[-1].strip() if result_lines else "<no RESULT: line found>"

    # Determine a one-word verdict for quick scanning.
    if "succeeded" in summary and "/" in summary:
        ok, total = summary.split(" succeeded", 1)[0].split("/", 1)
        verdict = "SUCCESS" if ok == total else "PARTIAL"
    elif summary.startswith("SUCCESS"):
        verdict = "SUCCESS"
    else:
        verdict = "FAIL"

    print(f"VERDICT: {verdict}", flush=True)
    print(f"SUMMARY: {summary}", flush=True)
    print(f"EXIT:    {proc.returncode}", flush=True)

    # Persist full output to a timestamped file under backend/replay_results/
    # so you have a durable record. One file per run, never overwritten.
    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    result_file = _RESULTS_DIR / f"replay_{stamp}_{verdict.lower()}.txt"
    record = {
        "verdict": verdict,
        "exit_code": proc.returncode,
        "summary": summary,
        "config": run_config,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    result_file.write_text(json.dumps(record, indent=2))
    print(f"Saved full results to: {result_file}", flush=True)

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
