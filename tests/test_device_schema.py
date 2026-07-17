import pytest
from pydantic import ValidationError

from app.schemas.device import DetectionCreate, DeviceCreate, DeviceUpdate, normalize_mac


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AA:BB:CC:00:11:22", "AA:BB:CC:00:11:22"),
        # 하드웨어/FE 가 소문자·공백 섞어 보내도 저장·조회 양쪽에서 같은 값이 되도록
        ("aa:bb:cc:00:11:22", "AA:BB:CC:00:11:22"),
        (" aa:bb:cc:00:11:22 ", "AA:BB:CC:00:11:22"),
    ],
)
def test_normalize_mac(raw, expected):
    assert normalize_mac(raw) == expected


def test_device_create_is_nickname_only():
    payload = DeviceCreate(nickname="내 목걸이")

    assert set(DeviceCreate.model_fields) == {"nickname"}
    assert payload.model_dump() == {"nickname": "내 목걸이"}


def test_device_update_is_nickname_only():
    # is_connected·battery_level 은 기기 WS 수명주기 전용 — 클라이언트 PATCH 로 쓸 수 없어야 한다
    # (과거 FE 의 PATCH is_connected:true 가 만든 '유령 연결' 재발 방지)
    assert set(DeviceUpdate.model_fields) == {"nickname"}

    # 구버전 FE 가 보내던 필드는 검증 오류 없이 무시된다 (하위 호환)
    payload = DeviceUpdate(nickname="새 이름", is_connected=True, battery_level=50)
    assert payload.model_dump(exclude_none=True) == {"nickname": "새 이름"}


def test_device_create_rejects_empty_nickname():
    with pytest.raises(ValidationError):
        DeviceCreate(nickname="")


@pytest.mark.parametrize("direction", ["FRONT", "BACK", "LEFT", "RIGHT", "UNKNOWN"])
def test_detection_accepts_supported_directions(direction):
    payload = DetectionCreate(
        sound_name="사이렌",
        sound_category="긴급",
        detected_at="2026-07-16T12:00:00Z",
        direction=direction,
    )

    assert payload.direction == direction


def test_detection_defaults_direction_to_unknown():
    payload = DetectionCreate(
        sound_name="사이렌",
        sound_category="긴급",
        detected_at="2026-07-16T12:00:00Z",
    )

    assert payload.direction == "UNKNOWN"


def test_detection_rejects_unsupported_direction():
    with pytest.raises(ValidationError):
        DetectionCreate(
            sound_name="사이렌",
            sound_category="긴급",
            detected_at="2026-07-16T12:00:00Z",
            direction="left",
        )
