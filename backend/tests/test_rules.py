from datetime import date, datetime

import pytest

from app.rules import normalize_email, parse_date, parse_timestamp


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Julia.Evans230@Gmail.com", "julia.evans230@gmail.com"),
        ("  zoe.allen235@gmail.com ", "zoe.allen235@gmail.com"),
        ("EMILY.MILLER827@GMAIL.COM", "emily.miller827@gmail.com"),
        ("not-an-email", None),
        ("@gmail.com", None),
        ("name@nodot", None),
        ("two words@gmail.com", None),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


def test_parse_date():
    assert parse_date("2026-09-28") == date(2026, 9, 28)
    assert parse_date("") is None
    with pytest.raises(ValueError):
        parse_date("09/28/2026")


def test_parse_timestamp_converts_to_naive_utc():
    assert parse_timestamp("2026-09-28 14:22:05") == datetime(2026, 9, 28, 14, 22, 5)
    assert parse_timestamp("2026-09-28T14:22:05Z") == datetime(2026, 9, 28, 14, 22, 5)
    assert parse_timestamp("2026-09-28T07:22:05-07:00") == datetime(2026, 9, 28, 14, 22, 5)
    assert parse_timestamp(" ") is None
