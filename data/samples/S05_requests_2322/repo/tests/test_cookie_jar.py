from clients.cookie_jar import parse_cookie_pair


def test_parse_cookie_pair():
    assert parse_cookie_pair("sid=42") == {"sid": "42"}
