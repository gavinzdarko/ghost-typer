import threading
from unittest.mock import Mock, patch

from src.notification_service import NotificationService


def test_native_delivery_returns_while_subprocess_is_blocked():
    started, release = threading.Event(), threading.Event()
    def deliver(*args, **kwargs):
        started.set()
        release.wait(2)
    with patch('src.notification_service.subprocess.run', side_effect=deliver):
        service = NotificationService()
        service.notify_paused()
        assert started.wait(1)
        # Queue more events while the only worker is blocked.
        for _ in range(50):
            service.notify_resumed()
        assert service._pending.qsize() == 32
        release.set()
        service._pending.join()


def test_webhook_uses_enqueued_destination_and_does_not_log_secrets(caplog):
    service = NotificationService('https://example.test/secret-token')
    operations = []
    service._enqueue = operations.append
    service._send_webhook('title', 'message')
    service.webhook_url = 'https://example.test/new-destination'
    with patch('src.notification_service.requests.post') as post:
        operations[0]()
    assert post.call_args.args[0] == 'https://example.test/secret-token'
    assert 'secret-token' not in caplog.text
