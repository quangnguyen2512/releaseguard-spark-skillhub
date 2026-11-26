from http_client.config import build_ssl_settings
from http_client.transport import ClientSession


def refresh_access_token(token_url, custom_ssl):
    ctx = build_ssl_settings(verify=custom_ssl)
    client = ClientSession(timeout=3.0)
    return client.open_connection(token_url, ssl_context=ctx)
