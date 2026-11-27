import re

from reservation import normalize_reservation_time, parse_reservation_date


START_WORDS = {"預約", "訂位", "我要預約", "我要訂位", "開始預約"}
CANCEL_WORDS = {"取消", "取消本次", "重新開始"}
BOOKING_WORDS = {"查詢預約", "我的預約", "預約查詢"}
CANCEL_BOOKING_WORDS = {"取消預約", "我要取消預約"}
HELP_TEXT = (
    "您好，這裡是餐廳訂位小幫手。\n"
    "輸入「預約」開始訂位；輸入「查詢預約」查看訂位；輸入「取消預約」取消訂位。\n"
    "營業時間：11:30–14:30、17:00–20:00。每組用餐 60 分鐘，預約時段每小時一班。"
)


def _format_booking(booking):
    table_text = "、".join(
        f"{table_id.split('-')[0]}人桌{table_id.split('-')[1]}" for table_id in booking["table_ids"]
    )
    return (
        f"#{booking['id']}　{booking['reservation_date']} {booking['reservation_time']}　"
        f"{booking['party_size']} 位　{booking['guest_name']}　桌位：{table_text}"
    )


def _format_tables(table_ids):
    return "、".join(
        f"{table_id.split('-')[0]}人桌{table_id.split('-')[1]}" for table_id in table_ids
    )


def process_reservation_message(store, user_id, message):
    text = (message or "").strip()
    if not text:
        return "請傳送文字訊息；輸入「預約」即可開始訂位。"

    state = store.get_state(user_id)
    if text in CANCEL_WORDS:
        store.clear_state(user_id)
        return "已取消目前操作。如需訂位，請輸入「預約」。"
    if text in ("/start", "說明", "幫助", "help"):
        store.clear_state(user_id)
        return HELP_TEXT
    if text in BOOKING_WORDS:
        store.clear_state(user_id)
        bookings = store.get_user_reservations(user_id)
        if not bookings:
            return "目前沒有尚未到期的有效預約。輸入「預約」可建立新訂位。"
        return "您的有效預約：\n" + "\n".join(_format_booking(item) for item in bookings)
    if text in CANCEL_BOOKING_WORDS:
        bookings = store.get_user_reservations(user_id)
        if not bookings:
            store.clear_state(user_id)
            return "目前沒有可取消的有效預約。"
        store.set_state(user_id, {"step": "cancel_booking"})
        return "請回覆要取消的預約編號：\n" + "\n".join(_format_booking(item) for item in bookings)
    if text in START_WORDS or state is None:
        store.set_state(user_id, {"step": "party_size"})
        return "好的，開始預約。請輸入用餐人數（1–36 位）。"

    step = state.get("step")
    if step == "cancel_booking":
        if not re.fullmatch(r"[0-9]+", text):
            return "請輸入上方預約清單中的數字編號，或輸入「取消」結束操作。"
        if store.cancel_user_reservation(int(text), user_id):
            store.clear_state(user_id)
            return f"已取消預約 #{text}。需要其他協助可輸入「預約」或「查詢預約」。"
        return "找不到這筆有效預約，請重新輸入清單中的編號，或輸入「取消」結束操作。"

    if step == "party_size":
        if not re.fullmatch(r"[0-9]+", text) or not 1 <= int(text) <= 36:
            return "人數請輸入 1 到 36 的整數；超過 36 位請聯絡店家安排。"
        party_size = int(text)
        store.set_state(user_id, {"step": "date", "party_size": party_size})
        return "請輸入預約日期（YYYY/MM/DD），也可輸入「今天」、「明天」或「後天」。可預約未來 90 天。"

    if step == "date":
        reservation_date = parse_reservation_date(text)
        if not reservation_date:
            return "日期格式或範圍不正確。請輸入未過期、90 天內的日期，例如 2026/12/01。"
        party_size = state["party_size"]
        slots = store.get_slots(reservation_date, party_size)
        if not slots:
            return "當日沒有適合的人數與可用桌位，請改選其他日期。"
        store.set_state(
            user_id,
            {"step": "time", "party_size": party_size, "reservation_date": reservation_date.isoformat()},
        )
        return f"{reservation_date.isoformat()} 尚可預約：{'、'.join(slots)}。請回覆其中一個時間。"

    if step == "time":
        reservation_time = normalize_reservation_time(text)
        reservation_date = parse_reservation_date(state["reservation_date"])
        if reservation_date is None:
            store.clear_state(user_id)
            return "這筆預約流程已過期，請輸入「預約」重新開始。"
        slots = store.get_slots(reservation_date, state["party_size"])
        if not reservation_time or reservation_time not in slots:
            available_text = "、".join(slots) if slots else "目前已無可預約時段"
            return f"這個時段不在營業時間、已過時間或桌位不足。可選時段：{available_text}。"
        store.set_state(
            user_id,
            {
                "step": "name",
                "party_size": state["party_size"],
                "reservation_date": reservation_date.isoformat(),
                "reservation_time": reservation_time,
            },
        )
        return "請留下訂位姓名（最多 40 個字）。"

    if step == "name":
        if len(text) > 40 or len(text) < 1:
            return "姓名需為 1–40 個字，請重新輸入。"
        reservation_date = parse_reservation_date(state["reservation_date"])
        if reservation_date is None:
            store.clear_state(user_id)
            return "這筆預約流程已過期，請輸入「預約」重新開始。"
        reservation = store.create_reservation(
            user_id,
            text,
            state["party_size"],
            reservation_date,
            state["reservation_time"],
        )
        if not reservation:
            store.clear_state(user_id)
            return "抱歉，該時段剛被訂滿。請重新輸入「預約」選擇其他時段。"
        store.clear_state(user_id)
        return (
            f"✅ 預約完成！\n"
            f"編號：#{reservation['id']}\n"
            f"姓名：{reservation['guest_name']}\n"
            f"日期時間：{reservation['reservation_date']} {reservation['reservation_time']}\n"
            f"人數：{reservation['party_size']} 位\n"
            f"桌位：{_format_tables(reservation['table_ids'])}\n"
            f"用餐時間 60 分鐘。若要取消，輸入「取消預約」。"
        )

    store.clear_state(user_id)
    return "預約流程已逾期或狀態無效，請輸入「預約」重新開始。"
