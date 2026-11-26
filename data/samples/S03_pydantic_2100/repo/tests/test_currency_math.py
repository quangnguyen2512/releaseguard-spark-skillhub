from billing.currency_math import cents_to_dollars


def test_cents_to_dollars():
    assert cents_to_dollars(1999) == 19.99
