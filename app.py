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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                mode TEXT NOT NULL,
                duration INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                closed INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id TEXT NOT NULL,
                text TEXT NOT NULL,
                votes INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


def poll_json(poll_id):
    with db() as conn:
        poll = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
        if not poll:
            return None
        options = conn.execute(
            "SELECT id, text, votes FROM options WHERE poll_id = ? ORDER BY id",
            (poll_id,),
        ).fetchall()
    total = sum(row["votes"] for row in options)
    return {
        "id": poll["id"],
        "title": poll["title"],
        "mode": poll["mode"],
        "duration": poll["duration"],
        "created_at": poll["created_at"],
        "closed": bool(poll["closed"]),
        "remaining": max(0, poll["created_at"] + poll["duration"] - int(time.time())) if poll["duration"] else None,
        "total": total,
        "options": [dict(row) for row in options],
    }


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/create")
def create_page():
    return render_template("create.html")


@app.get("/p/<poll_id>")
def vote_page(poll_id):
    if not poll_json(poll_id):
        return "Опрос не найден", 404
    return render_template("vote.html", poll_id=poll_id)


@app.get("/p/<poll_id>/overlay")
def overlay_page(poll_id):
    if not poll_json(poll_id):
        return "Опрос не найден", 404
    return render_template("overlay.html", poll_id=poll_id)


@app.get("/p/<poll_id>/control")
def control_page(poll_id):
    if not poll_json(poll_id):
        return "Опрос не найден", 404
    return render_template("control.html", poll_id=poll_id)


@app.get("/api/poll/<poll_id>")
def get_poll(poll_id):
    data = poll_json(poll_id)
    if not data:
        return jsonify({"error": "Опрос не найден"}), 404
    if data["mode"] == "timed" and data["remaining"] == 0 and not data["closed"]:
        with db() as conn:
            conn.execute("UPDATE polls SET closed = 1 WHERE id = ?", (poll_id,))
            conn.commit()
        data["closed"] = True
    return jsonify(data)


@app.post("/api/polls")
def create_poll():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    mode = str(data.get("mode", "poll")).strip().lower()
    duration = int(data.get("duration", 0) or 0)
    options = data.get("options", [])

    if not title:
        return jsonify({"error": "Введите вопрос."}), 400
    if mode not in {"poll", "timed", "vote"}:
        return jsonify({"error": "Неизвестный режим."}), 400
    if mode == "timed" and duration < 5:
        return jsonify({"error": "Таймер должен быть не меньше 5 секунд."}), 400
    options = [str(x).strip() for x in options if str(x).strip()]
    if len(options) < 2 or len(options) > 10:
        return jsonify({"error": "Нужно от 2 до 10 вариантов."}), 400

    poll_id = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
    now = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT INTO polls (id, title, mode, duration, created_at) VALUES (?, ?, ?, ?, ?)",
            (poll_id, title, mode, duration if mode == "timed" else 0, now),
        )
        conn.executemany(
            "INSERT INTO options (poll_id, text) VALUES (?, ?)",
            [(poll_id, option) for option in options],
        )
        conn.commit()
    return jsonify({"id": poll_id, "url": f"/p/{poll_id}", "overlay": f"/p/{poll_id}/overlay", "control": f"/p/{poll_id}/control"}), 201


@app.post("/api/poll/<poll_id>/vote")
def vote(poll_id):
    data = request.get_json(silent=True) or {}
    option_id = data.get("option_id")
    voter = str(data.get("voter", "")).strip()
    poll = poll_json(poll_id)
    if not poll:
        return jsonify({"error": "Опрос не найден"}), 404
    if poll["closed"] or (poll["mode"] == "timed" and poll["remaining"] == 0):
        return jsonify({"error": "Опрос уже завершён"}), 409
    if not voter:
        return jsonify({"error": "Не указан идентификатор голосующего"}), 400
    try:
        option_id = int(option_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Неверный вариант"}), 400

    vote_key = f"xyvera_vote_{poll_id}_{voter}"
    # Client-side voter key prevents normal duplicate voting without storing personal data.
    # The server still validates that the option belongs to this poll.
    with db() as conn:
        option = conn.execute("SELECT id FROM options WHERE id = ? AND poll_id = ?", (option_id, poll_id)).fetchone()
        if not option:
            return jsonify({"error": "Вариант не найден"}), 404
        conn.execute("UPDATE options SET votes = votes + 1 WHERE id = ?", (option_id,))
        conn.commit()
    response = poll_json(poll_id)
    response["vote_key"] = vote_key
    return jsonify(response)


@app.post("/api/poll/<poll_id>/close")
def close_poll(poll_id):
    if not poll_json(poll_id):
        return jsonify({"error": "Опрос не найден"}), 404
    with db() as conn:
        conn.execute("UPDATE polls SET closed = 1 WHERE id = ?", (poll_id,))
        conn.commit()
    return jsonify(poll_json(poll_id))


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "xyvera"})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
