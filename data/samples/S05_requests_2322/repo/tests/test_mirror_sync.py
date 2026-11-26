from clients.mirror_sync import follow_mirror_redirect


def test_follow_mirror_redirect_strips_proxy_auth():
    out = follow_mirror_redirect({"Proxy-Authorization": "Basic abc", "Accept": "*/*"}, is_same_host=False)
    assert "Proxy-Authorization" not in out
