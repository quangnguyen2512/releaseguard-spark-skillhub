from http_client.transport import ClientSession


class WebhookDispatcher:
    def __init__(self):
        self.session = ClientSession(timeout=5.0)

    def deliver_event(self, endpoint_url, outbound_proxy=None):
        return self.session.open_connection(endpoint_url, proxy=outbound_proxy)
