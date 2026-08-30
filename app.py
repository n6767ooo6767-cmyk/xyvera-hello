import os
import sqlite3
import secrets
import time
from flask import Flask, jsonify, redirect, render_template, request

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "xyvera.db")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY,title TEXT NOT NULL,mode TEXT NOT NULL,duration INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,closed INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS options (id INTEGER PRIMARY KEY AUTOINCREMENT,poll_id TEXT NOT NULL,text TEXT NOT NULL,votes INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS timers (id TEXT PRIMARY KEY,duration INTEGER NOT NULL,remaining INTEGER NOT NULL,running INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL)")
        conn.commit()


def poll_json(poll_id):
    with db() as conn:
        poll = conn.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
        if not poll: return None
        options = conn.execute("SELECT id,text,votes FROM options WHERE poll_id=? ORDER BY id", (poll_id,)).fetchall()
    total = sum(x["votes"] for x in options)
    remaining = max(0, poll["created_at"] + poll["duration"] - int(time.time())) if poll["duration"] else None
    closed = bool(poll["closed"])
    if poll["mode"] == "timed" and remaining == 0 and not closed:
        with db() as conn:
            conn.execute("UPDATE polls SET closed=1 WHERE id=?", (poll_id,)); conn.commit()
        closed = True
    return {"id":poll["id"],"title":poll["title"],"mode":poll["mode"],"duration":poll["duration"],"created_at":poll["created_at"],"closed":closed,"remaining":remaining,"total":total,"options":[dict(x) for x in options]}


def timer_json(timer_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM timers WHERE id=?", (timer_id,)).fetchone()
        if not row: return None
    remaining = row["remaining"]
    running = bool(row["running"])
    if running:
        remaining = max(0, remaining - (int(time.time()) - row["updated_at"]))
        if remaining == 0:
            running = False
            with db() as conn:
                conn.execute("UPDATE timers SET remaining=0,running=0,updated_at=? WHERE id=?", (int(time.time()), timer_id)); conn.commit()
    return {"id":timer_id,"duration":row["duration"],"remaining":remaining,"running":running}


@app.get("/")
def home(): return render_template("index.html")

@app.get("/create")
def create_page(): return render_template("create.html")

@app.get("/p/<poll_id>")
def vote_page(poll_id):
    if not poll_json(poll_id): return "Опрос не найден",404
    return render_template("vote.html",poll_id=poll_id)

@app.get("/p/<poll_id>/overlay")
def overlay_page(poll_id):
    if not poll_json(poll_id): return "Опрос не найден",404
    return render_template("overlay.html",poll_id=poll_id)

@app.get("/p/<poll_id>/control")
def control_page(poll_id):
    if not poll_json(poll_id): return "Опрос не найден",404
    return render_template("control.html",poll_id=poll_id)

@app.get("/timer/new")
def new_timer():
    timer_id=secrets.token_urlsafe(6).replace("-","").replace("_","")[:8]
    with db() as conn:
        conn.execute("INSERT INTO timers(id,duration,remaining,running,updated_at) VALUES(?,?,?,?,?)",(timer_id,300,300,0,int(time.time()))); conn.commit()
    return redirect(f"/timer/{timer_id}")

@app.get("/timer/<timer_id>")
def timer_page(timer_id):
    if not timer_json(timer_id): return "Таймер не найден",404
    return render_template("timer.html",timer_id=timer_id)

@app.get("/timer/<timer_id>/overlay")
def timer_overlay(timer_id):
    if not timer_json(timer_id): return "Таймер не найден",404
    return render_template("timer_overlay.html",timer_id=timer_id)

@app.get("/api/timer/<timer_id>")
def get_timer(timer_id):
    data=timer_json(timer_id)
    return (jsonify(data),200) if data else (jsonify({"error":"Таймер не найден"}),404)

@app.post("/api/timer/<timer_id>/<action>")
def timer_action(timer_id,action):
    timer=timer_json(timer_id)
    if not timer: return jsonify({"error":"Таймер не найден"}),404
    now=int(time.time()); remaining=timer["remaining"]; running=timer["running"]
    if action=="start": running=remaining>0
    elif action=="pause": running=False
    elif action=="reset": remaining=timer["duration"]; running=False
    elif action=="add":
        try: remaining += max(1,int(request.args.get("seconds",0)))
        except ValueError: return jsonify({"error":"Неверное количество секунд"}),400
    else: return jsonify({"error":"Неизвестное действие"}),400
    with db() as conn:
        conn.execute("UPDATE timers SET remaining=?,running=?,updated_at=? WHERE id=?",(remaining,int(running),now,timer_id)); conn.commit()
    return jsonify(timer_json(timer_id))

@app.post("/api/polls")
def create_poll():
    data=request.get_json(silent=True) or {}; title=str(data.get("title","")).strip(); mode=str(data.get("mode","poll")).strip().lower(); duration=int(data.get("duration",0) or 0)
    options=[str(x).strip() for x in data.get("options",[]) if str(x).strip()]
    if not title:return jsonify({"error":"Введите вопрос."}),400
    if mode not in {"poll","timed","vote"}:return jsonify({"error":"Неизвестный режим."}),400
    if mode=="timed" and duration<5:return jsonify({"error":"Таймер должен быть не меньше 5 секунд."}),400
    if len(options)<2 or len(options)>10:return jsonify({"error":"Нужно от 2 до 10 вариантов."}),400
    poll_id=secrets.token_urlsafe(6).replace("-","").replace("_","")[:8]; now=int(time.time())
    with db() as conn:
        conn.execute("INSERT INTO polls VALUES(?,?,?,?,?,0)",(poll_id,title,mode,duration if mode=="timed" else 0,now))
        conn.executemany("INSERT INTO options(poll_id,text) VALUES(?,?)",[(poll_id,x) for x in options]); conn.commit()
    return jsonify({"id":poll_id,"url":f"/p/{poll_id}","overlay":f"/p/{poll_id}/overlay","control":f"/p/{poll_id}/control"}),201

@app.get("/api/poll/<poll_id>")
def get_poll(poll_id):
    data=poll_json(poll_id); return (jsonify(data),200) if data else (jsonify({"error":"Опрос не найден"}),404)

@app.post("/api/poll/<poll_id>/vote")
def vote(poll_id):
    data=request.get_json(silent=True) or {}; voter=str(data.get("voter","")).strip()
    try: option_id=int(data.get("option_id"))
    except (TypeError,ValueError): return jsonify({"error":"Неверный вариант"}),400
    poll=poll_json(poll_id)
    if not poll:return jsonify({"error":"Опрос не найден"}),404
    if poll["closed"]:return jsonify({"error":"Опрос уже завершён"}),409
    if not voter:return jsonify({"error":"Не указан идентификатор голосующего"}),400
    with db() as conn:
        option=conn.execute("SELECT id FROM options WHERE id=? AND poll_id=?",(option_id,poll_id)).fetchone()
        if not option:return jsonify({"error":"Вариант не найден"}),404
        conn.execute("UPDATE options SET votes=votes+1 WHERE id=?",(option_id,)); conn.commit()
    return jsonify(poll_json(poll_id))

@app.post("/api/poll/<poll_id>/close")
def close_poll(poll_id):
    if not poll_json(poll_id):return jsonify({"error":"Опрос не найден"}),404
    with db() as conn: conn.execute("UPDATE polls SET closed=1 WHERE id=?",(poll_id,)); conn.commit()
    return jsonify(poll_json(poll_id))

@app.get("/health")
def health(): return jsonify({"status":"ok","service":"xyvera"})

init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
