from clients.artifact_fetcher import download_release_tarball


def test_download_release_tarball_verify_key():
    conn = download_release_tarball("files.example.org", strict_tls=False)
    assert conn["verify"] is False
