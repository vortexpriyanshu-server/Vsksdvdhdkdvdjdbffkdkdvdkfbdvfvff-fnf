import os, secrets, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

APP_NAME='PRIYANSHU API CLOUD'
LOGO='VORTEX'
TAGLINE='POWERFUL APIs FOR DEVELOPERS AND TRUSTED'
DEVELOPER='@Vortex_priyanshu'
CHANNEL='https://t.me/+904FzUCPszJjZTU1'
ADMIN_USER='@Vortex_priyanshu'
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','CHANGE_ME')
SECRET_KEY=os.getenv('SECRET_KEY',secrets.token_urlsafe(32))
DATA=Path('data.json')
app=FastAPI(title=APP_NAME)
app.add_middleware(SessionMiddleware,secret_key=SECRET_KEY,http_only=True,same_site='lax')

def load():
    import json
    if DATA.exists(): return json.loads(DATA.read_text())
    d={'apis':[{'id':'demo','name':'Developer API','category':'Tools','price':0,'description':'A lightweight example API product.'}], 'keys':[], 'firebases':[], 'activity':[]}
    save(d); return d

def save(d):
    import json
    DATA.write_text(json.dumps(d,indent=2))

def esc(x):
    import html
    return html.escape(str(x))

def page(title,body):
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · {LOGO}</title><link rel="stylesheet" href="/static/app.css"></head><body><nav><a class="brand" href="/">{LOGO}<span>API CLOUD</span></a><div class="nav"><a href="/">Home</a><a href="/marketplace">APIs</a><a href="/docs">Docs</a><a href="/admin">Admin</a></div></nav><main>{body}</main><footer>Developed by <a href="https://t.me/Vortex_priyanshu">{DEVELOPER}</a> · <a href="{CHANNEL}">Channel</a></footer></body></html>''')

@app.get('/',response_class=HTMLResponse)
def home():
    d=load(); cards=''.join(f'<article class="card"><span class="pill">{esc(a["category"])}</span><h3>{esc(a["name"])}</h3><p>{esc(a["description"])}</p><strong>{"FREE" if not a["price"] else "₹"+str(a["price"])}</strong><a class="btn" href="/api/{esc(a["id"])}">Explore</a></article>' for a in d['apis'])
    return page(APP_NAME,f'''<section class="hero"><div class="eyebrow">VORTEX · API PLATFORM</div><h1>{TAGLINE}</h1><p>Fast, clean and developer-friendly APIs with simple documentation, key management and transparent access.</p><div><a class="btn" href="/marketplace">Explore APIs</a><a class="btn ghost" href="/docs">Read Docs</a></div><div class="orb"><b>V</b><span>PRIYANSHU</span></div></section><section><div class="sectionhead"><h2>Featured APIs</h2><a href="/marketplace">View all →</a></div><div class="grid">{cards}</div></section>''')

@app.get('/marketplace',response_class=HTMLResponse)
def marketplace():
    d=load(); cards=''.join(f'<article class="card"><span class="pill">{esc(a["category"])}</span><h3>{esc(a["name"])}</h3><p>{esc(a["description"])}</p><strong>{"FREE" if not a["price"] else "₹"+str(a["price"])}</strong><a class="btn" href="/api/{esc(a["id"])}">Details</a></article>' for a in d['apis'])
    return page('Marketplace', '<section><div class="eyebrow">MARKETPLACE</div><h1>APIs built for builders.</h1><p>Search and discover lightweight API products.</p><input class="search" placeholder="Search APIs..." oninput="filterCards(this.value)"><div class="grid" id="cards">' + cards + '</div></section><script>function filterCards(q){document.querySelectorAll("#cards .card").forEach(function(c){c.style.display=c.innerText.toLowerCase().includes(q.toLowerCase())?"":"none"})}</script>')

@app.get('/api/{api_id}',response_class=HTMLResponse)
def api_detail(api_id):
    a=next((x for x in load()['apis'] if x['id']==api_id),None)
    if not a: return page('Not found','<section><h1>API not found</h1></section>')
    return page(a['name'],f'<section class="detail"><div><span class="pill">{esc(a["category"])}</span><h1>{esc(a["name"])}</h1><p>{esc(a["description"])}</p><h3>Access</h3><p>Use your API key as <code>?api_key=YOUR_KEY</code>. Keys have configurable expiry.</p><a class="btn" href="/docs">Open Docs</a></div><div class="code"><pre>GET /v1/example?api_key=YOUR_KEY\n\n{{\n  "status": "success",\n  "message": "Request completed",\n  "data": {{}},\n  "developer": "{DEVELOPER}",\n  "channel": "{CHANNEL}",\n  "key_duration": "30 days",\n  "created_at": "2026-09-15 22:30:00",\n  "expires_at": "2026-10-15 22:30:00",\n  "days_remaining": 30\n}}</pre></div></section>')

@app.get('/docs',response_class=HTMLResponse)
def docs():
    return page('Docs','''<section><div class="eyebrow">DOCUMENTATION</div><h1>Simple. Clear. Ready to test.</h1><div class="detail"><div class="card"><h3>Authentication</h3><p>Pass your key as a URL parameter:</p><pre>?api_key=YOUR_KEY</pre><p>For production, avoid exposing keys in shared URLs and rotate expired keys.</p></div><div class="card"><h3>Response</h3><pre>{"status":"success","message":"Request completed","data":{},"developer":"@Vortex_priyanshu","channel":"https://t.me/+904FzUCPszJjZTU1"}</pre><button class="btn" onclick="alert('Try API demo: connect a real product endpoint in Admin.')">Try API</button></div></div></section>''')

def admin_guard(request): return bool(request.session.get('admin'))
@app.get('/admin/login',response_class=HTMLResponse)
def login(): return page('Admin Login','<section class="login"><div class="card"><div class="eyebrow">VORTEX ADMIN</div><h1>Control Center</h1><form method="post"><input name="username" placeholder="Username" required><input name="password" type="password" placeholder="Password" required><button class="btn">Sign in</button></form></div></section>')
@app.post('/admin/login')
def do_login(request:Request,username:str=Form(...),password:str=Form(...)):
    if username==ADMIN_USER and password==ADMIN_PASSWORD:
        request.session['admin']=True; return RedirectResponse('/admin',303)
    return RedirectResponse('/admin/login',303)
@app.get('/admin',response_class=HTMLResponse)
def admin(request:Request):
    if not admin_guard(request): return RedirectResponse('/admin/login',303)
    d=load(); keys=len(d['keys']); fbs=len(d['firebases']); apis=len(d['apis'])
    fb=''.join(f'<tr><td>{esc(f["label"])}</td><td>{esc(f["url"])}</td></tr>' for f in d['firebases']) or '<tr><td colspan="2">No Firebase configs yet.</td></tr>'
    return page('Admin',f'''<section><div class="eyebrow">ADMIN DASHBOARD</div><h1>VORTEX Control Center</h1><div class="stats"><div><b>{apis}</b><span>APIs</span></div><div><b>{keys}</b><span>Keys</span></div><div><b>{fbs}</b><span>Firebase</span></div></div><div class="admin-grid"><div class="card"><h2>Add API</h2><form method="post" action="/admin/api"><input name="name" placeholder="API name" required><input name="category" placeholder="Category" required><input name="price" type="number" min="0" placeholder="Price (0 = free)" required><input name="description" placeholder="Description" required><button class="btn">Add API</button></form></div><div class="card"><h2>Firebase</h2><p>Add Firebase database/config entries here for your legitimate backend integrations.</p><form method="post" action="/admin/firebase"><input name="label" placeholder="Firebase label" required><input name="url" placeholder="Firebase URL" required><button class="btn">Add Firebase</button></form></div></div><div class="card"><h2>Firebase Configurations</h2><table><tr><th>Label</th><th>URL</th></tr>{fb}</table></div><p><a class="btn ghost" href="/admin/logout">Logout</a></p></section>''')
@app.post('/admin/api')
def add_api(request:Request,name:str=Form(...),category:str=Form(...),price:int=Form(...),description:str=Form(...)):
    if not admin_guard(request): return RedirectResponse('/admin/login',303)
    d=load(); d['apis'].append({'id':secrets.token_hex(4),'name':name,'category':category,'price':max(0,price),'description':description}); save(d); return RedirectResponse('/admin',303)
@app.post('/admin/firebase')
def add_fb(request:Request,label:str=Form(...),url:str=Form(...)):
    if not admin_guard(request): return RedirectResponse('/admin/login',303)
    d=load(); d['firebases'].append({'label':label,'url':url}); save(d); return RedirectResponse('/admin',303)
@app.get('/admin/logout')
def logout(request:Request): request.session.clear(); return RedirectResponse('/admin/login',303)

@app.get('/api/health')
def health(): return {'status':'success','message':'PRIYANSHU API CLOUD online','data':{},'developer':DEVELOPER,'channel':CHANNEL}
