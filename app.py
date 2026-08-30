import os
import re
import secrets
import sqlite3
import time
from urllib.parse import quote

import requests
from flask import Flask, jsonify, redirect, render_template, request

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "xyvera.db")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://xrahbkohfbtncasqncas.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_cSUARkOBMBka6JZ3QbT0RQ_s8K4ASkm")


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY,title TEXT NOT NULL,mode TEXT NOT NULL,duration INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,closed INTEGER NOT NULL DEFAULT 0,owner_id TEXT,slug TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS options (id INTEGER PRIMARY KEY AUTOINCREMENT,poll_id TEXT NOT NULL,text TEXT NOT NULL,votes INTEGER NOT NULL DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS votes (id INTEGER PRIMARY KEY AUTOINCREMENT,poll_id TEXT NOT NULL,option_id INTEGER NOT NULL,voter TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(poll_id,voter))")
        c.execute("CREATE TABLE IF NOT EXISTS timers (id TEXT PRIMARY KEY,duration INTEGER NOT NULL,remaining INTEGER NOT NULL,running INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL,owner_id TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT NOT NULL,user_id TEXT,target_id TEXT,created_at INTEGER NOT NULL)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS polls_owner_slug_idx ON polls(owner_id,slug) WHERE owner_id IS NOT NULL AND slug IS NOT NULL")
        c.commit()


def token():
    return secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:9]


def slugify(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9а-яё_-]+", "-", value, flags=re.I)
    return re.sub(r"-+", "-", value).strip("-")[:70]


