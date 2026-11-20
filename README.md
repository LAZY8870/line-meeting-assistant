# LINE 會議紀錄助理

結合 LINE Messaging API 與 Flask 的會議資訊助理。

## 功能

- 透過 LINE 文字訊息紀錄會議
- 收集會議名稱、時間與地點
- 缺少資訊時會持續詢問
- 補齊三項資訊後保存會議紀錄
- 提供網頁介面與 `/api/meetings` API

## 安裝

```powershell
cd C:\Users\user\Desktop\line-meeting-assistant
python -m pip install -r requirements.txt
```

建立本機 `.env`，並填入 LINE Console 的 Channel secret 與 Channel access token。

啟動伺服器：

```powershell
python app.py
```

LINE Console 的 Webhook URL 設為：

```text
https://你的公開網址/callback
```
