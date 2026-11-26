from services.retry_backoff import compute_backoff_delay


def test_compute_backoff_delay():
    assert compute_backoff_delay(2, base=0.5) == 2.0
