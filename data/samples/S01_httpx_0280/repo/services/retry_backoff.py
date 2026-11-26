def compute_backoff_delay(attempt, base=0.5):
    return base * (2 ** attempt)
