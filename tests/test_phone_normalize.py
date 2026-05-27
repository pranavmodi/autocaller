"""Tests for canonical phone normalization."""
import pytest

from app.services.phone_normalize import normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("818-784-8544", "+18187848544"),
        ("1 (818) 784-8544", "+18187848544"),
        ("+44 20 7946 0958", "+442079460958"),
        ("Primary: 818-784-8544; Additional: 424-283-5822", "+18187848544"),
        ("818-784-8544, Fax: 818-784-5970", "+18187848544"),
        ("818-784-8544 ext. 12", "+18187848544"),
        ("818-784-8544 x99", "+18187848544"),
        ("", ""),
        (None, ""),
        ("12345", ""),
        ("2-818-784-8544", ""),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
