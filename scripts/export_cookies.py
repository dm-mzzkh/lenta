#!/usr/bin/env python
"""Export Lenta cookies from a live Google Chrome via CDP (playwright connect_over_cdp).

Reads even httpOnly cookies (PassportAccessToken, PassportRefreshToken) that are
inaccessible from JS, so DevTools copy-paste won't cut it.

Usage:
    1) Once: open lenta.com in Chrome and log in.
    2) Every time before work:
          uv run python scripts/export_cookies.py --launch --phone 7XXXXXXXXXX --post
               restarts Chrome with a debug port, opens/refreshes lenta.com
               (fresh token), exports cookies to ~/Downloads and logs the service in
          uv run python scripts/export_cookies.py            # export only, no login
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from app.config import settings

# ponytail: only what the service needs; the rest (metrics) stays out.
NEEDED = (
    "App_Cache_MPK",
    "Utk_SessionToken",
    "PassportAccessToken",
    "Utk_DvcGuid",
    "qrator_jsid",
    "PassportRefreshToken",
    "App_Cache_CitySlug",
    "App_Cache_MissionAddressMode",
)


async def export_cookies(port: int) -> dict[str, str]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as e:
            sys.exit(
                f"Could not connect to Chrome on port {port}: {e}\n"
                "Add --launch so the script restarts your browser with a debug port itself."
            )

        contexts = browser.contexts or []
        if not contexts:
            sys.exit("No contexts in Chrome — open a browser window and visit lenta.com")
        ctx = contexts[0]

        # Open lenta.com: the page refreshes the access token and session.
        page = await ctx.new_page()
        await page.goto(settings.lenta_base_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(4)  # Qrator + token refresh need time to complete
        await page.close()

        all_cookies = await ctx.cookies(urls=[settings.lenta_base_url])
        cookie_map = {c["name"]: c["value"] for c in all_cookies}
        picked = {k: cookie_map[k] for k in NEEDED if k in cookie_map}
        missing = [k for k in NEEDED if k not in picked]
        if missing:
            print(f"WARNING: cookies not found in Chrome: {', '.join(missing)}", file=sys.stderr)
        await browser.close()
        return picked


def _chrome_candidates() -> list[str]:
    """Possible browsers: the one actually running first, then by path."""
    home = Path.home()
    cft = sorted(
        home.glob(
            "Library/Caches/ms-playwright/*/chrome-mac*/"
            "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        ),
        reverse=True,
    )
    return [str(p) for p in cft] + [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]


def _pick_browser() -> str:
    import subprocess

    running = subprocess.run(["pgrep", "-fl", "Chrome"], capture_output=True, text=True).stdout
    for cand in _chrome_candidates():
        if Path(cand).exists() and cand in running:
            return cand  # prefer the already running browser (it has the session)
    for cand in _chrome_candidates():
        if Path(cand).exists():
            return cand
    sys.exit(
        "Chrome not found. Install Google Chrome or Chrome for Testing, "
        "visit lenta.com and log in."
    )


def launch_chrome(port: int) -> None:
    """Restarts the user's browser with a remote-debugging port (profile is kept)."""
    import re
    import subprocess
    import time
    import urllib.request

    binary = _pick_browser()
    # An old instance (without a debug port) blocks the restart — kill by binary path.
    subprocess.run(["pkill", "-f", re.escape(binary)], capture_output=True)
    time.sleep(2)
    # stdout/stderr to DEVNULL: otherwise Chrome holds the terminal and the script never exits.
    subprocess.Popen(
        [binary, f"--remote-debugging-port={port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            print(f"Chrome is up with debug port {port} ({binary})")
            return
        except Exception:
            time.sleep(0.5)
    sys.exit("Chrome did not come up with a debug port within 25s")


def save(picked: dict[str, str]) -> Path:
    out = Path.home() / "Downloads" / f"cookies-{date.today().isoformat()}.json"
    out.write_text(json.dumps(picked, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--phone", default="", help="phone number for --post")
    ap.add_argument("--post", action="store_true", help="POST to /api/auth/login right away")
    ap.add_argument(
        "--launch",
        action="store_true",
        help="restart Chrome with a debug port (profile is kept)",
    )
    args = ap.parse_args()

    if args.launch:
        launch_chrome(args.port)

    picked = await export_cookies(args.port)
    if not picked:
        sys.exit("No Lenta cookies found — open lenta.com in this Chrome and log in.")

    path = save(picked)
    print(f"Cookies saved: {path}")

    if args.post:
        if not args.phone:
            sys.exit("--post requires --phone 7XXXXXXXXXX")
        import httpx

        proxy_url = settings.lenta_proxy_url
        try:
            r = httpx.post(
                f"{proxy_url}/api/auth/login",
                json={"phone": args.phone, "cookies": picked},
                timeout=20,
            )
        except httpx.ConnectError:
            sys.exit(
                f"Service unavailable at {proxy_url} — start uvicorn, then retry:\n"
                "  uv run uvicorn app.main:app --reload"
            )
        print(f"POST {proxy_url}/api/auth/login -> {r.status_code}")
        print(r.json())
    else:
        names = ", ".join(picked)
        print(f"Cookies ({len(picked)}): {names}")
        print("Service login:")
        print("  uv run python scripts/export_cookies.py --phone 7XXXXXXXXXX --post")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
