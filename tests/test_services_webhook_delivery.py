import logging
from unittest.mock import Mock, patch
import pytest
import requests
from src.notification_service import NotificationService


def operation(url):
    service = NotificationService(url)
    operations = []
    service._enqueue = operations.append
    service._send_webhook("title", "message")
    return operations[0]


def test_http_failure_is_reported_privately_and_response_is_closed(caplog):
    url = "https://example.test/private-token"
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("500 for " + url)
    with caplog.at_level(logging.INFO), patch("src.notification_service.requests.post", return_value=response):
        operation(url)()
    response.close.assert_called_once()
    assert "HTTPError" in caplog.text
    assert "Webhook notification sent" not in caplog.text
    assert "private-token" not in caplog.text


@pytest.mark.parametrize("url", [
    "https://example.test/ntfy/topic", "https://example.test/?key=pushover",
    "https://pushover.net.evil.test/token", "https://example.test/?service=ntfy.sh"])
def test_payload_detection_does_not_inspect_secret_paths_or_queries(url):
    with patch("src.notification_service.requests.post") as post:
        operation(url)()
    assert post.call_args.kwargs["json"]["app"] == "Ghost Typer"
    assert post.call_args.kwargs["stream"] is True
    post.return_value.raise_for_status.assert_called_once()
    post.return_value.close.assert_called_once()


@pytest.mark.parametrize("url,field", [
    ("https://ntfy.sh/topic", "data"), ("https://ntfy.example.test/topic", "data"),
    ("https://api.pushover.net/1/messages.json", "json")])
def test_recognized_hosts_keep_service_payloads(url, field):
    with patch("src.notification_service.requests.post") as post:
        operation(url)()
    assert field in post.call_args.kwargs
    if field == "json":
        assert "app" not in post.call_args.kwargs[field]
