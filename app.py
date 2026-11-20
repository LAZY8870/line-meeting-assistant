from datetime import datetime
import os
import base64
import hashlib
import hmac
import json
from flask import Flask, abort, jsonify, render_template, request
from dotenv import load_dotenv

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

app = Flask(__name__)

meetings = []
conversations = {}
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
line_handler = None
line_configuration = None

if channel_secret and WebhookHandler:
    line_handler = WebhookHandler(channel_secret)
    if channel_access_token:
        line_configuration = Configuration(access_token=channel_access_token)


def parse_meeting(text):
    lowered = text.lower()
    result = {"name": None, "time": None, "location": None}

    for marker in ("會議名稱", "名稱"):
        if marker in text:
            remainder = text.split(marker, 1)[1].lstrip("是為 ：:")
            result["name"] = remainder.split("，", 1)[0].split(" ", 1)[0].strip("。 ")

    for marker in ("地點", "地點是", "地點：", "地點:", "地點為"):
        if marker in text:
            remainder = text.split(marker, 1)[1].lstrip("是為 ：:")
            result["location"] = remainder.split("，", 1)[0].strip("。 ")
            break

    for marker in ("時間", "時間是", "時間為", "時間：", "時間:"):
        if marker in text:
            remainder = text.split(marker, 1)[1].lstrip("是為 ：:")
            result["time"] = remainder.split("，", 1)[0].strip("。 ")
            break

    if not result["time"]:
        time_words = ["今天", "明天", "後天", "今晚", "上午", "下午", "晚上", "星期", "週"]
        if any(word in lowered for word in time_words) or any(char.isdigit() for char in text):
            result["time"] = text.strip("，。 ")

    if not result["location"]:
        for marker in ("在", "於"):
            if marker in text:
                result["location"] = text.split(marker, 1)[1].strip("，。 ")
                break

    return result


def missing_field(draft):
    for field in ("name", "time", "location"):
        if not draft.get(field):
            return field
    return None


FIELD_QUESTIONS = {
    "name": "請問這場會議的名稱是什麼？",
    "time": "請問會議時間是？（例如：明天下午 2 點）",
    "location": "請問會議地點是？（例如：會議室 A 或 Teams）",
}

FIELD_LABELS = {"name": "會議名稱", "time": "時間", "location": "地點"}


def process_message(session_id, text):
    if not text:
        return {"reply": "請輸入訊息，我才能協助你紀錄會議。"}

    draft = conversations.setdefault(session_id, {"name": None, "time": None, "location": None})

    if text.lower() in ("取消", "清除", "重新開始", "reset"):
        conversations[session_id] = {"name": None, "time": None, "location": None}
        return {"reply": "已清除目前的會議資料，我們重新開始吧！", "draft": {"name": None, "time": None, "location": None}}

    missing_before_answer = missing_field(draft)
    parsed = parse_meeting(text)
    for field, value in parsed.items():
        if value:
            draft[field] = value

    if missing_before_answer and not draft.get(missing_before_answer):
        field = missing_before_answer
        time_words = ["今天", "明天", "後天", "今晚", "上午", "下午", "晚上", "星期", "週"]
        looks_like_time = any(word in text for word in time_words) or any(char.isdigit() for char in text)
        if field != "name" or not looks_like_time:
            draft[field] = text.strip("，。 ")

    missing = missing_field(draft)
    if missing:
        return {"reply": FIELD_QUESTIONS[missing], "draft": draft, "missing": missing}

    meeting = {
        "id": len(meetings) + 1,
        "name": draft["name"],
        "time": draft["time"],
        "location": draft["location"],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    meetings.insert(0, meeting)
    conversations[session_id] = {"name": None, "time": None, "location": None}
    return {
        "reply": f"✅ 已完成紀錄：{meeting['name']}｜{meeting['time']}｜{meeting['location']}",
        "meeting": meeting,
        "draft": {"name": None, "time": None, "location": None},
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "default"))
    text = str(data.get("message", "")).strip()
    return jsonify(process_message(session_id, text))


@app.route("/api/meetings")
def get_meetings():
    return jsonify(meetings)


@app.route("/callback", methods=["POST"])
def callback():
    if line_handler is None:
        return "LINE 尚未設定憑證或尚未安裝 line-bot-sdk", 503

    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    if not payload.get("events"):
        return "OK"

    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


if line_handler and TextMessageContent:
    @line_handler.add(MessageEvent, message=TextMessageContent)
    def handle_line_message(event):
        if line_configuration is None:
            app.logger.error("LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
            return
        user_id = event.source.user_id or "line-user"
        result = process_message(user_id, event.message.text)
        reply_text = result["reply"]
        if len(reply_text) > 5000:
            reply_text = reply_text[:4995] + "..."

        with ApiClient(line_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
