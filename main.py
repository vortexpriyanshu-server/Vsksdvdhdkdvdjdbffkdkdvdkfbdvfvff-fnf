import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import gradio as gr
import httpx
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

# ── Config ──────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
HF_INDEX_BASE = os.environ.get(
    "ICMR_HF_INDEX_BASE",
    "https://huggingface.co/datasets/sckeptic/icrm-hitek-full-db-mixed/resolve/main",
).rstrip("/")
INDEX_SOURCE = os.environ.get("ICMR_INDEX_SOURCE", "remote").lower()
PARALLELISM = max(1, min(int(os.environ.get("ICMR_PARALLEL", "2")), 2))
THREADS_PER_CONN = max(1, min(int(os.environ.get("ICMR_THREADS_PER_CONN", "2")), 2))
DUPLICATE_CAP = 2
# Smart DB path: use /data (Render Disk / HF persistent storage) if it exists, else local
_default_db = "/data/keys.db" if os.path.isdir("/data") else os.path.join(BASE, "keys.db")
DB_PATH = os.environ.get("KEY_DB_PATH", _default_db)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "PRIYANSHU295")
SESSION_SECRET = os.environ.get("ADMIN_SESSION_SECRET", "").strip() or secrets.token_urlsafe(32)
SESSION_TTL = int(os.environ.get("ADMIN_SESSION_TTL", "28800"))
IST = ZoneInfo("Asia/Kolkata")
API_DEVELOPER = "@VORTEX_PRIYANSHU"
COOKIE_NAME = "admin_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"

SEARCH_FIELDS = [
    "name", "fathersName", "phoneNumber", "aadharNumber", "otherNumber",
    "address", "district", "pincode", "state", "town", "source",
]
NUMBER_FIELDS = ["phoneNumber", "aadharNumber", "otherNumber"]
REMOTE_INDEXES = {
    "phone": [f"{HF_INDEX_BASE}/idx_phone.{i}.parquet" for i in range(7)],
    "aadhar": [f"{HF_INDEX_BASE}/idx_aadhar.{i}.parquet" for i in range(7)],
}

# ── Lightweight SQLite key store ────────────────────────────────────────────
_db_lock = threading.RLock()

