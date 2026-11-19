import handler


class FakeDedupe:
    class _Exceptions:
        class ConditionalCheckFailedException(Exception):
            pass

    def __init__(self):
        self.meta = type("Meta", (), {
            "client": type("Client", (), {"exceptions": self._Exceptions})()
        })()
        self.items = set()

    def put_item(self, Item, ConditionExpression):
        if Item["notification_id"] in self.items:
            raise self.meta.client.exceptions.ConditionalCheckFailedException()
        self.items.add(Item["notification_id"])

    def delete_item(self, Key):
        self.items.discard(Key["notification_id"])


class FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)


def test_lambda_delivers_once_per_notification(monkeypatch):
    ses = FakeSes()
    dedupe = FakeDedupe()
    monkeypatch.setattr(handler, "_clients", lambda: (ses, dedupe))
    monkeypatch.setenv("SES_SENDER", "library@example.com")
    record = {
        "messageId": "message-1",
        "body": '{"notification_id":"notification-1","recipient":"member@example.com",'
        '"subject":"Ready","body":"Your hold is ready",'
        '"event":{"recipient":"member@example.com","body":"Your hold is ready"}}',
    }

    event = handler.lambda_handler({"Records": [record, record]}, None)

    assert event == {"batchItemFailures": []}
    assert len(ses.sent) == 1
