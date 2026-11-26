from http_client.config import build_ssl_settings


class ClientSession:
    def __init__(self, timeout=10.0):
        self.timeout = timeout

    def open_connection(self, url, proxy=None, ssl_context=None):
        ctx = build_ssl_settings(verify=ssl_context)
        return {"url": url, "proxy": proxy, "ssl_ready": ctx is not None, "timeout": self.timeout}
