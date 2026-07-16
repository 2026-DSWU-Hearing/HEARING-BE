import pytest
from pydantic import ValidationError

from app.schemas.user import HapticUpdate, UserUpdate


@pytest.mark.parametrize("haptic_strength", [0, 50, 100])
def test_haptic_update_accepts_0_to_100(haptic_strength):
    payload = HapticUpdate(haptic_strength=haptic_strength)

    assert payload.haptic_strength == haptic_strength


@pytest.mark.parametrize("haptic_strength", [-1, 101])
def test_haptic_update_rejects_out_of_range(haptic_strength):
    with pytest.raises(ValidationError):
        HapticUpdate(haptic_strength=haptic_strength)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HARD_OF_HEARING", "HARD_OF_HEARING"),
        ("DEAF", "DEAF"),
        # FE 온보딩은 소문자를 보낸다 — 정본(대문자)으로 정규화돼야 한다
        ("hard_of_hearing", "HARD_OF_HEARING"),
        ("deaf", "DEAF"),
        (" deaf ", "DEAF"),
        (None, None),
    ],
)
def test_user_update_normalizes_disability_type(raw, expected):
    payload = UserUpdate(disability_type=raw)

    assert payload.disability_type == expected


@pytest.mark.parametrize("raw", ["BLIND", "hearing", ""])
def test_user_update_rejects_unknown_disability_type(raw):
    with pytest.raises(ValidationError):
        UserUpdate(disability_type=raw)