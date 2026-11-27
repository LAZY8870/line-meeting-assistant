import base64
import hashlib
import hmac
import json
import unittest
import uuid
from unittest.mock import patch

import app as application


class FakeApiClient:
    def __init__(self, _configuration):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeMessagingApi:
    replies = []

    def __init__(self, _client):
        pass

    def reply_message(self, reply_request):
        self.replies.append(reply_request)


class LineWebhookTests(unittest.TestCase):
    def setUp(self):
        if application.line_handler is None:
            self.skipTest("LINE SDK and Channel credentials are required")
        self.client = application.app.test_client()
        FakeMessagingApi.replies.clear()
        self.user_id = f"webhook-test-{uuid.uuid4()}"

    def tearDown(self):
        application.reservation_store.clear_state(self.user_id)

    def signed_headers(self, body):
        signature = hmac.new(
            application.channel_secret.encode(),
            body,
            hashlib.sha256,
        ).digest()
        return {
            "Content-Type": "application/json",
            "X-Line-Signature": base64.b64encode(signature).decode(),
        }

    def test_signed_line_booking_message_gets_reply(self):
        payload = {
            "destination": "test-destination",
            "events": [{
                "type": "message",
                "message": {
                    "type": "text",
                    "id": "test-message",
                    "text": "預約",
                    "quoteToken": "test-quote-token",
                },
                "timestamp": 1795161350358,
                "source": {"type": "user", "userId": self.user_id},
                "replyToken": "test-reply-token",
                "webhookEventId": str(uuid.uuid4()),
                "deliveryContext": {"isRedelivery": False},
                "mode": "active",
            }],
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        with patch.object(application, "ApiClient", FakeApiClient), patch.object(
            application, "MessagingApi", FakeMessagingApi
        ):
            response = self.client.post("/callback", data=body, headers=self.signed_headers(body))
        self.assertEqual(response.status_code, 200)
        duplicate = self.client.post("/callback", data=body, headers=self.signed_headers(body))
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(len(FakeMessagingApi.replies), 1)

    def test_invalid_signature_is_rejected(self):
        body = json.dumps({"events": [{"type": "message"}]}).encode()
        response = self.client.post(
            "/callback",
            data=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": "invalid"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
