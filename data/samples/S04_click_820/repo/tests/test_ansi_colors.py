from runners.ansi_colors import strip_ansi


def test_strip_ansi():
    assert strip_ansi("hi\x1b[0m") == "hi"
