import hmac
import json
import os
import re
import secrets
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

from reservation import ReservationStore
from reservation_bot import process_reservation_message

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        ApiClient,
        Configuration,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent
except ImportError:
    WebhookHandler = None
    Configuration = None
    MessageEvent = None
    TextMessageContent = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

instance_path = app.instance_path
os.makedirs(instance_path, exist_ok=True)
database_path = os.getenv("RESERVATION_DATABASE") or os.path.join(instance_path, "reservations.sqlite3")
reservation_store = ReservationStore(database_path)

channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
admin_password = os.getenv("ADMIN_PASSWORD")
line_handler = WebhookHandler(channel_secret) if channel_secret and WebhookHandler else None
line_configuration = (
    Configuration(access_token=channel_access_token)
    if channel_access_token and Configuration
    else None
)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            abort(401)
        return view(*args, **kwargs)

    return wrapped


def validate_csrf():
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not token or not hmac.compare_digest(token, session.get("csrf_token", "")):
        abort(403)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("session_id", "web-guest"))[:128]
    message = str(data.get("message", "")).strip()
    return jsonify({"reply": process_reservation_message(reservation_store, user_id, message)})


@app.route("/callback", methods=["POST"])
def callback():
    if line_handler is None:
        return "LINE 尚未設定 Channel secret 或尚未安裝 line-bot-sdk", 503

    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        abort(400)
    if not payload.get("events"):
        return "OK"

    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.warning("LINE webhook signature mismatch")
        abort(400)
    return "OK"


if line_handler and MessageEvent and TextMessageContent:
    @line_handler.add(MessageEvent, message=TextMessageContent)
    def handle_line_message(event):
        if line_configuration is None:
            app.logger.error("LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
            return
        if not reservation_store.claim_webhook_event(getattr(event, "webhook_event_id", None)):
            app.logger.info("Ignoring duplicate LINE webhook event")
            return
        user_id = (
            getattr(event.source, "user_id", None)
            or getattr(event.source, "group_id", None)
            or getattr(event.source, "room_id", None)
        )
        if not user_id:
            app.logger.warning("Ignoring LINE message without user, group, or room ID")
            return
        reply_text = process_reservation_message(reservation_store, user_id, event.message.text)
        with ApiClient(line_configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text[:5000])],
                )
            )


@app.route("/admin", methods=["GET"])
def admin_page():
    if not session.get("admin_logged_in"):
        return render_template("admin_login.html")
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return render_template("admin.html", csrf_token=session["csrf_token"])


@app.route("/admin/login", methods=["POST"])
def admin_login():
    supplied_password = request.form.get("password", "")
    if not admin_password:
        return render_template(
            "admin_login.html",
            error="後台尚未設定密碼，請在本機 .env 設定 ADMIN_PASSWORD 後重新啟動。",
        ), 503
    if not hmac.compare_digest(supplied_password, admin_password):
        return render_template("admin_login.html", error="密碼錯誤，請再試一次。"), 401
    session.clear()
    session["admin_logged_in"] = True
    session["csrf_token"] = secrets.token_urlsafe(32)
    return redirect(url_for("admin_page"))


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("admin_page"))


@app.route("/api/admin/month")
@admin_required
def admin_month():
    month = request.args.get("month", "")
    match = re.fullmatch(r"(\d{4})-(\d{2})", month)
    if not match:
        return jsonify({"error": "月份格式需為 YYYY-MM"}), 400
    year, month_number = (int(value) for value in match.groups())
    if not 1 <= month_number <= 12 or not 2000 <= year <= 2100:
        return jsonify({"error": "月份超出有效範圍"}), 400
    return jsonify(reservation_store.get_month(year, month_number))


@app.route("/api/admin/reservations/<int:reservation_id>/cancel", methods=["POST"])
@admin_required
def admin_cancel_reservation(reservation_id):
    validate_csrf()
    if not reservation_store.cancel_admin_reservation(reservation_id):
        return jsonify({"error": "找不到有效預約，可能已取消。"}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
