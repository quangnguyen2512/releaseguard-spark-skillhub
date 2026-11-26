def strip_ansi(text):
    return text.replace("\x1b[0m", "")
