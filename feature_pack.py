import time
from functools import wraps
from flask import Blueprint, jsonify, render_template, request
import app as core

bp = Blueprint("feature_pack", __name__)
FEATURES = [
"Обычные опросы","Опросы с таймером","Голосования","Закрытие опроса","Автозакрытие","Один голос","Смена голоса","Результаты в реальном времени","Проценты","Счётчик голосов","QR-ссылки","Короткие ссылки","Приватные ссылки","Запланированный старт","Несколько вариантов","Экспорт CSV","История результатов","Публичный профиль","Username URL","Профильные ссылки","Аватар","Bio","Редактирование профиля","Тёмная тема","Светлая тема","Кастомный фон","Кастомные цвета","Анимации","Настройки профиля","Удаление аккаунта","Таймер обратного отсчёта","Таймер вперёд","Пауза","Продолжение","Сброс таймера","Добавление времени","Вычитание времени","Несколько таймеров","Название таймера","Публичный таймер","OBS overlay","Прозрачный overlay","Overlay результатов","Overlay таймера","Control-панель","Автообновление","Stream Deck API","QR для OBS","Панель создателя","Ссылки на OBS","Free план","Pro план","VIP","Permissions","Stripe Checkout","Stripe webhook","История платежей","Лимиты","Rate limit","Проверка сессии","Баны","Временные баны","Приостановка","Жалобы","Журнал действий","Админ-панель","VIP-only действия","Безопасные API","CSRF-защита","CAPTCHA","Статистика просмотров","Уникальные посетители","Статистика голосов","Активность","Популярные опросы","Статистика таймеров","Настройки уведомлений","Импорт данных","Экспорт профиля","Резервные копии"]

def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = core.auth_user()
        if not u: return jsonify({"error":"Требуется вход в аккаунт."}),401
        return fn(u,*args,**kwargs)
    return wrapper

def vip_required(fn):
    @wraps(fn)
    def wrapper(u,*args,**kwargs):
        if not core.is_vip(u): return jsonify({"error":"VIP permission required."}),403
        return fn(u,*args,**kwargs)
    return wrapper

@bp.get("/features")
def features_page(): return render_template("features.html",features=FEATURES)

@bp.get("/api/features")
def features_api(): return jsonify({"count":len(FEATURES),"features":FEATURES})

@bp.get("/api/dashboard")
@require_user
def dashboard(u):
    with core.db() as conn:
        polls=conn.execute("SELECT id,title,mode,slug,closed,created_at FROM polls WHERE owner_id=? ORDER BY created_at DESC LIMIT 100",(u["id"],)).fetchall()
        timers=conn.execute("SELECT id,duration,remaining,running,updated_at FROM timers WHERE owner_id=? ORDER BY updated_at DESC LIMIT 100",(u["id"],)).fetchall()
    return jsonify({"polls":[dict(x) for x in polls],"timers":[dict(x) for x in timers],"vip":core.is_vip(u)})

@bp.get("/api/stats/<poll_id>")
def poll_stats(poll_id):
    data=core.poll_json(poll_id)
    if not data:return jsonify({"error":"Опрос не найден"}),404
    return jsonify({"poll_id":poll_id,"total_votes":data["total"],"options":data["options"],"closed":data["closed"]})

@bp.post("/api/poll/<poll_id>/reopen")
@require_user
def reopen_poll(u,poll_id):
    poll=core.poll_json(poll_id)
    if not poll:return jsonify({"error":"Опрос не найден"}),404
    if not core.can_control(poll["owner_id"],u):return jsonify({"error":"Недостаточно прав."}),403
    with core.db() as conn:
        conn.execute("UPDATE polls SET closed=0,created_at=? WHERE id=?",(int(time.time()),poll_id));conn.commit()
    return jsonify(core.poll_json(poll_id))

@bp.post("/api/timer/<timer_id>/subtract")
@require_user
def subtract_time(u,timer_id):
    timer=core.timer_json(timer_id)
    if not timer:return jsonify({"error":"Таймер не найден"}),404
    if not core.can_control(timer["owner_id"],u):return jsonify({"error":"Недостаточно прав."}),403
    try:seconds=max(1,min(86400,int(request.args.get("seconds",30))))
    except ValueError:return jsonify({"error":"Неверное количество секунд"}),400
    remaining=max(0,timer["remaining"]-seconds)
    with core.db() as conn:
        conn.execute("UPDATE timers SET remaining=?,running=?,updated_at=? WHERE id=?",(remaining,int(timer["running"] and remaining>0),int(time.time()),timer_id));conn.commit()
    return jsonify(core.timer_json(timer_id))

@bp.post("/api/admin/ban")
@require_user
@vip_required
def admin_ban(u):
    data=request.get_json(silent=True) or {};target=str(data.get("user_id","")).strip();reason=str(data.get("reason","")).strip() or "moderation"
    if not target:return jsonify({"error":"user_id обязателен"}),400
    import requests
    access=request.headers.get("Authorization","")
    headers={"apikey":core.SUPABASE_KEY,"Authorization":access,"Content-Type":"application/json"}
    try:
        r=requests.post(f"{core.SUPABASE_URL}/rest/v1/bans",headers=headers,json={"user_id":target,"reason":reason,"banned_by":u["id"]},timeout=10)
        if not r.ok:return jsonify({"error":"Не удалось создать бан","details":r.text}),r.status_code
    except requests.RequestException:return jsonify({"error":"Ошибка подключения к Supabase"}),502
    return jsonify({"ok":True,"user_id":target})
