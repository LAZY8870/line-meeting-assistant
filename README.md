# LINE 餐廳預約系統

使用 Flask、SQLite 與 LINE Messaging API 的餐廳訂位機器人，另提供受密碼保護的月曆管理後台。

## 預約規則

- 營業時段：每日 11:30–14:30、17:00–20:00。
- 每組用餐 60 分鐘，預約起始時段每小時一班；午、晚餐結束前最後一小時不接受新訂位（最晚分別為 12:30、18:00）。
- 店內有 6 張雙人桌與 6 張四人桌；機器人會選擇可容納人數且桌數最少的組合。
- 一般預約可提前 90 天；日期、人數、營業時間、最晚訂位時間、同人同時段重複預約與剩餘桌位都會驗證，滿位不會超額接受。
- 預約、對話進度與取消狀態存於 SQLite，伺服器重啟後仍保留。
- LINE 可用「預約」、「查詢預約」、「取消預約」操作。

## 管理後台

開啟 `/admin`，使用專案本機 `.env` 中的 `ADMIN_PASSWORD` 登入。後台提供月曆、每天有效訂位數及來客人數、訂位桌位明細與取消功能。

## 安裝

```powershell
cd C:\Users\user\Desktop\line-meeting-assistant
python -m pip install -r requirements.txt
```

建立本機 `.env`，填入 LINE Console 的 Channel secret 與 Channel access token，並設定只供店家使用的 `ADMIN_PASSWORD` 與隨機 `FLASK_SECRET_KEY`。不要將 `.env` 分享或提交至 GitHub。

啟動伺服器：

```powershell
python app.py
```

LINE Console 的 Webhook URL 設為：

```text
https://你的公開網址/callback
```

管理首頁位於 `/`，後台位於 `/admin`。執行測試：

```powershell
python -m unittest discover -s tests -v
```
