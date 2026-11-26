from services.webhook_sender import WebhookDispatcher


def test_deliver_event_uses_proxy():
    dispatcher = WebhookDispatcher()
    res = dispatcher.deliver_event("https://hooks.example.com", outbound_proxy="http://proxy.local:8080")
    assert res["proxy"] == "http://proxy.local:8080"
