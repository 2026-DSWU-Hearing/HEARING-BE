import pytest
from pydantic import ValidationError

from app.schemas.user import (
    EmergencyHapticBoostUpdate,
    HapticUpdate,
    UserResponse,
    emergency_haptic_hw,
    normal_haptic_hw,
)


@pytest.mark.parametrize("haptic_strength", [0, 50, 100])
def test_haptic_update_accepts_0_to_100(haptic_strength):
    payload = HapticUpdate(haptic_strength=haptic_strength)

    assert payload.haptic_strength == haptic_strength


@pytest.mark.parametrize("haptic_strength", [-1, 101])
def test_haptic_update_rejects_out_of_range(haptic_strength):
    with pytest.raises(ValidationError):
        HapticUpdate(haptic_strength=haptic_strength)


@pytest.mark.parametrize("value", [True, False])
def test_emergency_haptic_boost_update_accepts_bool(value):
    payload = EmergencyHapticBoostUpdate(emergency_haptic_boost=value)

    assert payload.emergency_haptic_boost is value


@pytest.mark.parametrize(
    ("ui_strength", "expected_hw"),
    [(0, 0), (70, 56), (100, 80)],
)
def test_normal_haptic_hw_scales_by_ceiling(ui_strength, expected_hw):
    assert normal_haptic_hw(ui_strength) == expected_hw


def test_emergency_haptic_hw_uses_full_scale_when_boosted():
    # 부스트 ON → 여유분까지 풀어 100
    assert emergency_haptic_hw(70, emergency_haptic_boost=True) == 100


def test_emergency_haptic_hw_matches_normal_when_not_boosted():
    # 부스트 OFF → 일반값과 동일
    assert emergency_haptic_hw(70, emergency_haptic_boost=False) == normal_haptic_hw(70)


@pytest.mark.parametrize(
    ("boost", "expected_emergency"),
    [(False, 56), (True, 100)],
)
def test_user_response_exposes_computed_haptic_values(boost, expected_emergency):
    response = UserResponse(
        id=1,
        email="a@b.com",
        nickname="tester",
        disability_type=None,
        haptic_strength=70,
        emergency_haptic_boost=boost,
        do_not_disturb=False,
        push_enabled=True,
        terms_agreed=True,
    )

    assert response.normal_haptic_hw == 56
    assert response.emergency_haptic_hw == expected_emergency