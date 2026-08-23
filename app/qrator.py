from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from app.config import settings

log = logging.getLogger("lenta.qrator")

# ponytail: minimal stealth to bypass Qrator's headless detection.
# If Lenta tightens checks — switch to playwright-stealth or headed mode.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU','ru','en']});
window.chrome = { runtime: {} };
const originalQuery = window.navigator.permissions ? window.navigator.permissions.query : null;
if (originalQuery) {
  window.navigator.permissions.query = (p) => p.name === 'notifications'
    ? Promise.resolve({state: Notification.permission})
    : originalQuery(p);
}
"""

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class QratorSolver:
    """Solves the Qrator JS challenge via headless Chromium (stealth), returns cookies.

    Strategy: opens lenta.com, waits for the Qrator JS to run, then makes a
    browser-side fetch to the public /api/v1/cities — if it succeeds (200 OK),
    the challenge is solved; grab all context cookies.

    ponytail: one Chromium per process, no pool; enough for MVP,
    per-request isolation — add a pool if throughput matters.
    """

    def __init__(self, base_url: str = settings.lenta_base_url) -> None:
        self.base_url = base_url
        self._lock = asyncio.Lock()

    async def solve(self) -> dict[str, str]:
        async with self._lock:
            return await self._solve_locked()

    async def _solve_locked(self) -> dict[str, str]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "playwright is required for Qrator bypass; "
                "run `uv sync` and `uv run playwright install chromium`"
            ) from e

        cookies: dict[str, str] = {}
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.lenta_headless, args=_LAUNCH_ARGS
            )
            context = await browser.new_context(
                user_agent=settings.lenta_user_agent,
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )
            await context.add_init_script(_STEALTH_JS)
            page = await context.new_page()
            try:
                log.info("qrator: navigating to %s", self.base_url)
                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=45000)
                # Step 1: wait for the page to fully render (Qrator JS runs
                # in the background, document.cookie updates with a delay).
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=45000)
                # Step 2: fetch the public API from the browser context —
                # if Qrator let us through, we get JSON; otherwise an HTML challenge.
                log.info("qrator: probing /api/v1/cities via browser fetch")
                probe = await page.evaluate(
                    """
                    async () => {
                      try {
                        const r = await fetch('/api/v1/cities', {
                          headers: {'accept': 'application/json'},
                          credentials: 'same-origin',
                        });
                        const ct = r.headers.get('content-type') || '';
                        return {status: r.status, ct: ct, ok: r.ok};
                      } catch (e) {
                        return {status: 0, ct: '', ok: false, err: String(e)};
                      }
                    }
                    """
                )
                log.info("qrator: probe result=%s", probe)

                # If the probe is not OK — wait and retry the fetch
                # after 5s (sometimes Qrator takes more than one attempt).
                if not probe.get("ok"):
                    log.info("qrator: probe failed, retrying in 5s")
                    await asyncio.sleep(5)
                    probe = await page.evaluate(
                        """
                        async () => {
                          try {
                            const r = await fetch('/api/v1/cities', {
                              headers: {'accept': 'application/json'},
                              credentials: 'same-origin',
                            });
                            const ct = r.headers.get('content-type') || '';
                            return {status: r.status, ct: ct, ok: r.ok};
                          } catch (e) {
                            return {status: 0, ct: '', ok: false, err: String(e)};
                          }
                        }
                        """
                    )
                    log.info("qrator: probe retry result=%s", probe)

                for c in await context.cookies():
                    cookies[c["name"]] = c["value"]

                if not probe.get("ok"):
                    log.warning(
                        "qrator: API probe still failing (status=%s); "
                        "auth requests will likely 403/401",
                        probe.get("status"),
                    )
            finally:
                await context.close()
                await browser.close()

        log.info(
            "qrator solved: %d cookies (qrator_jsid=%s)",
            len(cookies),
            "qrator_jsid" in cookies,
        )
        return cookies


_solver: QratorSolver | None = None


def get_solver() -> QratorSolver:
    global _solver
    if _solver is None:
        _solver = QratorSolver()
    return _solver


def set_solver_for_tests(solver: Any) -> None:
    global _solver
    _solver = solver