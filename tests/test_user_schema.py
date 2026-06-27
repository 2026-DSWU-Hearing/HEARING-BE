import pytest
from pydantic import ValidationError

from app.schemas.user import HapticUpdate


@pytest.mark.parametrize("haptic_strength", [0, 50, 100])
def test_haptic_update_accepts_0_to_100(haptic_strength):
    payload = HapticUpdate(haptic_strength=haptic_strength)

    assert payload.haptic_strength == haptic_strength


@pytest.mark.parametrize("haptic_strength", [-1, 101])
def test_haptic_update_rejects_out_of_range(haptic_strength):
    with pytest.raises(ValidationError):
        HapticUpdate(haptic_strength=haptic_strength)