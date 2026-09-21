"""
Standalone entry point for minting one Walmart PerimeterX cookie via
CloakBrowser, run as a SEPARATE OS process from the web server — see
walmart_pricing._warm_http_session_isolated() for why.

A live browser warm on Render's 512MB instance has been confirmed
(2026-09-12) to occasionally get the whole server process OOM-killed by the
host. That's a SIGKILL, not a Python exception — nothing in-process can
catch it, so the entire in-flight request (every concurrent user, not just
the one that triggered the warm) dies with it. Running the mint here
instead means an OOM kill only takes down this one child process; the
parent web server just sees a normal failed-subprocess return, excludes
Walmart from that plan the same way any other pricing failure already does,
and keeps serving everything else.

Usage: python walmart_warm_subprocess.py <output_path>
Writes {"cookies": {...}, "ua": "..."} as JSON to <output_path> on success
— NOT stdout: importing walmart_pricing (and its dependencies) pulls in
plenty of their own unstructured print()s, so stdout can't be trusted to
carry only the JSON. Exits non-zero with an error message on stderr on
failure; <output_path> is left unwritten in that case.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: walmart_warm_subprocess.py <output_path>", file=sys.stderr)
        return 2
    out_path = sys.argv[1]

    import walmart_pricing
    try:
        session = walmart_pricing._warm_http_session()
    except Exception as e:
        print(f"warm failed: {repr(e)[:200]}", file=sys.stderr)
        return 1

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(session, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
