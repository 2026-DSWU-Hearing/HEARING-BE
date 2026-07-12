import pytest
from pydantic import ValidationError

from app.schemas.device import DeviceCreate, DeviceUpdate, normalize_mac


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AA:BB:CC:00:11:22", "AA:BB:CC:00:11:22"),
        # 하드웨어/FE 가 소문자·공백 섞어 보내도 저장·조회 양쪽에서 같은 값이 되도록
        ("aa:bb:cc:00:11:22", "AA:BB:CC:00:11:22"),
        (" aa:bb:cc:00:11:22 ", "AA:BB:CC:00:11:22"),
    ],
)
def test_device_create_normalizes_mac(raw, expected):
    payload = DeviceCreate(nickname="내 목걸이", mac_address=raw)

    assert payload.mac_address == expected
    assert normalize_mac(raw) == expected


@pytest.mark.parametrize("battery_level", [0, 100])
def test_device_update_accepts_battery_0_to_100(battery_level):
    payload = DeviceUpdate(battery_level=battery_level)

    assert payload.battery_level == battery_level


@pytest.mark.parametrize("battery_level", [-1, 101])
def test_device_update_rejects_battery_out_of_range(battery_level):
    with pytest.raises(ValidationError):
        DeviceUpdate(battery_level=battery_level)


def test_device_create_rejects_empty_nickname():
    with pytest.raises(ValidationError):
        DeviceCreate(nickname="", mac_address="AA:BB:CC:00:11:22")
