import ssl
from services.oauth_fetcher import refresh_access_token


def test_refresh_access_token_ssl_context():
    ctx = ssl.create_default_context()
    res = refresh_access_token("https://auth.example.com/token", ctx)
    assert res["ssl_ready"] is True