def auth_user():
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    access = auth.split(" ", 1)[1].strip()
    try:
        r = requests.get(f"{SUPABASE_URL}/auth/v1/user", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {access}"}, timeout=10)
        if r.ok:
            return r.json()
    except requests.RequestException:
        pass
    return None


def require_user():
    user = auth_user()
    if not user:
        return None, (jsonify({"error": "Требуется вход в аккаунт."}), 401)
    return user, None


def supabase_profile(user_id, access_token=None):
    headers = {"apikey": SUPABASE_KEY}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/profiles", params={"select":"user_id,username,display_name,bio,avatar_url,vip", "user_id":f"eq.{user_id}"}, headers=headers, timeout=10)
        if r.ok:
            rows = r.json()
            return rows[0] if rows else None
    except requests.RequestException:
        pass
    return None


def is_vip(user):
    if not user:
        return False
    access = request.headers.get("Authorization", "").split(" ", 1)[1] if " " in request.headers.get("Authorization", "") else None
    profile = supabase_profile(user.get("id"), access)
    return bool(profile and profile.get("vip"))


def poll_json(poll_id):
    with db() as c:
        poll = c.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
        if not poll:
            return None
        opts = c.execute("SELECT id,text,votes FROM options WHERE poll_id=? ORDER BY id", (poll_id,)).fetchall()
    remaining = None
    if poll["mode"] == "timed":
        remaining = max(0, poll["created_at"] + poll["duration"] - int(time.time()))
    closed = bool(poll["closed"] or (poll["mode"] == "timed" and remaining == 0))
    if closed and not poll["closed"]:
        with db() as c:
            c.execute("UPDATE polls SET closed=1 WHERE id=?", (poll_id,)); c.commit()
    return {"id":poll["id"],"title":poll["title"],"mode":poll["mode"],"duration":poll["duration"],"created_at":poll["created_at"],"closed":closed,"remaining":remaining,"total":sum(x["votes"] for x in opts),"owner_id":poll["owner_id"],"slug":poll["slug"],"options":[dict(x) for x in opts]}


def timer_json(timer_id):
    with db() as c:
        row = c.execute("SELECT * FROM timers WHERE id=?", (timer_id,)).fetchone()
    if not row: return None
    remaining = row["remaining"]
    running = bool(row["running"])
    if running:
        remaining = max(0, remaining - (int(time.time()) - row["updated_at"]))
        if remaining == 0:
            running = False
    return {"id":timer_id,"duration":row["duration"],"remaining":remaining,"running":running,"owner_id":row["owner_id"]}


def can_control(owner_id, user):
    return bool(user and (owner_id == user.get("id") or is_vip(user)))


@app.get("/")
def home(): return render_template("index.html")
@app.get("/create")
def create_page(): return render_template("create.html")
@app.get("/login")
def login_page(): return render_template("login.html")
@app.get("/register")
def register_page(): return render_template("register.html")
@app.get("/profile")
def profile_page(): return render_template("profile.html")
@app.get("/u/<username>")
def public_profile(username): return render_template("public_profile.html", username=username)

@app.get("/<username>/<slug>")
def named_poll(username, slug):
    with db() as c:
        row = c.execute("SELECT p.id FROM polls p JOIN (SELECT user_id FROM temp_profile_lookup) x ON x.user_id=p.owner_id WHERE p.slug=?", (slug,)).fetchone() if False else None
    # Username is resolved through Supabase, then the local poll is found by owner id.
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/profiles", params={"select":"user_id", "username":f"eq.{username}"}, headers={"apikey":SUPABASE_KEY}, timeout=10)
        rows = r.json() if r.ok else []
    except requests.RequestException:
        rows = []
    if not rows: return "Профиль не найден", 404
    with db() as c:
        row = c.execute("SELECT id FROM polls WHERE owner_id=? AND slug=?", (rows[0]["user_id"], slug)).fetchone()
    if not row: return "Опрос не найден", 404
    return render_template("vote.html", poll_id=row["id"])

@app.get("/p/<poll_id>")
def vote_page(poll_id):
    if not poll_json(poll_id): return "Опрос не найден", 404
    return render_template("vote.html", poll_id=poll_id)
@app.get("/p/<poll_id>/overlay")
def overlay_page(poll_id):
    if not poll_json(poll_id): return "Опрос не найден", 404
    return render_template("overlay.html", poll_id=poll_id)
@app.get("/p/<poll_id>/control")
def control_page(poll_id):
    if not poll_json(poll_id): return "Опрос не найден", 404
    return render_template("control.html", poll_id=poll_id)

@app.post("/api/polls")
def create_poll():
    user, err = require_user()
    if err: return err
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    mode = str(data.get("mode", "poll")).lower().strip()
    duration = int(data.get("duration", 0) or 0)
    options = [str(x).strip() for x in data.get("options", []) if str(x).strip()]
    if not title: return jsonify({"error":"Введите вопрос."}),400
    if mode not in {"poll","timed","vote"}: return jsonify({"error":"Неизвестный режим."}),400
    if len(options) < 2 or len(options) > 10: return jsonify({"error":"Нужно от 2 до 10 вариантов."}),400
    if mode == "timed" and not 5 <= duration <= 86400: return jsonify({"error":"Таймер: от 5 секунд до 24 часов."}),400
    profile = supabase_profile(user["id"])
    username = profile.get("username") if profile else None
    if not username: return jsonify({"error":"Сначала укажите username в профиле."}),400
    requested = slugify(data.get("slug") or title) or token()
    slug = requested
    with db() as c:
        i=2
        while c.execute("SELECT 1 FROM polls WHERE owner_id=? AND slug=?", (user["id"],slug)).fetchone():
            slug = f"{requested}-{i}"; i += 1
        pid = token(); now=int(time.time())
        c.execute("INSERT INTO polls(id,title,mode,duration,created_at,closed,owner_id,slug) VALUES(?,?,?,?,?,?,?,?)", (pid,title,mode,duration if mode=="timed" else 0,now,0,user["id"],slug))
        c.executemany("INSERT INTO options(poll_id,text) VALUES(?,?)", [(pid,x) for x in options])
        c.execute("INSERT INTO events(type,user_id,target_id,created_at) VALUES(?,?,?,?)", ("poll_created",user["id"],pid,now)); c.commit()
    return jsonify({"id":pid,"slug":slug,"url":f"/{quote(username)}/{quote(slug)}","legacy_url":f"/p/{pid}","overlay":f"/p/{pid}/overlay","control":f"/p/{pid}/control"}),201

@app.get("/api/poll/<poll_id>")
def get_poll(poll_id):
    data=poll_json(poll_id)
    return (jsonify(data),200) if data else (jsonify({"error":"Опрос не найден"}),404)

@app.post("/api/poll/<poll_id>/vote")
def vote(poll_id):
    data=request.get_json(silent=True) or {}; voter=str(data.get("voter","")).strip()
    try: option_id=int(data.get("option_id"))
    except (TypeError,ValueError): return jsonify({"error":"Неверный вариант"}),400
    poll=poll_json(poll_id)
    if not poll: return jsonify({"error":"Опрос не найден"}),404
    if poll["closed"]: return jsonify({"error":"Опрос уже завершён"}),409
    if not voter: return jsonify({"error":"Не указан голосующий"}),400
    with db() as c:
        opt=c.execute("SELECT id FROM options WHERE id=? AND poll_id=?",(option_id,poll_id)).fetchone()
        if not opt: return jsonify({"error":"Вариант не найден"}),404
        try:
            c.execute("INSERT INTO votes(poll_id,option_id,voter,created_at) VALUES(?,?,?,?)",(poll_id,option_id,voter,int(time.time())))
        except sqlite3.IntegrityError: return jsonify({"error":"Вы уже голосовали."}),409
        c.execute("UPDATE options SET votes=votes+1 WHERE id=?",(option_id,)); c.commit()
    return jsonify(poll_json(poll_id))

@app.post("/api/poll/<poll_id>/close")
def close_poll(poll_id):
    poll=poll_json(poll_id)
    if not poll: return jsonify({"error":"Опрос не найден"}),404
    user,err=require_user()
    if err:return err
    if not can_control(poll["owner_id"],user): return jsonify({"error":"Недостаточно прав."}),403
    with db() as c:c.execute("UPDATE polls SET closed=1 WHERE id=?",(poll_id,));c.commit()
    return jsonify(poll_json(poll_id))

@app.get("/timer/new")
def new_timer():
    user=auth_user()
    tid=token(); now=int(time.time())
    with db() as c:c.execute("INSERT INTO timers VALUES(?,?,?,?,?,?)",(tid,300,300,0,now,user.get("id") if user else None));c.commit()
    return redirect(f"/timer/{tid}")
@app.get("/timer/<timer_id>")
def timer_page(timer_id):
    if not timer_json(timer_id):return "Таймер не найден",404
    return render_template("timer.html",timer_id=timer_id)
@app.get("/timer/<timer_id>/overlay")
def timer_overlay(timer_id):
    if not timer_json(timer_id):return "Таймер не найден",404
    return render_template("timer_overlay.html",timer_id=timer_id)
@app.get("/api/timer/<timer_id>")
def get_timer(timer_id):
    x=timer_json(timer_id);return (jsonify(x),200) if x else (jsonify({"error":"Таймер не найден"}),404)
@app.post("/api/timer/<timer_id>/<action>")
def timer_action(timer_id,action):
    timer=timer_json(timer_id)
    if not timer:return jsonify({"error":"Таймер не найден"}),404
    user,err=require_user()
    if err:return err
    if not can_control(timer["owner_id"],user):return jsonify({"error":"Недостаточно прав."}),403
    remaining=timer["remaining"];running=timer["running"]
    if action=="start":running=remaining>0
    elif action=="pause":running=False
    elif action=="reset":remaining=timer["duration"];running=False
    elif action=="add":
        try:remaining+=max(1,min(86400,int(request.args.get("seconds",0))))
        except ValueError:return jsonify({"error":"Неверные секунды"}),400
    else:return jsonify({"error":"Неизвестное действие"}),400
    with db() as c:c.execute("UPDATE timers SET remaining=?,running=?,updated_at=? WHERE id=?",(remaining,int(running),int(time.time()),timer_id));c.commit()
    return jsonify(timer_json(timer_id))

@app.get("/api/me")
def me():
    user,err=require_user()
    if err:return err
    profile=supabase_profile(user["id"])
    return jsonify({"id":user["id"],"email":user.get("email"),"profile":profile,"vip":bool(profile and profile.get("vip"))})

@app.post("/api/reports")
def report():
    user,err=require_user()
    if err:return err
    data=request.get_json(silent=True) or {}; reason=str(data.get("reason","")).strip()
    if not reason:return jsonify({"error":"Укажите причину."}),400
    headers={"apikey":SUPABASE_KEY,"Authorization":request.headers.get("Authorization")}
    payload={"reporter_id":user["id"],"target_user_id":data.get("target_user_id"),"target_url":data.get("target_url"),"reason":reason}
    r=requests.post(f"{SUPABASE_URL}/rest/v1/reports",json=payload,headers={**headers,"Content-Type":"application/json","Prefer":"return=minimal"},timeout=10)
    return jsonify({"ok":True}) if r.ok else jsonify({"error":"Не удалось отправить жалобу."}),502

@app.get("/api/admin/reports")
def admin_reports():
    user,err=require_user()
    if err:return err
    if not is_vip(user):return jsonify({"error":"VIP only"}),403
    access=request.headers.get("Authorization")
    r=requests.get(f"{SUPABASE_URL}/rest/v1/reports",params={"select":"*","order":"created_at.desc"},headers={"apikey":SUPABASE_KEY,"Authorization":access},timeout=10)
    return (jsonify(r.json()),200) if r.ok else (jsonify({"error":"Supabase error"}),502)

@app.post("/api/admin/ban")
def admin_ban():
    user,err=require_user()
    if err:return err
    if not is_vip(user):return jsonify({"error":"VIP only"}),403
    data=request.get_json(silent=True) or {}; target=data.get("user_id")
    if not target:return jsonify({"error":"user_id обязателен"}),400
    payload={"user_id":target,"banned_by":user["id"],"reason":str(data.get("reason","")).strip(),"expires_at":data.get("expires_at")}
    r=requests.post(f"{SUPABASE_URL}/rest/v1/bans",json=payload,headers={"apikey":SUPABASE_KEY,"Authorization":request.headers.get("Authorization"),"Content-Type":"application/json","Prefer":"return=minimal"},timeout=10)
    return jsonify({"ok":True}) if r.ok else jsonify({"error":"Не удалось заблокировать пользователя."}),502

@app.get("/health")
def health():return jsonify({"status":"ok","service":"xyvera"})

init_db()
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