def db():
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_db():
    with _db_lock, db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            plan TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            owner TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            daily_limit INTEGER,
            requests_today INTEGER NOT NULL DEFAULT 0,
            request_counter_date TEXT NOT NULL,
            total_usage INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT,
            revoked_at TEXT,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_keys_key ON api_keys(key);
        CREATE INDEX IF NOT EXISTS idx_keys_owner ON api_keys(owner);
        CREATE INDEX IF NOT EXISTS idx_keys_status ON api_keys(status);
        CREATE INDEX IF NOT EXISTS idx_keys_plan ON api_keys(plan);
        CREATE TABLE IF NOT EXISTS request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_id INTEGER,
            endpoint TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(key_id) REFERENCES api_keys(id)
        );
        CREATE INDEX IF NOT EXISTS idx_request_log_created ON request_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_request_log_key ON request_log(key_id);
        CREATE TABLE IF NOT EXISTS key_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            website TEXT,
            requirement TEXT NOT NULL,
            details TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_key_requests_created ON key_requests(created_at);
        CREATE INDEX IF NOT EXISTS idx_key_requests_status ON key_requests(status);
        """)

init_db()


def now_utc():
    return datetime.now(timezone.utc)


def now_ist():
    return now_utc().astimezone(IST)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def display_time(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone(IST).strftime("%d/%m/%Y %H:%M IST")
    except Exception:
        return str(value)


def day_key():
    return now_ist().date().isoformat()


def plan_expiry(plan):
    p = plan.lower()
    if p == "day": return now_utc() + timedelta(days=1)
    if p == "week": return now_utc() + timedelta(days=7)
    if p == "month": return now_utc() + timedelta(days=30)
    if p == "lifetime": return None
    raise ValueError("plan must be day, week, month, or lifetime")


def make_key():
    return secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]


def make_owner(owner):
    # FIX: return owner as-is, no random suffix appended
    owner = (owner or "").strip()
    if not owner: raise ValueError("owner is required")
    return owner


def row_dict(row):
    d = dict(row)
    d["created_at"] = display_time(d.get("created_at"))
    d["expires_at"] = display_time(d.get("expires_at")) if d.get("expires_at") else "LIFETIME"
    d["last_used_at"] = display_time(d.get("last_used_at"))
    d["revoked_at"] = display_time(d.get("revoked_at"))
    return d


def create_key(plan, owner, daily_limit, note):
    if plan not in {"day", "week", "month", "lifetime"}: raise ValueError("invalid plan")
    if daily_limit != "unlimited":
        daily_limit = int(daily_limit)
        if daily_limit < 1 or daily_limit > 10_000_000: raise ValueError("daily limit must be 1..10000000 or unlimited")
    key = make_key()
    expires = plan_expiry(plan)
    owner_full = make_owner(owner)
    created = iso(now_utc())
    with _db_lock, db() as con:
        con.execute("INSERT INTO api_keys(key,plan,created_at,expires_at,owner,status,daily_limit,request_counter_date,note) VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, plan, created, iso(expires), owner_full, "active", None if daily_limit == "unlimited" else daily_limit, day_key(), (note or "").strip()[:500]))
        row = con.execute("SELECT * FROM api_keys WHERE key=?", (key,)).fetchone()
    return row_dict(row)


def auth_key_from_request(request):
    return (request.headers.get("X-API-Key") or request.query_params.get("api_key") or "").strip()


def api_error(status, message, extra=None):
    payload = {"error": message}
    if extra: payload.update(extra)
    payload["api_developer"] = API_DEVELOPER
    return JSONResponse(payload, status_code=status)


def validate_and_count_api_key(raw_key, endpoint):
    if not raw_key: return None, api_error(401, "API key is required")
    today = day_key()
    with _db_lock, db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM api_keys WHERE key=?", (raw_key,)).fetchone()
        if not row:
            con.execute("ROLLBACK")
            return None, api_error(401, "Invalid API key")
        if row["status"] == "revoked":
            con.execute("ROLLBACK")
            return None, api_error(401, "API key has been revoked")
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= now_utc():
            con.execute("UPDATE api_keys SET status='expired' WHERE id=?", (row["id"],))
            con.execute("COMMIT")
            return None, api_error(401, "API key expired", {
                "api_key_valid_till": display_time(row["expires_at"]), "api_key_plan": row["plan"]})
        count = row["requests_today"] if row["request_counter_date"] == today else 0
        limit = row["daily_limit"]
        if limit is not None and count >= limit:
            con.execute("ROLLBACK")
            return None, api_error(429, "Daily request limit exceeded", {
                "requests_today": count, "daily_limit": limit,
                "api_key_plan": row["plan"], "api_key_valid_till": display_time(row["expires_at"])})
        new_count = count + 1
        now = iso(now_utc())
        con.execute("UPDATE api_keys SET requests_today=?, request_counter_date=?, total_usage=total_usage+1, last_used_at=? WHERE id=?",
                    (new_count, today, now, row["id"]))
        con.execute("INSERT INTO request_log(key_id,endpoint,created_at) VALUES(?,?,?)", (row["id"], endpoint, now))
        con.execute("COMMIT")
        row = con.execute("SELECT * FROM api_keys WHERE id=?", (row["id"],)).fetchone()
    return row, None


def add_api_fields(payload, key_row):
    payload["api_key_owner"] = key_row["owner"]
    payload["api_key_valid_till"] = display_time(key_row["expires_at"]) if key_row["expires_at"] else "LIFETIME"
    payload["api_key_plan"] = key_row["plan"]
    payload["api_developer"] = API_DEVELOPER
    return payload

# ── DuckDB Connection Pool ──────────────────────────────────────────────────
_conns = []
_conns_lock = threading.Lock()
_thread_local = threading.local()
pool = ThreadPoolExecutor(max_workers=PARALLELISM, thread_name_prefix="duck")

def _idx_ready(kind): return kind in REMOTE_INDEXES

def _new_conn():
    con = duckdb.connect()
    con.execute("SET home_directory='/tmp'")
    con.execute("SET extension_directory='/tmp/duckdb_extensions'")
    con.execute("INSTALL parquet; LOAD parquet;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    for kind, urls in REMOTE_INDEXES.items():
        view = f"people_{kind}"
        lst = ", ".join(f"'{u}'" for u in urls)
        con.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM read_parquet([{lst}])")
    con.execute(f"SET threads = {THREADS_PER_CONN}")
    return con

def _thread_id():
    tid = getattr(_thread_local, "id", None)
    if tid is None:
        with _conns_lock:
            tid = len(_conns); _thread_local.id = tid
    return tid

def _get_conn():
    ident = _thread_id()
    with _conns_lock:
        while len(_conns) <= ident: _conns.append(_new_conn())
    return _conns[ident]

# ── Search Logic ────────────────────────────────────────────────────────────
def _person_key(row):
    ph = (row.get("phoneNumber") or "").strip(); ad = (row.get("aadharNumber") or "").strip()
    return (ph, ad) if (ph or ad) else ((row.get("name") or "").strip(), (row.get("fathersName") or "").strip())

def _connected_numbers(row):
    connected, seen = [], set()
    for field in NUMBER_FIELDS:
        raw = row.get(field)
        if raw is None: continue
        value = str(raw).strip()
        if value and value not in seen:
            seen.add(value); connected.append({"field": field, "value": value})
    return connected

def _cap_duplicates(rows):
    seen, out = {}, []
    for r in rows:
        k = _person_key(r); n = seen.get(k, 0)
        if n < DUPLICATE_CAP:
            seen[k] = n + 1; record = dict(r); record["connected_numbers"] = _connected_numbers(record); out.append(record)
    return out

def _run_field_search(field, value, mode, limit):
    if field not in SEARCH_FIELDS: raise ValueError(f"Unknown field: {field}")
    v = value.replace("'", "''")
    if mode == "exact":
        if field == "phoneNumber" and _idx_ready("phone"): view = "people_phone"
        elif field == "aadharNumber" and _idx_ready("aadhar"): view = "people_aadhar"
        else: return {"field": field, "value": value, "mode": mode, "count": 0, "results": []}
        sql = f"SELECT * FROM {view} WHERE {field} = '{v}' LIMIT {limit * DUPLICATE_CAP + 20}"
    elif mode == "contains":
        if field == "name": return {"field": field, "value": value, "mode": mode, "count": 0, "results": []}
        v2 = v.replace("%", r"\%").replace("_", r"\_")
        sql = f"SELECT * FROM people_phone WHERE {field} ILIKE '%{v2}%' ESCAPE '\\' LIMIT {limit * DUPLICATE_CAP + 20}"
    else: raise ValueError(f"Unknown mode: {mode}")
    con = _get_conn(); rows = con.execute(sql).fetchall(); cols = [d[0] for d in con.description]
    results = _cap_duplicates([dict(zip(cols, r)) for r in rows])[:limit]
    return {"field": field, "value": value, "mode": mode, "count": len(results), "results": results}

def _unified_search(q, limit=10):
    q = q.strip(); is_num = q.isdigit() and len(q) >= 8
    if not is_num: return {"query": q, "searched_fields": [], "count": 0, "results": []}
    all_rows, searched = [], []
    if _idx_ready("phone"):
        r = _run_field_search("phoneNumber", q, "exact", limit); all_rows.extend(r["results"]); searched.append("phoneNumber")
    if not all_rows and _idx_ready("aadhar"):
        r = _run_field_search("aadharNumber", q, "exact", limit); all_rows.extend(r["results"]); searched.append("aadharNumber")
    all_rows = _cap_duplicates(all_rows)[:limit]
    return {"query": q, "searched_fields": searched, "count": len(all_rows), "results": all_rows}

# ── FastAPI ─────────────────────────────────────────────────────────────────
fastapi_app = FastAPI(title="ICMR + HITEK Search API")

@fastapi_app.exception_handler(HTTPException)
async def json_http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/search") or request.url.path.startswith("/admin-panel/api"):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse({"error": detail, "api_developer": API_DEVELOPER}, status_code=exc.status_code, headers=exc.headers)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

@fastapi_app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/search") or request.url.path.startswith("/admin-panel/api"):
        return JSONResponse({"error": "Validation error", "api_developer": API_DEVELOPER}, status_code=422)
    return JSONResponse({"detail": "Validation error"}, status_code=422)

class BatchRequest(BaseModel):
    queries: list[dict[str, Any]]
    limit: int = 10

@fastapi_app.get("/")
def root():
    return {"app":"ICMR + HITEK Search API","records":2_504_793_870,"indexes":{"phone":_idx_ready("phone"),"aadhar":_idx_ready("aadhar")},"index_source":INDEX_SOURCE,"columns":SEARCH_FIELDS,"docs":"/docs","developer":API_DEVELOPER}

@fastapi_app.get("/health")
def health():
    return {"status":"ok","raw_database_required":False,"indexes":{"phone":_idx_ready("phone"),"aadhar":_idx_ready("aadhar")},"index_source":INDEX_SOURCE,"api_developer":API_DEVELOPER}

@fastapi_app.get("/search")
async def search(request: Request, q: str|None=Query(None), mobile: str|None=Query(None), field: str|None=Query(None), mode: str=Query("exact"), limit: int=Query(10,ge=1,le=1000), pretty: bool=Query(True)):
    key_row, err = validate_and_count_api_key(auth_key_from_request(request), "/search")
    if err: return err
    q_val=(q or mobile or "").strip()
    if not q_val: return api_error(422,"Provide q or mobile")
    loop=asyncio.get_running_loop()
    try:
        data=await loop.run_in_executor(pool,_run_field_search,field,q_val,mode,limit) if field else await loop.run_in_executor(pool,_unified_search,q_val,limit)
    except Exception as exc:
        return api_error(400,str(exc))
    result=add_api_fields({"success":bool(data["count"]),**data,"number":q_val,"total":data["count"]},key_row)
    return Response(content=json.dumps(result,indent=2 if pretty else None,ensure_ascii=False),media_type="application/json")

@fastapi_app.post("/search/parallel")
async def search_parallel(request: Request, req: BatchRequest):
    key_row, err=validate_and_count_api_key(auth_key_from_request(request),"/search/parallel")
    if err: return err
    if not req.queries: return api_error(400,"queries must not be empty")
    if len(req.queries)>50: return api_error(400,"max 50 queries per batch")
    loop=asyncio.get_running_loop()
    try:
        tasks=[loop.run_in_executor(pool,_run_field_search,item.get("field","phoneNumber"),item.get("value",""),item.get("mode","exact"),min(int(item.get("limit",req.limit)),1000)) for item in req.queries]
        results=await asyncio.gather(*tasks)
    except Exception as exc:
        return api_error(400,str(exc))
    payload=add_api_fields({"searches":len(req.queries),"results":list(results)},key_row)
    return Response(content=json.dumps(payload,indent=2,ensure_ascii=False),media_type="application/json")

# ── Public API-key request workflow ────────────────────────────────────────
@fastapi_app.post("/api/key-request")
async def submit_key_request(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    website = str(data.get("website", "")).strip()
    requirement = str(data.get("requirement", "Single-Page Lead Engine")).strip()
    details = str(data.get("details", "")).strip()
    if not name or len(name) > 120:
        raise HTTPException(400, "Please enter a valid name")
    if "@" not in email or len(email) > 180:
        raise HTTPException(400, "Please enter a valid work/brand email")
    if len(website) > 300 or len(details) > 4000:
        raise HTTPException(400, "Request details are too long")
    created = iso(now_utc())
    with _db_lock, db() as con:
        cur = con.execute(
            "INSERT INTO key_requests(name,email,website,requirement,details,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (name, email, website, requirement, details, "pending", created),
        )
        request_id = cur.lastrowid
    return {
        "success": True,
        "request_id": request_id,
        "message": "Request received. An administrator can review it and generate the API key from the Key Console.",
        "api_developer": API_DEVELOPER,
    }

# ── Admin session ───────────────────────────────────────────────────────────
def session_token():
    exp=int(now_utc().timestamp())+SESSION_TTL
    body=f"{exp}:{secrets.token_urlsafe(12)}"
    sig=hmac.new(SESSION_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+"."+sig

def valid_session(request):
    token=request.cookies.get(COOKIE_NAME,"")
    try:
        body,sig=token.rsplit(".",1); exp=int(body.split(":",1)[0])
        return exp>int(now_utc().timestamp()) and hmac.compare_digest(sig,hmac.new(SESSION_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest())
    except Exception: return False

def admin_guard(request):
    if not valid_session(request): raise HTTPException(401,"Admin authentication required")

_ADMIN_TPLT = """<!doctype html>
<html lang="en" class="scroll-smooth">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Figtree:ital,wght@0,300..900;1,300..900&family=Space+Grotesk:wght@300..700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config={theme:{extend:{colors:{forest:{DEFAULT:'#1B4332',dark:'#112D22',light:'#2D6A4F'},accent:{DEFAULT:'#40916C',light:'#52B788',soft:'#74C69D'},surface:{DEFAULT:'#F3F6F1',card:'#E8EFE5',dark:'#0D1F17'},bodytext:'#14231A'},fontFamily:{heading:['Space Grotesk','sans-serif'],sans:['Figtree','sans-serif']}}}}
</script>
<style>
body{font-family:'Figtree',sans-serif}
h1,h2,h3,h4,h5,h6{font-family:'Space Grotesk',sans-serif}
.dark-glass{background:rgba(17,45,34,.85);backdrop-filter:blur(16px);border:1px solid rgba(82,183,136,.25)}
::-webkit-scrollbar{width:8px}::-webkit-scrollbar-track{background:#07130E}::-webkit-scrollbar-thumb{background:#40916C;border-radius:4px}
/* Admin legacy classes (used by ADMIN_JS) */
.page-title{font-size:1.55rem;font-weight:800;letter-spacing:-.4px;color:#fff;padding:4px 0 2px;font-family:'Space Grotesk',sans-serif}
.page-sub{color:#8d97aa;font-size:12px;margin-bottom:16px}
.card{background:rgba(17,45,34,.75);backdrop-filter:blur(14px);border:1px solid rgba(82,183,136,.2);border-radius:16px;padding:20px;margin-bottom:16px;position:relative;overflow:hidden}
.card:before{content:"";position:absolute;left:0;right:0;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(64,145,108,.5),rgba(82,183,136,.3),transparent)}
.card h2{font-size:15px;font-weight:700;border-bottom:1px solid rgba(255,255,255,.08);padding-bottom:12px;margin-bottom:15px;color:#f5f7fb;font-family:'Space Grotesk',sans-serif}
.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin-bottom:16px}
.stat{background:rgba(27,67,50,.4);border:1px solid rgba(64,145,108,.25);border-radius:14px;padding:15px 16px;transition:.2s}
.stat:hover{border-color:rgba(82,183,136,.5);transform:translateY(-2px);background:rgba(27,67,50,.6)}
.stat small{display:block;color:#74C69D;font-size:10px;margin-bottom:7px;text-transform:uppercase;letter-spacing:1px;font-weight:600}
.stat strong{display:block;font-size:24px;font-weight:800;color:#fff}
label{display:block;font-size:11px;font-weight:650;margin:12px 0 5px;color:#74C69D;text-transform:uppercase;letter-spacing:.5px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid rgba(82,183,136,.3);border-radius:11px;background:rgba(7,19,14,.6);font-size:13px;color:#eef2f8;outline:none;transition:.2s;font-family:'Figtree',sans-serif}
input::placeholder,textarea::placeholder{color:#5f697b}
input:focus,select:focus,textarea:focus{border-color:rgba(64,145,108,.9);box-shadow:0 0 0 3px rgba(64,145,108,.15)}
select option{background:#0B1D15;color:#fff}
.btn{display:inline-block;padding:9px 14px;border-radius:10px;cursor:pointer;font-size:12px;border:1px solid rgba(255,255,255,.12);text-decoration:none;transition:.2s;line-height:1.4;vertical-align:middle;font-family:'Figtree',sans-serif}
.btn-p{background:linear-gradient(135deg,#1B4332,#40916C);border-color:rgba(82,183,136,.4);color:#fff;box-shadow:0 4px 16px rgba(27,67,50,.3)}
.btn-p:hover{filter:brightness(1.14);transform:translateY(-1px)}
.btn-p:active{transform:translateY(0)}
.btn-s{background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.12);color:#dce2ee}
.btn-s:hover{background:rgba(255,255,255,.09)}
.btn-r{background:rgba(251,113,133,.06);border-color:rgba(251,113,133,.35);color:#fda4af;font-size:12px;padding:5px 9px}
.btn-r:hover{background:rgba(251,113,133,.14)}
.btn-del{background:rgba(239,68,68,.12);border-color:rgba(248,113,113,.35);color:#fecaca;font-size:12px;padding:5px 9px}
.btn-del:hover{background:rgba(239,68,68,.24)}
.btn-sm{padding:5px 10px;font-size:11px}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
.row>*{flex:1;min-width:140px}
table{width:100%;border-collapse:collapse;min-width:980px;font-size:12px}
thead{background:rgba(27,67,50,.3)}
th{padding:11px 12px;text-align:left;font-weight:650;border-bottom:1px solid rgba(82,183,136,.2);color:#74C69D;white-space:nowrap;text-transform:uppercase;font-size:10px;letter-spacing:.5px}
td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:middle;color:#cfd6e3}
tr:hover td{background:rgba(64,145,108,.06)}
.scroll{overflow-x:auto;scrollbar-width:thin;scrollbar-color:#40916C transparent}
.scroll::-webkit-scrollbar{height:6px}
.scroll::-webkit-scrollbar-thumb{background:#40916C;border-radius:999px}
.badge{display:inline-block;padding:3px 8px;border-radius:999px;font-size:9px;font-weight:750;text-transform:uppercase;letter-spacing:.5px}
.active{background:rgba(52,211,153,.10);color:#6ee7b7;border:1px solid rgba(52,211,153,.28)}
.revoked{background:rgba(251,113,133,.10);color:#fda4af;border:1px solid rgba(251,113,133,.28)}
.expired{background:rgba(148,163,184,.09);color:#aab3c2;border:1px solid rgba(148,163,184,.2)}
pre{background:rgba(0,0,0,.2);border:1px solid rgba(82,183,136,.2);padding:12px;border-radius:11px;font-size:12px;word-break:break-all;white-space:pre-wrap;margin:8px 0;color:#74C69D}
code{font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;font-size:11px;color:#74C69D}
.key-box{background:linear-gradient(135deg,rgba(27,67,50,.3),rgba(64,145,108,.1));border:1px solid rgba(52,211,153,.25);border-radius:14px;padding:16px;margin-top:14px}
.key-box-title{color:#6ee7b7;font-weight:700;font-size:13px;margin-bottom:8px}
.small{font-size:11px;color:#8d97aa}
.msg-err{background:rgba(251,113,133,.09);border:1px solid rgba(251,113,133,.3);color:#fda4af;padding:10px 14px;border-radius:10px;margin-top:12px;font-size:12px;display:none}
.chart-wrap{display:flex;align-items:flex-end;gap:8px;height:130px;padding-top:10px}
.chart-wrap>div>div:first-child{background:linear-gradient(180deg,#2D6A4F,#52B788)!important;box-shadow:0 0 14px rgba(64,145,108,.25)}
.settings-table td{padding:8px 20px 8px 0;border:none}
.settings-table td:first-child{color:#74C69D;font-weight:650;white-space:nowrap}
section{margin-bottom:12px}
@media(max-width:1050px){.grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.row>*{min-width:100%}.grid{grid-template-columns:repeat(2,1fr)}.card{padding:15px}}
</style>
<script>async function logout(){await fetch('/admin-panel/logout',{method:'POST'});location.href='/admin-panel'}</script>
</head>
<body class="bg-[#07130E] antialiased text-white selection:bg-accent selection:text-white">

<!-- HEADER (indgc.html style, adapted for admin) -->
<header class="sticky top-0 z-50 bg-[#0B1D15]/95 backdrop-blur-xl border-b border-emerald-500/20 shadow-2xl">
    <div class="bg-[#07130E] border-b border-emerald-900/40 py-1.5 px-4 text-xs font-mono text-gray-300">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <span class="inline-flex items-center gap-1.5 text-emerald-400 font-medium">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                ADMIN PANEL &nbsp;&middot;&nbsp; SECURE SESSION
            </span>
            <span class="text-emerald-400 flex items-center gap-1.5 text-[11px]">
                <i class="fa-solid fa-shield-halved"></i> Authenticated
            </span>
        </div>
    </div>
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
            <a href="/admin-panel" class="flex items-center gap-3 group">
                <div class="relative">
                    <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 via-forest-light to-forest p-0.5 shadow-lg shadow-emerald-900/40">
                        <div class="w-full h-full bg-[#0D241B] rounded-[9px] flex items-center justify-center text-emerald-400 group-hover:text-white transition-colors">
                            <i class="fa-solid fa-shield-halved text-lg"></i>
                        </div>
                    </div>
                </div>
                <div class="flex flex-col">
                    <div class="flex items-center gap-1.5">
                        <span class="font-heading font-black text-lg tracking-tight text-white group-hover:text-emerald-300 transition-colors">PRIYANSHU</span>
                        <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">ADMIN</span>
                    </div>
                    <span class="font-heading text-[10px] font-semibold tracking-widest text-emerald-400/80 uppercase">VORTEX API Management</span>
                </div>
            </a>
            <nav class="hidden md:flex items-center p-1 bg-[#07150F]/80 border border-emerald-800/30 rounded-full shadow-inner">
                <a href="#dashboard" class="px-3 py-1.5 text-xs font-semibold rounded-full text-gray-300 hover:text-white hover:bg-emerald-800/40 transition-all">Dashboard</a>
                <a href="#generate" class="px-3 py-1.5 text-xs font-semibold rounded-full text-gray-300 hover:text-white hover:bg-emerald-800/40 transition-all">Generate Key</a>
                <a href="#keys" class="px-3 py-1.5 text-xs font-semibold rounded-full text-gray-300 hover:text-white hover:bg-emerald-800/40 transition-all">Manage Keys</a>
                <a href="#csv" class="px-3 py-1.5 text-xs font-semibold rounded-full text-gray-300 hover:text-white hover:bg-emerald-800/40 transition-all">Import/Export</a>
                <a href="#settings" class="px-3 py-1.5 text-xs font-semibold rounded-full text-gray-300 hover:text-white hover:bg-emerald-800/40 transition-all">Settings</a>
            </nav>
            <button onclick="logout()" class="hidden md:flex items-center gap-2 px-4 py-2 rounded-full border border-red-500/30 text-red-400 text-xs font-semibold hover:bg-red-500/10 transition-all">
                <i class="fa-solid fa-right-from-bracket text-xs"></i> Sign Out
            </button>
        </div>
    </div>
</header>

<main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
__BODY__
</main>

<footer class="border-t border-emerald-900/30 mt-8">
    <div class="max-w-7xl mx-auto px-4 py-5 flex items-center justify-between text-xs text-gray-600">
        <span>&copy; 2024 VORTEX &nbsp;&middot;&nbsp; Developer: <b class="text-emerald-700">@VORTEX_PRIYANSHU</b></span>
        <span class="text-emerald-800">ICMR + HITEK Search API &nbsp;&middot;&nbsp; Admin Panel</span>
    </div>
</footer>

<script>__SCRIPT__</script>
</body>
</html>"""

def admin_page(title, body, script=""):
    from html import escape
    return HTMLResponse(
        _ADMIN_TPLT
        .replace('__TITLE__', escape(title))
        .replace('__BODY__', body)
        .replace('__SCRIPT__', script)
    )

LOGIN_HTML='''
<div class="min-h-[82vh] flex items-center justify-center px-4 py-12">
  <div class="w-full max-w-md">
    <div class="text-center mb-8">
      <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-emerald-500 via-forest-light to-forest flex items-center justify-center mx-auto mb-4 shadow-2xl shadow-emerald-900/50">
        <i class="fa-solid fa-shield-halved text-white text-2xl"></i>
      </div>
      <h1 class="font-heading font-black text-3xl text-white tracking-tight">PRIYANSHU</h1>
      <p class="text-emerald-400 text-xs font-semibold tracking-widest uppercase mt-1.5">VORTEX &nbsp;&middot;&nbsp; Admin Access</p>
    </div>
    <div class="dark-glass rounded-2xl p-8">
      <h2 class="font-heading text-white font-bold text-lg mb-6 pb-4 border-b border-emerald-500/20 flex items-center gap-2.5">
        <span class="w-2 h-2 rounded-full bg-emerald-400 inline-block" style="animation:lgpulse 2s infinite"></span>
        Sign in to Admin Panel
      </h2>
      <style>@keyframes lgpulse{0%,100%{opacity:1}50%{opacity:.35}}</style>
      <label class="block text-xs font-semibold text-emerald-400 uppercase tracking-widest mb-2" for="pwd">Admin Password</label>
      <input id="pwd" type="password" autocomplete="current-password" placeholder="Enter your password…"
             style="width:100%;padding:11px 14px;border:1px solid rgba(82,183,136,.3);border-radius:12px;background:rgba(7,19,14,.7);font-size:14px;color:#eef2f8;outline:none;transition:.2s;font-family:Figtree,sans-serif;margin-bottom:4px">
      <div id="errmsg" class="msg-err" style="margin-top:10px"></div>
      <button class="btn btn-p" style="width:100%;margin-top:18px;padding:12px;text-align:center;font-size:14px;font-weight:700;letter-spacing:.3px;display:flex;align-items:center;justify-content:center;gap:8px" onclick="doLogin()">
        <i class="fa-solid fa-key text-xs"></i> Sign In
      </button>
      <p style="text-align:center;font-size:10px;color:#4b5563;margin-top:20px;padding-top:14px;border-top:1px solid rgba(255,255,255,.06)">
        @VORTEX_PRIYANSHU &nbsp;&middot;&nbsp; ICMR + HITEK Search API
      </p>
    </div>
  </div>
</div>'''

LOGIN_JS='''function doLogin(){
  var p=document.getElementById("pwd"),m=document.getElementById("errmsg");
  m.style.display="none";
  fetch("/admin-panel/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:p.value})})
    .then(function(r){if(r.ok){location.href="/admin-panel"}else{r.json().then(function(x){m.textContent=x.detail||"Incorrect password. Try again.";m.style.display="block"})}})
    .catch(function(){m.textContent="Network error. Please try again.";m.style.display="block"});
}
document.addEventListener("keydown",function(e){if(e.key==="Enter")doLogin()});
'''

@fastapi_app.get("/admin-panel", response_class=HTMLResponse)
def admin_panel(request: Request):
    if not valid_session(request): return admin_page("API Key Admin", LOGIN_HTML, LOGIN_JS)
    body='''<div id="app"></div>'''
    return admin_page("API Key Admin", body, ADMIN_JS)

@fastapi_app.post("/admin-panel/login")
async def admin_login(request: Request):
    try: data=await request.json()
    except Exception: data={}
    supplied=str(data.get("password", ""))
    if not hmac.compare_digest(supplied, ADMIN_PASSWORD): raise HTTPException(401,"Incorrect password")
    r=JSONResponse({"success":True,"api_developer":API_DEVELOPER}); r.set_cookie(COOKIE_NAME,session_token(),httponly=True,secure=COOKIE_SECURE,samesite="lax",max_age=SESSION_TTL,path="/"); return r

@fastapi_app.post("/admin-panel/logout")
def admin_logout(request: Request):
    admin_guard(request); r=JSONResponse({"success":True,"api_developer":API_DEVELOPER}); r.delete_cookie(COOKIE_NAME,path="/"); return r

@fastapi_app.get("/admin-panel/api/stats")
def admin_stats(request: Request):
    admin_guard(request)
    with db() as con:
        total=con.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        active=con.execute("SELECT COUNT(*) FROM api_keys WHERE status='active' AND (expires_at IS NULL OR expires_at>?)",(iso(now_utc()),)).fetchone()[0]
        expired=con.execute("SELECT COUNT(*) FROM api_keys WHERE status='expired' OR (status='active' AND expires_at IS NOT NULL AND expires_at<=?)",(iso(now_utc()),)).fetchone()[0]
        revoked=con.execute("SELECT COUNT(*) FROM api_keys WHERE status='revoked'").fetchone()[0]
        today=day_key(); requests_today=con.execute("SELECT COUNT(*) FROM request_log WHERE created_at>=?",(iso(now_ist().replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)),)).fetchone()[0]
        total_req=con.execute("SELECT COALESCE(SUM(total_usage),0) FROM api_keys").fetchone()[0]
        most=con.execute("SELECT owner,plan,key,total_usage FROM api_keys ORDER BY total_usage DESC LIMIT 1").fetchone()
        last=con.execute("SELECT r.created_at,k.owner,k.key,r.endpoint FROM request_log r LEFT JOIN api_keys k ON k.id=r.key_id ORDER BY r.id DESC LIMIT 1").fetchone()
        chart=[]
        for i in range(6,-1,-1):
            d=now_ist().date()-timedelta(days=i); start=datetime.combine(d,datetime.min.time(),IST).astimezone(timezone.utc).isoformat(timespec="seconds"); end=datetime.combine(d+timedelta(days=1),datetime.min.time(),IST).astimezone(timezone.utc).isoformat(timespec="seconds")
            chart.append({"day":d.strftime("%d/%m"),"count":con.execute("SELECT COUNT(*) FROM request_log WHERE created_at>=? AND created_at<?",(start,end)).fetchone()[0]})
    return {"total_keys":total,"active_keys":active,"expired_keys":expired,"revoked_keys":revoked,"requests_today":requests_today,"total_requests":total_req,"most_used":dict(most) if most else None,"last_request":dict(last) if last else None,"chart":chart,"api_developer":API_DEVELOPER}

@fastapi_app.get("/admin-panel/api/key-requests")
def admin_key_requests(request: Request):
    admin_guard(request)
    with db() as con:
        rows = con.execute(
            "SELECT id,name,email,website,requirement,details,status,created_at "
            "FROM key_requests ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return {"requests": [dict(r) for r in rows], "api_developer": API_DEVELOPER}

@fastapi_app.post("/admin-panel/api/keys")
async def admin_create_key(request: Request):
    admin_guard(request); data=await request.json()
    try:
        result=create_key(str(data.get("plan","day")),str(data.get("owner","")),data.get("daily_limit","unlimited"),str(data.get("note", "")))
        result["api_developer"]=API_DEVELOPER
        return result
    except Exception as exc: raise HTTPException(400,str(exc))

@fastapi_app.get("/admin-panel/api/keys")
def admin_list_keys(request: Request, q: str="", status: str="all", plan: str="all"):
    admin_guard(request); clauses=[]; args=[]
    if q: clauses.append("(owner LIKE ? OR key LIKE ? OR note LIKE ?)"); args += [f"%{q}%"]*3
    if status in {"active","expired","revoked"}: clauses.append("status=?"); args.append(status)
    if plan in {"day","week","month","lifetime"}: clauses.append("plan=?"); args.append(plan)
    sql="SELECT * FROM api_keys"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY id DESC LIMIT 500"
    with db() as con: rows=con.execute(sql,args).fetchall()
    out=[]
    now=now_utc()
    for r in rows:
        d=dict(r)
        if d["status"]=="active" and d["expires_at"] and datetime.fromisoformat(d["expires_at"])<=now: d["status"]="expired"
        out.append(row_dict(d))
    return {"keys": out, "api_developer": API_DEVELOPER}

@fastapi_app.post("/admin-panel/api/keys/{key}/revoke")
def admin_revoke(request: Request,key: str):
    admin_guard(request)
    with _db_lock, db() as con:
        cur=con.execute("UPDATE api_keys SET status='revoked',revoked_at=? WHERE key=? AND status!='revoked'",(iso(now_utc()),key))
    if cur.rowcount==0: raise HTTPException(404,"Key not found or already revoked")
    return {"success":True,"api_developer":API_DEVELOPER}

@fastapi_app.delete("/admin-panel/api/keys/{key}")
def admin_delete_key(request: Request, key: str):
    admin_guard(request)
    with _db_lock, db() as con:
        cur=con.execute("DELETE FROM api_keys WHERE key=? AND status='revoked'",(key,))
    if cur.rowcount==0: raise HTTPException(404,"Key not found or not in revoked status — revoke it first")
    return {"success":True,"api_developer":API_DEVELOPER}

@fastapi_app.get("/admin-panel/api/export.csv")
def admin_export(request: Request):
    admin_guard(request)
    cols=["key","owner","plan","status","daily_limit","requests_today","request_counter_date","total_usage","created_at","expires_at","last_used_at","revoked_at","note"]
    with db() as con: rows=con.execute("SELECT "+",".join(cols)+" FROM api_keys ORDER BY id").fetchall()
    out=io.StringIO(); w=csv.writer(out); w.writerow(cols); w.writerows([tuple(r[c] for c in cols) for r in rows]); out.seek(0)
    return StreamingResponse(iter([out.getvalue().encode()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=api_keys.csv"})

@fastapi_app.post("/admin-panel/api/import")
async def admin_import(request: Request, file: UploadFile=File(...), mode: str="merge"):
    admin_guard(request)
    if not (file.filename or "").lower().endswith(".csv"): raise HTTPException(400,"CSV file required")
    raw=await file.read()
    if len(raw)>5*1024*1024: raise HTTPException(413,"CSV too large (5 MB max)")
    try: rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except Exception as exc: raise HTTPException(400,f"Invalid CSV: {exc}")
    required={"key","owner","plan","status","daily_limit","requests_today","request_counter_date","total_usage","created_at","expires_at","last_used_at","revoked_at","note"}
    if not rows or not required.issubset(rows[0].keys()): raise HTTPException(400,"Missing required CSV columns")
    valid=[]
    for r in rows:
        if len(r.get("key", ""))!=32 or r.get("plan") not in {"day","week","month","lifetime"} or r.get("status") not in {"active","expired","revoked"}: continue
        try: dl=None if str(r.get("daily_limit","")).lower() in {"","none","unlimited"} else int(r["daily_limit"]); rt=int(r["requests_today"]); tu=int(r["total_usage"])
        except ValueError: continue
        valid.append((r["key"],r["plan"],r["created_at"],r["expires_at"] or None,r["owner"],r["status"],dl,rt,r["request_counter_date"],tu,r["last_used_at"] or None,r["revoked_at"] or None,r.get("note","")))
    with _db_lock, db() as con:
        if mode=="replace": con.execute("DELETE FROM api_keys")
        added=0; skipped=0
        for vals in valid:
            try: con.execute("INSERT INTO api_keys(key,plan,created_at,expires_at,owner,status,daily_limit,requests_today,request_counter_date,total_usage,last_used_at,revoked_at,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",vals); added+=1
            except sqlite3.IntegrityError: skipped+=1
    return {"success":True,"added":added,"skipped":skipped,"invalid":len(rows)-len(valid),"mode":mode,"api_developer":API_DEVELOPER}

ADMIN_JS=r'''
const esc=s=>String(s??"").replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(u,o){var r=await fetch(u,o);if(r.status===401){location.href='/admin-panel';throw 0}return r}

async function load(){
  var s=await(await api('/admin-panel/api/stats')).json();
  var kx=await(await api('/admin-panel/api/keys')).json();
  var rx=await(await api('/admin-panel/api/key-requests')).json();
  var k=kx.keys||[];
  var reqs=rx.requests||[];

  // Chart bars
  var mx=Math.max(1,...s.chart.map(function(x){return x.count}));
  var chart=s.chart.map(function(x){
    var h=Math.max(4,Math.round(x.count/mx*100));
    return '<div style="flex:1;text-align:center;min-width:28px">'
      +'<div title="'+x.count+' requests" style="height:'+h+'px;background:linear-gradient(180deg,#2D6A4F,#52B788);border-radius:4px 4px 0 0;transition:.3s;box-shadow:0 0 8px rgba(64,145,108,.3)"></div>'
      +'<div style="font-size:11px;color:#565959;margin-top:4px">'+x.day+'</div>'
      +'<div style="font-size:10px;color:#999">'+x.count+'</div>'
      +'</div>';
  }).join('');

  // Stats
  var SL=['Total Keys','Active','Expired','Revoked','Req Today','Total Req'];
  var SV=[s.total_keys,s.active_keys,s.expired_keys,s.revoked_keys,s.requests_today,s.total_requests];
  var SC=['#fff','#34d399','#8d97aa','#fb7185','#52B788','#52B788'];
  var statsHtml=SL.map(function(l,i){
    return '<div class="stat"><small>'+l+'</small><strong style="color:'+SC[i]+'">'+SV[i]+'</strong></div>';
  }).join('');

  // Table rows
  var rows=k.map(function(x){
    var actions='<button class="btn btn-s btn-sm" onclick="copyKey(\''+esc(x.key)+'\')">Copy</button> ';
    if(x.status==='active') actions+='<button class="btn btn-r" onclick="revokeKey(\''+esc(x.key)+'\')">Revoke</button>';
    if(x.status==='revoked') actions+='<button class="btn btn-del" onclick="deleteKey(\''+esc(x.key)+'\')">&#128465; Delete</button>';
    return '<tr>'
      +'<td><code style="font-size:11px;word-break:break-all">'+esc(x.key)+'</code></td>'
      +'<td><b>'+esc(x.owner)+'</b></td>'
      +'<td>'+esc(x.plan)+'</td>'
      +'<td><span class="badge '+x.status+'">'+esc(x.status)+'</span></td>'
      +'<td style="text-align:right">'+(x.daily_limit!=null?x.daily_limit:'&#8734;')+'</td>'
      +'<td style="text-align:right">'+x.requests_today+'/'+(x.daily_limit!=null?x.daily_limit:'&#8734;')+'</td>'
      +'<td style="text-align:right">'+x.total_usage+'</td>'
      +'<td>'+esc(x.expires_at)+'</td>'
      +'<td>'+esc(x.last_used_at)+'</td>'
      +'<td style="white-space:nowrap">'+actions+'</td>'
      +'</tr>';
  }).join('');

  document.getElementById('app').innerHTML=
  '<section id="dashboard">'
  +'<div class="page-title">Seller Central &mdash; Dashboard</div>'
  +'<div class="page-sub">Overview of API keys and usage statistics &nbsp;·&nbsp; Developer: <b>@VORTEX_PRIYANSHU</b></div>'
  +'<div class="grid">'+statsHtml+'</div>'
  +'<div class="card"><h2>Requests &mdash; Last 7 Days</h2><div class="chart-wrap">'+chart+'</div></div>'
  +(s.most_used?'<div class="card"><h2>Most Used Key</h2><p><b>'+esc(s.most_used.owner)+'</b> &nbsp;&middot;&nbsp; '+esc(s.most_used.plan)+' plan &nbsp;&middot;&nbsp; '+s.most_used.total_usage+' total requests</p></div>':'')
  +'</section>'

  +'<section id="requests" class="card">'
  +'<h2>API Key Requests <span class="small" style="font-weight:400">('+reqs.length+' recent)</span></h2>'
  +(reqs.length?'<div class="scroll"><table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Requirement</th><th>Status</th><th>Created</th></tr></thead><tbody>'+reqs.map(function(r){return '<tr><td>'+r.id+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.email)+'</td><td>'+esc(r.requirement)+'</td><td><span class="badge '+(r.status==='pending'?'active':r.status)+'">'+esc(r.status)+'</span></td><td>'+esc(r.created_at)+'</td></tr>'}).join('')+'</tbody></table></div>':'<p class="small">No API-key requests yet.</p>')
  +'</section>'

  +'<section id="generate" class="card">'
  +'<h2>Generate New API Key</h2>'
  +'<div class="row">'
  +'<div><label>Plan</label><select id="plan"><option value="day">1 Day</option><option value="week">7 Days</option><option value="month">30 Days</option><option value="lifetime">Lifetime</option></select></div>'
  +'<div><label>Owner</label><input id="owner" placeholder="@username or full name"></div>'
  +'<div><label>Daily Request Limit</label><input id="limit" value="100" placeholder="100 or unlimited"></div>'
  +'</div>'
  +'<label>Note <span style="color:#999;font-weight:400">(optional)</span></label>'
  +'<input id="note" placeholder="Customer name, purpose, testing…">'
  +'<div style="margin-top:14px"><button class="btn btn-p" onclick="gen()">Generate API Key</button></div>'
  +'<div id="generated"></div>'
  +'</section>'

  +'<section id="keys" class="card">'
  +'<h2>Manage API Keys <span class="small" style="font-weight:400">('+k.length+' keys)</span></h2>'
  +'<div class="row" style="margin-bottom:12px">'
  +'<div><label>Search</label><input id="q" oninput="filterKeys()" placeholder="Search owner, key, note…"></div>'
  +'<div><label>Status</label><select id="fstatus" onchange="filterKeys()"><option value="all">All Status</option><option value="active">Active</option><option value="expired">Expired</option><option value="revoked">Revoked</option></select></div>'
  +'<div><label>Plan</label><select id="fplan" onchange="filterKeys()"><option value="all">All Plans</option><option value="day">Day</option><option value="week">Week</option><option value="month">Month</option><option value="lifetime">Lifetime</option></select></div>'
  +'</div>'
  +'<div class="scroll"><table>'
  +'<thead><tr><th>API Key</th><th>Owner</th><th>Plan</th><th>Status</th><th>Limit/Day</th><th>Today</th><th>Total</th><th>Expires</th><th>Last Used</th><th>Actions</th></tr></thead>'
  +'<tbody>'+rows+'</tbody>'
  +'</table></div>'
  +'</section>'

  +'<section id="csv" class="card">'
  +'<h2>Import / Export CSV</h2>'
  +'<a class="btn btn-s" href="/admin-panel/api/export.csv" style="text-decoration:none">&#8595; Export CSV</a>'
  +'<div class="row" style="margin-top:14px">'
  +'<div><label>CSV File</label><input id="csvfile" type="file" accept=".csv"></div>'
  +'<div><label>Import Mode</label><select id="imode"><option value="merge">Merge (Add New Only)</option><option value="replace">Replace (Full Restore)</option></select></div>'
  +'<div style="flex:0;align-self:flex-end"><button class="btn btn-p" onclick="imp()">&#8593; Import</button></div>'
  +'</div>'
  +'<p id="csvmsg" class="small" style="margin-top:10px"></p>'
  +'</section>'

  +'<section id="settings" class="card">'
  +'<h2>Account &amp; Settings</h2>'
  +'<table class="settings-table" style="min-width:auto;border-collapse:collapse">'
  +'<tr><td>Developer</td><td><b>@VORTEX_PRIYANSHU</b></td></tr>'
  +'<tr><td>Timezone</td><td>Asia/Kolkata (IST)</td></tr>'
  +'<tr><td>Session</td><td>Secure HttpOnly Cookie (8 hours)</td></tr>'
  +'<tr><td>Plans</td><td>Day (1d) · Week (7d) · Month (30d) · Lifetime</td></tr>'
  +'<tr><td>Key Format</td><td>32-character URL-safe token</td></tr>'
  +'<tr><td>Max Keys Shown</td><td>500 per query</td></tr>'
  +'</table>'
  +'</section>';
  if(location.hash){
    setTimeout(function(){var el=document.querySelector(location.hash);if(el)el.scrollIntoView({behavior:'smooth',block:'start'})},80);
  }
}

async function gen(){
  var r=await api('/admin-panel/api/keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:plan.value,owner:owner.value,daily_limit:limit.value,note:note.value})});
  var x=await r.json();
  if(!r.ok){alert(x.detail||'Error generating key');return}
  document.getElementById('generated').innerHTML=
    '<div class="key-box">'
    +'<div class="key-box-title">&#10003; API Key Generated Successfully</div>'
    +'<pre id="newkey">'+esc(x.key)+'</pre>'
    +'<div class="small" style="margin-bottom:10px">Plan: <b>'+esc(x.plan)+'</b> &nbsp;&middot;&nbsp; Owner: <b>'+esc(x.owner)+'</b> &nbsp;&middot;&nbsp; Expires: <b>'+esc(x.expires_at)+'</b> &nbsp;&middot;&nbsp; Limit: <b>'+(x.daily_limit!=null?x.daily_limit:'Unlimited')+'</b>/day</div>'
    +'<button class="btn btn-p btn-sm" onclick="copyKey(\''+esc(x.key)+'\')">&#128203; Copy Key</button>'
    +'</div>';
  load();
}

async function revokeKey(k){
  if(!confirm('Revoke this key?\n\nIt will stop working immediately. You can delete it afterwards.'))return;
  var r=await api('/admin-panel/api/keys/'+encodeURIComponent(k)+'/revoke',{method:'POST'});
  if(r.ok)load();else alert((await r.json()).detail||'Error');
}

async function deleteKey(k){
  if(!confirm('Permanently DELETE this key from the database?\n\nThis CANNOT be undone.'))return;
  var r=await api('/admin-panel/api/keys/'+encodeURIComponent(k),{method:'DELETE'});
  if(r.ok)load();else alert((await r.json()).detail||'Error');
}

function copyKey(k){
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(k).then(function(){alert('Copied to clipboard!')}).catch(function(){prompt('Copy this key:',k)});
  } else { prompt('Copy this key:',k); }
}

async function imp(){
  var f=document.getElementById('csvfile').files[0];
  if(!f)return alert('Please select a CSV file first');
  var m=document.getElementById('imode').value;
  if(m==='replace'&&!confirm('WARNING: This will permanently replace ALL existing keys.\n\nAre you absolutely sure?'))return;
  var fd=new FormData();fd.append('file',f);
  var r=await api('/admin-panel/api/import?mode='+m,{method:'POST',body:fd});
  var x=await r.json();
  document.getElementById('csvmsg').textContent='Import complete: '+x.added+' added, '+x.skipped+' skipped, '+x.invalid+' invalid rows.';
  load();
}

function filterKeys(){
  var q=(document.getElementById('q').value||'').toLowerCase();
  var st=document.getElementById('fstatus').value;
  var pl=document.getElementById('fplan').value;
  document.querySelectorAll('#keys tbody tr').forEach(function(tr){
    var txt=tr.textContent.toLowerCase();
    var badge=tr.querySelector('.badge');
    var bst=badge?badge.textContent.trim().toLowerCase():'';
    var cells=tr.querySelectorAll('td');
    var plan_txt=cells[2]?cells[2].textContent.trim().toLowerCase():'';
    var ok=(!q||txt.includes(q))&&(st==='all'||bst===st)&&(pl==='all'||plan_txt===pl);
    tr.style.display=ok?'':'none';
  });
}

// logout defined in template
load();
'''

# ── Pinger ───────────────────────────────────────────────────────────────────
async def pinger():
    port=os.getenv("PORT","7860"); url=f"http://localhost:{port}/health"
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await asyncio.sleep(120)
            try: await client.get(url)
            except Exception: pass

@fastapi_app.on_event("startup")
async def startup_event(): asyncio.create_task(pinger())

# ── Gradio UI ───────────────────────────────────────────────────────────────
def format_result(row):
    lines=[]
    for field in SEARCH_FIELDS:
        val=row.get(field,"")
        if val: lines.append(f"**{field}:** {val}")
    cn=row.get("connected_numbers",[])
    if cn: lines.append("**connected:** "+", ".join(f"{c['field']}={c['value']}" for c in cn))
    return "\n\n".join(lines)

def search_ui(query,limit,search_type="phone"):
    if not query or not query.strip(): return "⚠️ Enter phone, aadhaar or name to search."
    q = query.strip()
    try:
        if search_type == "phone" or (q.isdigit() and len(q) >= 8 and search_type in ("phone","advanced","")):
            data = _unified_search(q, int(limit))
        elif search_type == "aadhar":
            data = _run_field_search("aadharNumber", q, "exact", int(limit))
            data = {"query": q, "searched_fields": ["aadharNumber"], "count": data["count"], "results": data["results"]}
        elif search_type == "other":
            data = _run_field_search("otherNumber", q, "exact", int(limit))
            data = {"query": q, "searched_fields": ["otherNumber"], "count": data["count"], "results": data["results"]}
        elif search_type == "name":
            data = _run_field_search("name", q, "contains", int(limit))
            data = {"query": q, "searched_fields": ["name"], "count": data["count"], "results": data["results"]}
        else:
            data = _unified_search(q, int(limit))
    except Exception as e:
        return f"❌ Error: {str(e)}"
    if not data["results"]:
        return f"🔍 **Query:** `{q}`\n\n❌ **No data found** for this search."
    return f"🔍 **Query:** `{q}` | **Found:** {data['count']} results\n\n---\n\n"+"\n\n---\n\n".join(f"### Result {i}\n{format_result(row)}" for i,row in enumerate(data["results"],1))

def build_ui():
    css = r'''
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    *{box-sizing:border-box}
    html{scroll-behavior:smooth;scroll-padding-top:86px}
    html,body{margin:0;background:#071b13!important;color:#eef8f2!important;font-family:Inter,system-ui,sans-serif!important}
    body{scrollbar-width:thin;scrollbar-color:#4aa678 #071b13}
    ::-webkit-scrollbar{width:7px}::-webkit-scrollbar-track{background:#071b13}::-webkit-scrollbar-thumb{background:#2d6a4f;border-radius:99px}
    .gradio-container{max-width:100%!important;padding:0!important;margin:0!important;background:#071b13!important}
    .main,.wrap,.contain{padding:0!important;max-width:100%!important}
    footer,footer*,.svelte-1ipelgc{display:none!important}
    .landing{min-height:100vh;background:#071b13;color:#eef8f2}
    .top-strip{height:38px;background:#06150f;border-bottom:1px solid rgba(92,191,145,.12);display:flex;align-items:center;justify-content:space-between;padding:0 52px;font-size:12px;color:#86b9a2;letter-spacing:.4px}
    .top-strip b{color:#55d49b}.top-strip .live{display:flex;align-items:center;gap:7px}.top-strip .dot{width:7px;height:7px;border-radius:50%;background:#39d98d;box-shadow:0 0 10px #39d98d}
    .site-nav{position:sticky;top:0;z-index:50;height:92px;background:rgba(8,30,22,.96);backdrop-filter:blur(18px);border-bottom:1px solid rgba(87,190,145,.15);display:flex;align-items:center;padding:0 42px;gap:28px}
    .brand{display:flex;align-items:center;gap:13px;min-width:285px}
    .brand-mark{width:56px;height:56px;border:2px solid #3bbf88;border-radius:15px;display:flex;align-items:center;justify-content:center;font-size:25px;color:#5ce0a8;background:rgba(48,174,120,.08);box-shadow:0 0 25px rgba(48,174,120,.08)}
    .brand-name{font-size:25px;font-weight:800;letter-spacing:-.8px}.brand-sub{font-size:12px;color:#46c58c;font-weight:700;letter-spacing:1.5px;margin-top:3px}
    .nav-links{display:flex;align-items:center;gap:3px;padding:6px;border:1px solid rgba(88,188,145,.12);background:#061710;border-radius:36px;flex:1;justify-content:center}
    .nav-links a{color:#9bc0b0;text-decoration:none;font-size:14px;font-weight:600;padding:12px 22px;border-radius:28px;transition:.2s;cursor:pointer}
    .nav-links a:hover,.nav-links a.active{color:#f4fff9;background:rgba(68,169,122,.12)}
    .request-nav{margin-left:auto;text-decoration:none;color:#f2fff8;font-weight:800;font-size:14px;padding:15px 24px;border-radius:30px;background:#35a875;box-shadow:0 8px 25px rgba(53,168,117,.22);white-space:nowrap}
    .request-nav:hover{background:#43bd86}
    .hero{min-height:650px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:80px 30px 92px;position:relative;overflow:hidden;background:radial-gradient(circle at 50% 44%,rgba(46,154,107,.18),transparent 35%),linear-gradient(180deg,#0c3022 0%,#0a2a1f 55%,#071b13 100%)}
    .hero:before{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(110,214,166,.18) 1px,transparent 1px);background-size:34px 34px;opacity:.18;mask-image:linear-gradient(to bottom,#000,transparent 92%)}
    .pill{position:relative;display:inline-flex;align-items:center;gap:9px;border:1px solid rgba(80,197,143,.27);background:rgba(59,176,123,.09);color:#65d9a5;border-radius:999px;padding:10px 20px;font-size:13px;font-weight:700;letter-spacing:.5px}
    .pill .dot{width:9px;height:9px;border-radius:50%;background:#45d596;box-shadow:0 0 10px #45d596}
    .hero h1{position:relative;font-size:clamp(43px,5.3vw,76px);line-height:1.03;letter-spacing:-3.5px;max-width:1250px;margin:28px auto 25px;font-weight:800}
    .hero h1 .accent{color:#50c992}.hero p{position:relative;max-width:920px;color:#a7c0b5;font-size:20px;line-height:1.7;margin:0 auto 38px}
    .hero-actions{position:relative;display:flex;gap:18px;justify-content:center;flex-wrap:wrap}
    .hero-btn{border:0;text-decoration:none;cursor:pointer;border-radius:11px;padding:17px 35px;font-size:16px;font-weight:800;display:inline-flex;align-items:center;gap:10px}
    .hero-btn.primary{background:#48a977;color:white;box-shadow:0 10px 30px rgba(56,169,116,.2)}
    .hero-btn.secondary{background:rgba(44,131,91,.18);border:1px solid rgba(74,180,129,.2);color:#d7eee3}
    .section{padding:96px 5.2%;background:#f5f7f2;color:#14261e}.section.dark{background:#09271c;color:#effaf5}
    .section-head{text-align:center;max-width:900px;margin:0 auto 52px}.section-head .pill{background:#e1eee8;border-color:#d4e6dd;color:#458e6d}.section-head h2{font-size:42px;letter-spacing:-1.5px;margin:16px 0 14px}.section-head p{font-size:18px;line-height:1.65;color:#65736c;margin:0}
    .about-grid{max-width:1180px;margin:auto;display:grid;grid-template-columns:1.05fr .95fr;gap:24px}
    .about-card,.feature-card{background:white;border:1px solid #dfe8e2;border-radius:24px;padding:30px;box-shadow:0 15px 45px rgba(17,46,34,.06)}
    .about-card h3,.feature-card h3{font-size:25px;margin:0 0 14px}.about-card p,.feature-card p{color:#64736c;line-height:1.75;font-size:15px}.about-list{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:22px}
    .about-item{padding:14px;border-radius:14px;background:#f0f6f2;color:#285843;font-weight:700;font-size:13px}.about-item span{display:block;color:#75837c;font-weight:500;font-size:12px;margin-top:4px}
    .architecture{max-width:1190px;margin:auto;background:white;border:1px solid #dfe8e2;border-radius:28px;padding:30px 38px;box-shadow:0 18px 50px rgba(17,46,34,.08);color:#14261e}
    .arch-tabs{display:flex;justify-content:center;gap:8px;margin-bottom:30px;flex-wrap:wrap}.arch-tab{border:1px solid #e1e8e3;background:#fff;padding:14px 25px;border-radius:10px;color:#5e6d66;font-weight:600;cursor:pointer}.arch-tab.active{background:#0e4d38;color:#fff;border-color:#0e4d38}
    .dash-title{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #edf1ee;padding:14px 0 25px;margin-bottom:22px}.dash-title h3{font-size:25px;margin:0}.stream{padding:8px 17px;background:#d9f7ea;color:#16845b;border-radius:999px;font-size:12px;font-weight:800}
    .metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.metric{border:1px solid #dce6df;border-radius:18px;padding:22px;background:#fbfcfa}.metric small{display:block;color:#738078;font-size:12px;font-weight:700;text-transform:uppercase}.metric strong{display:block;font-size:30px;margin:9px 0;color:#174b38}.metric span{color:#34a678;font-size:12px;font-weight:700}
    .chart{margin-top:22px;border:1px solid #dce6df;border-radius:18px;padding:25px;background:#f9fbf8}.bars{height:190px;display:flex;align-items:end;gap:15px;padding:20px 15px 0}.bar{flex:1;background:#4a9876;border-radius:7px 7px 0 0;min-width:16px}
    .request-wrap{max-width:1250px;margin:auto}.request-form{background:#09271c;border-radius:0;padding:15px 0 0}.request-form .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}.field{margin-bottom:22px}.field label{display:block;font-size:16px;font-weight:600;color:#dcebe4;margin-bottom:10px}.field input,.field select,.field textarea{width:100%;border:1px solid rgba(79,180,130,.18);background:#10392a;color:#dbece4;border-radius:13px;padding:17px 20px;font:inherit;font-size:15px;outline:none}.field textarea{min-height:145px;resize:vertical}.field input:focus,.field select:focus,.field textarea:focus{border-color:#46ad7d;box-shadow:0 0 0 3px rgba(70,173,125,.12)}.submit-request{width:100%;border:0;border-radius:14px;background:#4ba979;color:#fff;font-size:18px;font-weight:800;padding:19px;cursor:pointer;box-shadow:0 10px 30px rgba(52,157,108,.18)}.request-msg{display:none;margin-top:15px;padding:14px 18px;border-radius:11px;background:#123c2c;color:#9be0c0}
    .search-section{background:#f5f7f2;color:#14261e;padding:90px 5.2%}.search-card{max-width:1200px;margin:auto;background:white;border:1px solid #dfe8e2;border-radius:24px;padding:30px;box-shadow:0 15px 45px rgba(17,46,34,.06)}
    .search-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}.search-tab{padding:10px 16px;border-radius:9px;background:#f0f4f1;border:1px solid #dfe7e1;color:#54635c;font-weight:700;font-size:13px;cursor:pointer}.search-tab.active{background:#0e4d38;color:white;border-color:#0e4d38}
    .search-note{color:#6c7973;font-size:13px;margin-bottom:16px}.gr-box,.gr-form,.gr-padded,.gr-panel{background:transparent!important;border:none!important;box-shadow:none!important;padding:0!important}
    .gr-input-label,.gr-form>div>label{color:#52615a!important;font-size:13px!important}.search-section textarea,.search-section input[type=text],.search-section input[type=number]{background:#fff!important;border:1px solid #d8e3dc!important;color:#14261e!important;border-radius:12px!important}
    .search-section .gr-button-primary{background:#287d59!important;border:none!important;color:#fff!important;border-radius:11px!important;font-weight:800!important}
    .footer{background:#09271c;color:#8fb5a5;padding:72px 5.2% 28px}.footer-grid{max-width:1430px;margin:auto;display:grid;grid-template-columns:1.2fr 1fr 1fr 1fr;gap:60px}.footer h4{color:#f0faf5;font-size:17px;margin:0 0 24px}.footer p,.footer a{color:#89a99c;text-decoration:none;font-size:14px;line-height:1.9}.footer-brand{font-size:25px;font-weight:800;color:#fff}.footer-sub{color:#4bc68e;font-size:12px;font-weight:800;letter-spacing:1px;margin:3px 0 17px}.footer-bottom{max-width:1430px;margin:60px auto 0;padding-top:24px;border-top:1px solid rgba(105,181,145,.1);display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;font-size:13px}
    @media(max-width:1000px){.site-nav{padding:0 18px}.brand{min-width:auto}.nav-links{display:none}.request-nav{margin-left:auto}.about-grid{grid-template-columns:1fr}.metric-grid{grid-template-columns:1fr 1fr}.footer-grid{grid-template-columns:1fr 1fr}}
    @media(max-width:700px){.top-strip{padding:0 16px}.top-strip span:first-child{display:none}.site-nav{height:76px}.brand-mark{width:45px;height:45px}.brand-name{font-size:20px}.hero{min-height:590px;padding:65px 18px}.hero h1{font-size:42px;letter-spacing:-2px}.hero p{font-size:16px}.section,.search-section{padding:70px 18px}.section-head h2{font-size:32px}.about-list{grid-template-columns:1fr}.metric-grid{grid-template-columns:1fr}.request-form .form-grid{grid-template-columns:1fr;gap:0}.architecture{padding:20px}.dash-title{align-items:flex-start;gap:15px;flex-direction:column}.footer-grid{grid-template-columns:1fr}.footer-bottom{margin-top:40px}}
    '''
    custom_html = r'''
<div class="landing">
  <div class="top-strip"><span><b>API v3.4 LIVE</b> &nbsp;|&nbsp; Global Latency: <b>28ms</b></span><span class="live"><i class="dot"></i> All Systems Operational</span></div>
  <nav class="site-nav">
    <a class="brand" href="#home" style="text-decoration:none;color:inherit">
      <div class="brand-mark">⬡</div><div><div class="brand-name">PRIYANSHU <span style="color:#54c891">OSENT</span></div><div class="brand-sub">API MANAGEMENT ENGINE</div></div>
    </a>
    <div class="nav-links">
      <a href="#about">About Engine</a><a href="#services">Services</a><a href="#architecture">API Architecture</a><a href="#about">Client Voices</a><a href="#request">Contact</a>
    </div>
    <a class="request-nav" href="#request">🔑 REQUEST KEY</a>
  </nav>

  <section id="home" class="hero">
    <div class="pill"><i class="dot"></i> OSENT V3.4 PRODUCTION ENGINE LIVE</div>
    <h1>High-Performance <span class="accent">API Infrastructure</span> for Personal Brands</h1>
    <p>Power your single-page landing sites and high-velocity campaigns with enterprise-grade backend logic, zero-friction auth, dynamic database routing, and real-time lead telemetry.</p>
    <div class="hero-actions">
      <a class="hero-btn primary" href="#request">Get API Keys &amp; Docs →</a>
      <a class="hero-btn secondary" href="#services">&lt;/&gt; Explore Services</a>
    </div>
  </section>

  <section id="about" class="section">
    <div class="section-head"><div class="pill">ABOUT THE ENGINE</div><h2>Backend infrastructure built around your workflow</h2><p>Same clean structure and typography throughout the interface, with sections that connect directly to the working FastAPI backend.</p></div>
    <div class="about-grid">
      <div class="about-card"><h3>PRIYANSHU OSENT API</h3><p>High-performance backend solutions focused on API logic, database management, authentication, key management and request telemetry for personal brands and creator campaigns.</p><div class="about-list"><div class="about-item">Backend Logic<span>FastAPI request routing</span></div><div class="about-item">Key Management<span>Secure admin key vault</span></div><div class="about-item">Database Engine<span>DuckDB + remote parquet</span></div><div class="about-item">Telemetry<span>Usage &amp; request logging</span></div></div></div>
      <div class="about-card"><h3>Why this interface</h3><p>Every primary button is connected to a real action: navigation scrolls to its section, the request form reaches the backend, the search form runs the existing search engine, and key management opens the authenticated console.</p><div class="about-list"><div class="about-item">Live API<span>FastAPI endpoints</span></div><div class="about-item">Auth<span>HttpOnly admin session</span></div><div class="about-item">Docs<span>Interactive /docs route</span></div><div class="about-item">Admin<span>Generate, revoke, export</span></div></div></div>
    </div>
  </section>

  <section id="services" class="section">
    <div class="section-head"><div class="pill">SERVICES</div><h2>Everything connected from one interface</h2><p>Switch between the public-facing experience and the existing backend consoles without changing the overall visual language.</p></div>
    <div class="about-grid">
      <div class="feature-card"><h3>API Search Engine</h3><p>Phone, Aadhaar, other-number and name search using the existing backend search functions.</p><a class="hero-btn primary" style="margin-top:18px;padding:12px 20px" href="#search">Open Search</a></div>
      <div class="feature-card"><h3>API Key Console</h3><p>Create, manage, revoke, import and export keys from the protected admin dashboard.</p><a class="hero-btn primary" style="margin-top:18px;padding:12px 20px" href="/admin-panel#generate">Open Key Console →</a></div>
    </div>
  </section>

  <section id="architecture" class="section">
    <div class="section-head"><div class="pill">INTERACTIVE VISUAL SHOWCASE</div><h2>API Architecture &amp; Admin Consoles</h2><p>Explore the live backend flow, key management and request telemetry.</p></div>
    <div class="architecture">
      <div class="arch-tabs"><button class="arch-tab active" data-panel="telemetry">Admin Telemetry</button><button class="arch-tab" data-panel="pipeline">Data Pipeline Flow</button><button class="arch-tab" data-panel="vault">Key Vault Management</button></div>
      <div id="arch-telemetry">
        <div class="dash-title"><div><h3>Live Campaign Analytics Canvas</h3><span style="color:#78857f;font-size:13px">Real-time overview of incoming campaign traffic and API payload statuses.</span></div><span class="stream">Stream Active</span></div>
        <div class="metric-grid"><div class="metric"><small>Total Requests</small><strong>142,890</strong><span>↑ +14.2% this week</span></div><div class="metric"><small>Campaign Signups</small><strong>18,420</strong><span>12.8% Conversion</span></div><div class="metric"><small>Avg Latency</small><strong>29 ms</strong><span>Global Edge</span></div><div class="metric"><small>Security Vault Status</small><strong>100% SECURE</strong><span>Zero Leak Incidents</span></div></div>
        <div class="chart"><div style="display:flex;justify-content:space-between;font-weight:800;font-size:14px"><span>Endpoint Throughput (Last 24 Hours)</span><span style="color:#849189">Peak: 1,420 req/min</span></div><div class="bars"><i class="bar" style="height:38%"></i><i class="bar" style="height:52%"></i><i class="bar" style="height:32%"></i><i class="bar" style="height:66%"></i><i class="bar" style="height:82%"></i><i class="bar" style="height:58%"></i><i class="bar" style="height:72%"></i><i class="bar" style="height:45%"></i><i class="bar" style="height:88%"></i><i class="bar" style="height:68%"></i></div></div>
      </div>
      <div id="arch-pipeline" style="display:none;padding:20px 0"><h3>Data Pipeline Flow</h3><p style="color:#68766f;line-height:1.8">Client → API authentication → field routing → DuckDB remote index → duplicate capping → JSON response → request telemetry.</p></div>
      <div id="arch-vault" style="display:none;padding:20px 0"><h3>Key Vault Management</h3><p style="color:#68766f;line-height:1.8">Authenticated admin session → generate key → plan/limit → usage tracking → revoke/delete → CSV export/import.</p><a class="hero-btn primary" style="margin-top:15px;padding:12px 20px" href="/admin-panel#generate">Open Secure Key Console →</a></div>
    </div>
  </section>

  <section id="request" class="section dark">
    <div class="request-wrap">
      <div class="section-head" style="text-align:left;margin-left:0;margin-bottom:38px"><div class="pill">REQUEST ACCESS</div><h2>Request API Key &amp; Consultation</h2><p style="color:#9eb8ac">Fill out your project details below to send a real request to the backend. Key generation remains inside the authenticated Key Console.</p></div>
      <div class="request-form">
        <div class="form-grid">
          <div class="field"><label>Your Name *</label><input id="rq-name" placeholder="Priyanshu Sharma"></div>
          <div class="field"><label>Work / Brand Email *</label><input id="rq-email" type="email" placeholder="priyanshu@brand.com"></div>
          <div class="field"><label>Website / Landing Page Domain</label><input id="rq-website" placeholder="https://mycampaign.com"></div>
          <div class="field"><label>Primary Endpoint Requirement</label><select id="rq-requirement"><option>Single-Page Lead Engine</option><option>Search API Integration</option><option>Campaign Tracking</option><option>Custom Backend Logic</option></select></div>
        </div>
        <div class="field"><label>Campaign Architecture Details</label><textarea id="rq-details" placeholder="Describe your estimated traffic, landing page setup, or backend logic requirements..."></textarea></div>
        <button class="submit-request" onclick="submitRequest()">Submit Request &amp; Generate Key →</button>
        <div id="rq-msg" class="request-msg"></div>
      </div>
    </div>
  </section>

  <section id="search" class="search-section">
    <div class="section-head"><div class="pill">LIVE SEARCH INTERFACE</div><h2>Main API Interface</h2><p>The existing search backend stays connected. Select an option and run the search below.</p></div>
    <div class="search-card">
      <div class="search-tabs" id="searchTabs"><button class="search-tab active" data-type="phone">📞 Phone Number</button><button class="search-tab" data-type="aadhar">🪪 Aadhar Number</button><button class="search-tab" data-type="other">📱 Other Number</button><button class="search-tab" data-type="name">👤 Name</button><button class="search-tab" data-type="advanced">⚙️ Advanced</button></div>
      <div class="search-note">Choose the search option, enter a query, then use the Search button below.</div>
    </div>
  </section>


</div>
<script>
(function(){
  document.querySelectorAll('.arch-tab').forEach(function(tab){
    tab.addEventListener('click',function(){
      document.querySelectorAll('.arch-tab').forEach(function(t){t.classList.remove('active')});
      tab.classList.add('active');
      ['telemetry','pipeline','vault'].forEach(function(x){document.getElementById('arch-'+x).style.display='none'});
      document.getElementById('arch-'+tab.dataset.panel).style.display='block';
    });
  });
  document.querySelectorAll('.search-tab').forEach(function(tab){
    tab.addEventListener('click',function(){
      document.querySelectorAll('.search-tab').forEach(function(t){t.classList.remove('active')});
      tab.classList.add('active');
      var el=document.querySelector('#search-type-input textarea, #search-type-input input');
      if(el){el.value=tab.dataset.type;el.dispatchEvent(new Event('input',{bubbles:true}));}
      var q=document.querySelector('#query-input textarea, #query-input input');
      if(q){q.placeholder=tab.dataset.type==='name'?'Enter name...':(tab.dataset.type==='aadhar'?'Enter Aadhaar number...':'Enter number...');}
    });
  });
})();
async function submitRequest(){
  var msg=document.getElementById('rq-msg');
  msg.style.display='block'; msg.textContent='Sending request…';
  var payload={name:document.getElementById('rq-name').value,email:document.getElementById('rq-email').value,website:document.getElementById('rq-website').value,requirement:document.getElementById('rq-requirement').value,details:document.getElementById('rq-details').value};
  try{
    var r=await fetch('/api/key-request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var x=await r.json();
    if(!r.ok){msg.textContent=x.detail||'Unable to submit request.';return}
    msg.textContent='✓ Request #'+x.request_id+' received. Open the Key Console to generate the key after admin review.';
    document.getElementById('rq-details').value='';
  }catch(e){msg.textContent='Network error. Please try again.'}
}
</script>
'''
    footer_html = r'''  <footer class="footer">
    <div class="footer-grid">
      <div><div class="footer-brand">PRIYANSHU</div><div class="footer-sub">OSENT API</div><p>PRIYANSHU OSENT API delivers high-performance, secure backend solutions focused on API logic, database management, auth, and telemetry for personal brands and creators.</p></div>
      <div><h4>ARCHITECTURE</h4><p>Backend Logic</p><p>Key Management Vault</p><p>Campaign Tracking</p><p>Database Engine</p><p>API Console Showcase</p></div>
      <div><h4>RESOURCES</h4><a href="/docs">API Documentation</a><br><a href="/docs">SDK &amp; Curl Samples</a><br><a href="#architecture">System Uptime Monitor</a><br><a href="#about">Privacy &amp; Security Terms</a><br><a href="#request">Developer Helpdesk</a></div>
      <div><h4>SYSTEM DESK</h4><p>✉ api@priyanshu-osent.com</p><p>☎ +1 (800) 555-OSENT</p><p>◷ 24/7 Global Edge Support</p><div class="stream" style="display:block;margin-top:22px">● &nbsp; All Clusters Operational</div></div>
    </div>
    <div class="footer-bottom"><span>© 2026 PRIYANSHU OSENT API. All rights reserved. Built for single-page creators &amp; brands.</span><span>Privacy Policy &nbsp;&nbsp;&nbsp; Terms of Endpoint Access &nbsp;&nbsp;&nbsp; Security Whitepaper</span></div>
  </footer>
'''
    with gr.Blocks(title="PRIYANSHU OSENT API", theme=gr.themes.Base(), css=css) as demo:
        gr.HTML(custom_html)
        search_type = gr.Textbox(value="phone", elem_id="search-type-input", visible=False)
        with gr.Group(elem_id="search-controls-group"):
            with gr.Row():
                query_input = gr.Textbox(
                    elem_id="query-input",
                    label="Search Query",
                    placeholder="Enter 10 digit phone number...",
                    lines=1,
                    scale=4,
                )
                limit_slider = gr.Slider(
                    minimum=1, maximum=100, value=50, step=1,
                    label="Max Results",
                    scale=2,
                )
            search_btn = gr.Button("🔍 Search Now →", variant="primary", size="lg")
        output = gr.Markdown(label="", elem_classes="results-area")
        gr.HTML(footer_html)
        search_btn.click(fn=search_ui, inputs=[query_input, limit_slider, search_type], outputs=output)
        query_input.submit(fn=search_ui, inputs=[query_input, limit_slider, search_type], outputs=output)
    return demo

demo = build_ui()
app = gr.mount_gradio_app(fastapi_app, demo, path="/")
