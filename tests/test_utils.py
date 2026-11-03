from app.utils.errors import error_payload
from app.utils.formatting import status_label
from app.utils.ids import new_id
from app.utils.text import squeeze_repeats
from app.utils.time import clamp_seconds, window_label


def test_new_id_keeps_its_prefix_and_is_unique() -> None:
    first, second = new_id("inc"), new_id("inc")
    assert first.startswith("inc-") and len(first) == len("inc-") + 12
    assert first != second


def test_clamp_seconds_stays_in_range() -> None:
    assert clamp_seconds(5, 10, 3600) == 10
    assert clamp_seconds(99999, 10, 3600) == 3600
    assert clamp_seconds(120, 10, 3600) == 120


def test_window_label_uses_seconds_then_minutes() -> None:
    assert window_label(10) == "10 s"
    assert window_label(120) == "2 min"


def test_squeeze_repeats_collapses_runs() -> None:
    assert squeeze_repeats("hii") == "hi"
    assert squeeze_repeats("helloo") == "helo"


def test_status_label_thresholds() -> None:
    assert status_label(1.0, 3, 5, "%") == "🟢 1.0%"
    assert status_label(4.0, 3, 5, "%") == "🟡 4.0%"
    assert status_label(6.0, 3, 5, "%") == "🔴 6.0%"


def test_error_payload_names_the_exception() -> None:
    assert error_payload(ValueError("bad")) == {"error": "ValueError: bad"}
