def status_label(value: float, warn: float, crit: float, unit: str = "") -> str:
    """Value with a traffic-light marker: red at or above crit, amber at or above warn, green otherwise."""
    if value >= crit:
        return f"🔴 {value:.1f}{unit}"
    if value >= warn:
        return f"🟡 {value:.1f}{unit}"
    return f"🟢 {value:.1f}{unit}"
