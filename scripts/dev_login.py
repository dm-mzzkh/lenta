#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import urllib.request

PROXY = "http://127.0.0.1:8000/api/auth/login"

REQUIRED = ("App_Cache_MPK",)
OPTIONAL = (
    "PassportAccessToken",
    "Utk_SessionToken",
    "qrator_jsid",
    "qrator_jsr",
    "App_Cache_CitySlug",
    "App_Cache_MissionAddressMode",
    "PassportRefreshToken",
)


def main() -> int:
    print("=== lenta-proxy dev login ===")
    phone = input("phone (7XXXXXXXXXX): ").strip() or "70000000000"

    cookies: dict[str, str] = {}
    for name in REQUIRED + OPTIONAL:
        val = input(f"{name}: ").strip()
        if val:
            cookies[name] = val

    missing = [n for n in REQUIRED if n not in cookies]
    if missing:
        print(f"REQUIRED: {missing}", file=sys.stderr)
        return 1

    body = json.dumps({"phone": phone, "cookies": cookies}).encode()
    req = urllib.request.Request(
        PROXY,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode()
            print(f"[{resp.status}] {text}")
            if resp.status == 202:
                print("session loaded — data routes are live")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
