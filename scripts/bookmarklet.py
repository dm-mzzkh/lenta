#!/usr/bin/env python3
"""Generates a bookmarklet that uploads lenta.com cookies to the local lenta-proxy.

Open lenta.com in Firefox (incognito works too), log in via the site,
then click the bookmarklet in the bookmarks bar — it sends the cookies
to the running lenta-proxy at 127.0.0.1:8000 itself.
"""
from urllib.parse import quote

PROXY_URL = "http://127.0.0.1:8000/api/auth/login"

js = f"""
(function() {{
  const cookies = document.cookie.split(';').reduce((acc, pair) => {{
    const [k, ...v] = pair.trim().split('=');
    if (k) acc[k] = v.join('=');
    return acc;
  }}, {{}});
  const phone = prompt('phone (7XXXXXXXXXX):', '');
  if (!phone) return alert('phone required');
  fetch({PROXY_URL!r}, {{
    method: 'POST',
    headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{phone, cookies}})
  }})
  .then(r => r.json().then(b => ({{status: r.status, body: b}})))
  .then(({{status, body}}) => alert('lenta-proxy: ' + status + '\\n' + JSON.stringify(body)))
  .catch(e => alert('lenta-proxy: error\\n' + e));
}})();
""".strip()

# Strip newlines and URL-encode for the bookmarklet.
one_line = " ".join(js.split())
bookmarklet = "javascript:" + quote(one_line, safe=":/=?&;{}()*'\"+,!")

print("=== BOOKMARKLET ===")
print()
print(bookmarklet)
print()
print("Usage:")
print("  1. Create a new bookmark in the Firefox bookmarks bar")
print("  2. Paste the string above into the URL field")
print("  3. Open lenta.com (or incognito) and log in there")
print("  4. Click the bookmark — the cookies go to lenta-proxy")
print()
print(f"Proxy URL: {PROXY_URL}")