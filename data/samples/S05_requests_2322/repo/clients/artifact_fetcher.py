from net_transport.adapters import TLSAdapter


def download_release_tarball(host, strict_tls=True):
    adapter = TLSAdapter()
    return adapter.get_connection_with_tls_context(host, verify=strict_tls)
