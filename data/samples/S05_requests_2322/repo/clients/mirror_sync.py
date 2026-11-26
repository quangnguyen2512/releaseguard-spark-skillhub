from net_transport.redirects import strip_sensitive_redirect_headers


def follow_mirror_redirect(req_headers, is_same_host):
    return strip_sensitive_redirect_headers(req_headers, same_origin=is_same_host)
