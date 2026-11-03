def clamp_seconds(seconds: int, low: int, high: int) -> int:
    """Keeps a window length inside [low, high] seconds."""
    return max(low, min(int(seconds), high))


def window_label(seconds: int) -> str:
    """Human-readable window length, for example '10 s' or '2 min'."""
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min"
