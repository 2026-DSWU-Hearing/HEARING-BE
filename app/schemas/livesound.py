"""livesound(실시간 소리 감지) WS 메시지 스키마.

모드·필터링과 무관한 화면 전용 경로다. 클라이언트(웹/iOS/Android)가 마이크 PCM 을 올리면
AI 서버 분석 결과를 그대로 돌려준다 — 저장도, 알림도, 진동도 없다.
"""

from typing import Literal

from pydantic import BaseModel, field_validator

# YAMNet 입력 규격. 클라이언트가 다른 샘플레이트로 보내면 소리가 느리게/빠르게 해석돼
# 분류가 조용히 엉망이 되므로(에러도 안 난다) start 에서 선언받아 검증한다.
SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # signed int16

# 분석 1회에 넘길 오디오 길이. YAMNet 은 최소 15,600 샘플(0.975초)이 있어야 하므로
# 1초로 잡는다 — 클라이언트가 100ms 씩 보내도 서버가 모아서 창을 만든다.
WINDOW_SECONDS = 1
WINDOW_BYTES = SAMPLE_RATE * WINDOW_SECONDS * BYTES_PER_SAMPLE


class LiveSoundStart(BaseModel):
    """세션 첫 메시지. 오디오 포맷 선언 + 검증."""

    type: Literal["start"]
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    format: Literal["pcm_s16le"] = "pcm_s16le"

    @field_validator("sample_rate")
    @classmethod
    def _only_16k(cls, v: int) -> int:
        if v != SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {SAMPLE_RATE}")
        return v

    @field_validator("channels")
    @classmethod
    def _only_mono(cls, v: int) -> int:
        if v != CHANNELS:
            raise ValueError("channels must be 1 (mono)")
        return v


class SoundItem(BaseModel):
    """화면 한 줄. FE 는 confidence 를 %로 환산해 쓴다(0~1 실수로 보낸다).

    필드명은 detections 채널·감지 페이로드(DetectionCreate)와 **일부러 똑같이** 맞춘다.
    같은 개념(감지된 소리 하나)을 채널마다 다르게 부르면 클라이언트가 두 타입을 섞어 쓴다.
    """

    sound_id: int | None  # 카탈로그에 같은 이름이 있으면 그 id, 없으면 None
    sound_name: str
    sound_category: str
    confidence: float
