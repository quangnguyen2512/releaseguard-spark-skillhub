from endpoints.healthcheck import liveness_probe


def test_liveness_probe():
    assert liveness_probe()["status"] == "ok"
