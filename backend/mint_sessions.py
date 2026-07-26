"""
GitHub-Actions entrypoint: mint each browser chain's WAF cookie on a beefy
runner (7GB RAM, where a real browser fits comfortably) and publish it to
Supabase via session_store, so the 512MB web server can replay via curl_cffi
without ever launching a browser.

Runs on a cron (see .github/workflows/mint-sessions.yml). Each chain is minted
independently — one failing (e.g. WAF block) doesn't stop the others.

Env expected (set as GitHub Actions secrets):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (to write chain_sessions)
    CLOAK_PROXY                                (optional: route mint via proxy)
    MINT_CHAINS                                (optional: comma list; default all)

Local test:  python mint_sessions.py
"""
from __future__ import annotations

import os
import sys
import time

# config.py hard-exits if ORS_API_KEY is unset, but this job doesn't need it —
# provide a harmless placeholder so importing the chain modules doesn't abort.
os.environ.setdefault("ORS_API_KEY", "not-needed-for-minting")
# Plenty of RAM on the runner: no need to serialize/limit browsers.
os.environ.setdefault("LOW_MEMORY_MODE", "0")

import session_store  # noqa: E402


def _mint_via_warm(module_name: str, warm_attr: str = "_warm_http_session") -> dict:
    module = __import__(module_name)
    warm = getattr(module, warm_attr)
    return warm()  # returns {"cookies": {...}, "ua": str}; may raise on block


# chain_key -> (module, how to mint). All four use _warm_http_session().
_CHAINS = {
    "walmart":    ("walmart_pricing", "_warm_http_session"),
    "target":     ("target_pricing", "_warm_http_session"),
    "coles":      ("coles_pricing", "_warm_http_session"),
    "woolworths": ("woolworths_pricing", "_warm_http_session"),
}


def main() -> int:
    wanted = os.environ.get("MINT_CHAINS")
    chains = ([c.strip() for c in wanted.split(",") if c.strip()]
              if wanted else list(_CHAINS))

    ok, failed = [], []
    for chain in chains:
        spec = _CHAINS.get(chain)
        if not spec:
            print(f"[mint] unknown chain '{chain}', skipping", flush=True)
            continue
        module_name, warm_attr = spec
        t0 = time.time()
        try:
            session = _mint_via_warm(module_name, warm_attr)
            if not session or not session.get("cookies"):
                raise RuntimeError("warm returned no cookies")
            if session_store.save(chain, session):
                ok.append(chain)
                print(f"[mint] {chain}: minted + published ({time.time()-t0:.0f}s, "
                      f"{len(session['cookies'])} cookies)", flush=True)
            else:
                failed.append(chain)
                print(f"[mint] {chain}: minted but Supabase save failed", flush=True)
        except Exception as e:
            failed.append(chain)
            print(f"[mint] {chain}: FAILED ({repr(e)[:120]})", flush=True)

    print(f"\n[mint] done — ok={ok} failed={failed}", flush=True)
    # Exit 0 even on partial failure: one blocked chain shouldn't fail the whole
    # workflow run (the next cron tick retries). Exit non-zero only if ALL failed.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
