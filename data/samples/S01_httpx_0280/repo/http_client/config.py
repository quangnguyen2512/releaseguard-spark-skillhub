import ssl


def build_ssl_settings(verify=True, cert=None):
    if isinstance(verify, ssl.SSLContext):
        return verify
    ctx = ssl.create_default_context()
    if cert is not None:
        ctx.load_cert_chain(cert)
    return ctx
