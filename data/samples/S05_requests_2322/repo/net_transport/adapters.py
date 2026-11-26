class TLSAdapter:
    def __init__(self):
        self._pools = {}

    def get_connection_with_tls_context(self, host, verify=True):
        pool_key = (host, bool(verify))
        if pool_key not in self._pools:
            self._pools[pool_key] = {"host": host, "verify": bool(verify)}
        return self._pools[pool_key]
