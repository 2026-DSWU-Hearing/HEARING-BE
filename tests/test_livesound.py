"""livesound(실시간 소리 감지) WS — 릴레이·버퍼링·백프레셔·에러 경로.

이 경로의 핵심 계약은 '감지 흐름을 건드리지 않는다'와 '1초 창이 모여야 분석한다' 둘이다.
전자는 notification_service 를 아예 import 하지 않는 것으로, 후자는 여기서 검증한다.
"""

import asyncio
import json
import time

import pytest

from app.core.config import settings
from app.schemas.livesound import WINDOW_BYTES, SoundItem
from app.services.livesound_service import (
    AnalyzerClient,
    AnalyzerUnavailable,
    to_sound_items,
)
from app.websocket import livesound_handler
from app.websocket.livesound_handler import _offer_latest, handle_livesound_socket

START = json.dumps({"type": "start", "sample_rate": 16000, "channels": 1, "format": "pcm_s16le"})
SILENCE = b"\x00" * WINDOW_BYTES
# FE 가 start 이후 ready 를 기다리는 시간(liveSound/hooks/useLiveSoundSocket.ts 의 READY_TIMEOUT_MS).
# 서버 쪽 접속 타임아웃은 이보다 짧아야 한다.
CLIENT_READY_TIMEOUT_SECONDS = 5.0


class FakeClientSocket:
    """FastAPI WebSocket 대역. 미리 넣어둔 프레임을 순서대로 주고, 소진 후엔
    release() 될 때까지 매달린다 — 실제 클라이언트처럼 '아직 안 끊긴' 상태를 재현한다."""

    def __init__(self, incoming: list[dict]):
        self._incoming = list(incoming)
        self._released = asyncio.Event()
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        if self._incoming:
            return self._incoming.pop(0)
        await self._released.wait()
        return {"type": "websocket.disconnect"}

    async def receive_text(self) -> str:
        message = await self.receive()
        return message["text"]

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    def release(self) -> None:
        self._released.set()

    async def wait_for_sent(self, count: int, timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            while len(self.sent) < count:
                await asyncio.sleep(0.01)

    def types(self) -> list[str]:
        return [message["type"] for message in self.sent]


class FakeAnalyzer:
    """AI 서버 대역. analyze 호출마다 고정 결과를 준다(AI 응답 원본 형태)."""

    instances: list["FakeAnalyzer"] = []

    def __init__(self):
        self.windows: list[bytes] = []
        self.closed = False

    @classmethod
    async def connect(cls) -> "FakeAnalyzer":
        instance = cls()
        cls.instances.append(instance)
        return instance

    async def analyze(self, pcm: bytes) -> list[dict]:
        self.windows.append(pcm)
        return [{"category": "교통", "block": "경적", "sound": "Vehicle horn", "score": 0.82}]

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def analyzer(monkeypatch):
    FakeAnalyzer.instances = []
    monkeypatch.setattr(livesound_handler, "AnalyzerClient", FakeAnalyzer)
    return FakeAnalyzer


@pytest.fixture
def catalog(monkeypatch, test_session_factory):
    """카탈로그 조회가 테스트 DB(마이그레이션으로 시드된 실물)를 보게 한다."""
    monkeypatch.setattr(livesound_handler, "AsyncSessionLocal", test_session_factory)


# --- 필드명 계약 -------------------------------------------------------------


def test_sound_item_field_names_match_detection_payload():
    """livesound 와 감지 흐름이 같은 개념을 다른 이름으로 부르면 안 된다.

    한때 livesound 만 name/category 를 써서, 클라이언트가 detections 타입과 섞어 쓰면
    조용히 undefined 가 되는 상태였다. 두 채널의 소리 필드는 같은 이름을 유지한다.
    """
    from app.schemas.device import DetectionCreate

    sound_fields = {"sound_id", "sound_name", "sound_category", "confidence"}
    assert set(SoundItem.model_fields) == sound_fields
    assert sound_fields <= set(DetectionCreate.model_fields)


@pytest.mark.asyncio
async def test_catalog_matches_the_names_ai_actually_sends(db):
    """카탈로그와 AI 의 이름이 어긋나면 양쪽으로 조용히 깨진다.

    - 카탈로그에만 있는 이름: AI 가 만들어낼 수 없으니 모드에 넣어도 평생 안 울린다.
    - AI 만 내는 이름: 카탈로그에 없으니 sound_id 가 null 로 나간다.

    이름 매칭이 AI↔백엔드의 유일한 연결 고리라, AI(category_map.py)가 여러 YAMNet 라벨을
    하나로 접어둔 두 곳을 AI 기준으로 고정한다 — 음악 계열 9개 라벨(Music/Piano/Guitar/
    Violin/Drum/Jazz/Classical music/Orchestra/Electronic music)은 ("생활음", "음악") 하나로,
    칼·수저(Cutlery, silverware)는 그릇·냄비와 함께 "식기" 로 접혀 "주방 도구" 는 발화 불가능하다.
    """
    from sqlalchemy import select

    from app.models.sound import Sound, SoundCategory

    async def pairs(names: list[str]) -> list[tuple[str, str]]:
        rows = await db.execute(
            select(SoundCategory.name, Sound.name)
            .join(Sound, Sound.category_id == SoundCategory.id)
            .where(Sound.name.in_(names))
        )
        return [tuple(row) for row in rows]

    assert await pairs(
        ["음악", "대중 음악", "피아노", "현악기", "드럼", "재즈", "클래식"]
    ) == [("생활음", "음악")]

    assert await pairs(["주방 도구"]) == []

    # 비워진 '음악' 카테고리를 남기면 소리 목록 화면에 항목 없는 섹션이 뜬다.
    categories = (await db.execute(select(SoundCategory.name))).scalars().all()
    assert "음악" not in categories


# --- 응답 변환 ---------------------------------------------------------------


def test_to_sound_items_maps_analyzer_shape():
    """AI 의 block/score 를 화면용 name/confidence 로 옮기고 카탈로그 id 를 붙인다."""
    items = to_sound_items(
        [{"category": "교통", "block": "경적", "score": 0.82}],
        {("교통", "경적"): 17},
    )

    assert items == [
        {"sound_id": 17, "sound_name": "경적", "sound_category": "교통", "confidence": 0.82}
    ]


def test_to_sound_items_separates_same_name_in_different_categories():
    """'충돌·파손음' 은 긴급/생활음 두 카테고리에 각각 존재한다.

    이름만으로 id 를 찾으면 한쪽이 다른 쪽 id 를 물고 나가서, 나중에 이 항목으로
    '모드에 추가' 같은 걸 하면 엉뚱한 소리가 붙는다. AI 도 (카테고리, 이름) 쌍으로
    중복을 거르므로 두 항목은 한 스냅샷에 함께 올 수 있다.
    """
    items = to_sound_items(
        [
            {"category": "긴급", "block": "충돌·파손음", "score": 0.51},
            {"category": "생활음", "block": "충돌·파손음", "score": 0.33},
        ],
        {("긴급", "충돌·파손음"): 14, ("생활음", "충돌·파손음"): 46},
    )

    assert [item["sound_id"] for item in items] == [14, 46]


def test_to_sound_items_keeps_unknown_names_with_null_id():
    """카탈로그에 없는 이름도 화면엔 띄운다 — id 만 None."""
    items = to_sound_items([{"category": "기타", "block": "미등록소리", "score": 0.3}], {})

    assert items[0]["sound_id"] is None
    assert items[0]["sound_name"] == "미등록소리"


def test_to_sound_items_keeps_low_confidence():
    """livesound 는 임계값 컷을 하지 않는다 — 낮은 신뢰도도 화면에 보여준다."""
    items = to_sound_items([{"category": "생활음", "block": "가전제품", "score": 0.02}], {})

    assert len(items) == 1 and items[0]["confidence"] == 0.02


def test_to_sound_items_drops_malformed_entries():
    items = to_sound_items(
        [
            {"category": "교통", "block": "경적", "score": 0.8},
            {"category": "교통", "score": 0.5},  # block 없음
            {"category": "교통", "block": "사이렌", "score": "높음"},  # score 가 숫자가 아님
            "쓰레기",
        ],
        {},
    )

    assert [item["sound_name"] for item in items] == ["경적"]


# --- 백프레셔 ----------------------------------------------------------------


def test_offer_latest_discards_backlog():
    """분석이 밀리면 최신 창만 남는다 — 오래된 오디오로 화면이 뒤처지지 않게."""
    windows: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)

    _offer_latest(windows, b"old")
    _offer_latest(windows, b"new")

    assert windows.get_nowait() == b"new"
    assert windows.empty()


# --- 분석기 접속 -------------------------------------------------------------


def test_connect_timeout_leaves_room_before_client_gives_up():
    """접속 대기는 클라이언트의 ready 대기(FE READY_TIMEOUT_MS = 5초)보다 짧아야 한다.

    같거나 길면 AI 서버가 늘어졌을 때 ANALYZER_UNAVAILABLE 안내가 도착하기 전에
    클라이언트가 먼저 끊어서, 사용자는 원인을 알 수 없는 침묵만 보게 된다.
    """
    assert settings.AI_CONNECT_TIMEOUT_SECONDS < CLIENT_READY_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_connect_gives_up_on_hanging_analyzer(monkeypatch):
    """응답 없는 AI 서버는 **접속** 타임아웃으로 포기하고 AnalyzerUnavailable 로 바꾼다.

    왕복 타임아웃(AI_ANALYZE_TIMEOUT_SECONDS)을 쓰면 안 된다 — 그 값은 ready 이후
    기준이라 훨씬 길게 잡혀 있고, 여기에 걸면 위 테스트가 지키는 여유가 사라진다.
    두 값을 크게 벌려놔서 잘못된 쪽을 쓰면 경과 시간으로 바로 걸린다.
    """

    async def _never_completes_handshake(url):
        await asyncio.sleep(30)

    monkeypatch.setattr("websockets.asyncio.client.connect", _never_completes_handshake)
    monkeypatch.setattr(settings, "AI_CONNECT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(settings, "AI_ANALYZE_TIMEOUT_SECONDS", 30.0)

    started = time.perf_counter()
    with pytest.raises(AnalyzerUnavailable):
        await asyncio.wait_for(AnalyzerClient.connect(), timeout=5)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, "왕복 타임아웃(30초)에 걸렸다 — connect 가 접속 타임아웃을 안 쓴다"


# --- 분석기 응답 해석 --------------------------------------------------------


class FakeAnalyzerSocket:
    """AI 서버 소켓 대역. 정해둔 원문 한 건을 돌려준다."""

    def __init__(self, raw):
        self._raw = raw

    async def send(self, pcm: bytes) -> None:
        pass

    async def recv(self):
        return self._raw


async def _analyze_response(raw) -> list[dict]:
    return await AnalyzerClient(FakeAnalyzerSocket(raw)).analyze(SILENCE)


@pytest.mark.asyncio
async def test_ok_with_empty_list_is_normal_silence():
    """status=ok 인데 top_sounds 가 비었으면 '조용하다'는 정상 신호다 — 끊으면 안 된다."""
    assert await _analyze_response('{"status":"ok","top_sounds":[]}') == []


@pytest.mark.asyncio
async def test_analyzer_error_is_not_mistaken_for_silence():
    """분석 실패도 top_sounds 를 [] 로 함께 보낸다 — status 를 안 보면 무음과 구분이 안 된다.

    그대로 두면 화면에 '감지된 소리 없음'이 뜨면서 실패가 조용히 묻힌다.
    """
    raw = '{"status":"error","message":"invalid audio frame size","top_sounds":[]}'
    with pytest.raises(AnalyzerUnavailable, match="invalid audio frame size"):
        await _analyze_response(raw)


@pytest.mark.asyncio
async def test_missing_status_is_treated_as_failure():
    """status 없는 응답은 계약 위반이라 성공으로 넘기지 않는다."""
    with pytest.raises(AnalyzerUnavailable):
        await _analyze_response('{"top_sounds":[]}')


@pytest.mark.asyncio
async def test_non_object_response_reports_error_instead_of_silent_close():
    """JSON 이지만 객체가 아니면 예전엔 AttributeError 로 터졌다.

    그 예외는 AnalyzerUnavailable 이 아니라서 호출측이 FE 에 아무 안내도 못 보내고
    소켓만 닫혔다 — 사용자는 원인 없는 침묵만 본다.
    """
    with pytest.raises(AnalyzerUnavailable):
        await _analyze_response("[]")


@pytest.mark.asyncio
async def test_invalid_top_sounds_type_is_rejected():
    with pytest.raises(AnalyzerUnavailable):
        await _analyze_response('{"status":"ok","top_sounds":"경적"}')


# --- 세션 흐름 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_streams_classification(analyzer, catalog):
    """start → ready → (조각 2개가 1초 창을 채움) → classification."""
    half = WINDOW_BYTES // 2
    socket = FakeClientSocket([
        {"type": "websocket.receive", "text": START},
        {"type": "websocket.receive", "bytes": SILENCE[:half]},
        {"type": "websocket.receive", "bytes": SILENCE[half:]},
    ])

    session = asyncio.create_task(handle_livesound_socket(socket, user_id=1))
    await socket.wait_for_sent(2)
    socket.release()
    await asyncio.wait_for(session, timeout=2)

    assert socket.types() == ["ready", "classification"]
    sounds = socket.sent[1]["data"]["sounds"]
    assert sounds[0]["sound_name"] == "경적" and sounds[0]["confidence"] == 0.82
    assert sounds[0]["sound_id"] is not None  # 카탈로그에 '경적'이 있으므로 해석됨
    assert analyzer.instances[0].windows == [SILENCE]  # 조각이 아니라 온전한 1초 창이 넘어갔다
    assert analyzer.instances[0].closed is True


@pytest.mark.asyncio
async def test_partial_window_is_not_analyzed(analyzer, catalog):
    """1초가 안 모이면 분석하지 않는다 — YAMNet 최소 길이(15,600 샘플) 미달 방지."""
    socket = FakeClientSocket([
        {"type": "websocket.receive", "text": START},
        {"type": "websocket.receive", "bytes": SILENCE[: WINDOW_BYTES // 2]},
    ])

    session = asyncio.create_task(handle_livesound_socket(socket, user_id=1))
    await socket.wait_for_sent(1)
    socket.release()
    await asyncio.wait_for(session, timeout=2)

    assert socket.types() == ["ready"]
    assert analyzer.instances[0].windows == []


@pytest.mark.asyncio
async def test_stop_message_ends_session(analyzer, catalog):
    socket = FakeClientSocket([
        {"type": "websocket.receive", "text": START},
        {"type": "websocket.receive", "text": json.dumps({"type": "stop"})},
    ])

    await asyncio.wait_for(handle_livesound_socket(socket, user_id=1), timeout=2)

    assert socket.types() == ["ready"]
    assert analyzer.instances[0].closed is True


@pytest.mark.asyncio
async def test_wrong_sample_rate_is_rejected_before_connecting(analyzer, catalog):
    """48kHz 를 그대로 받으면 분류가 조용히 망가진다 — 분석기에 붙기 전에 끊는다."""
    socket = FakeClientSocket([
        {"type": "websocket.receive", "text": json.dumps({"type": "start", "sample_rate": 48000})},
    ])

    await asyncio.wait_for(handle_livesound_socket(socket, user_id=1), timeout=2)

    assert socket.types() == ["error"]
    assert socket.sent[0]["code"] == "INVALID_START"
    assert analyzer.instances == []  # 분석기 연결조차 시도하지 않았다


@pytest.mark.asyncio
async def test_analyzer_unavailable_reports_error(monkeypatch, catalog):
    async def _refuse():
        raise AnalyzerUnavailable("connection refused")

    monkeypatch.setattr(livesound_handler.AnalyzerClient, "connect", _refuse)
    socket = FakeClientSocket([{"type": "websocket.receive", "text": START}])

    await asyncio.wait_for(handle_livesound_socket(socket, user_id=1), timeout=2)

    assert socket.sent == [
        {
            "type": "error",
            "code": "ANALYZER_UNAVAILABLE",
            "message": "소리 분석 서버에 연결할 수 없습니다.",
        }
    ]


@pytest.mark.asyncio
async def test_analyzer_dropping_midsession_reports_error(analyzer, catalog):
    """세션 도중 AI 가 끊기면 조용히 멈추지 않고 error 로 알린다(FE 가 error 상태로 전환)."""

    async def _die(self, pcm):
        raise AnalyzerUnavailable("socket closed")

    FakeAnalyzer.analyze = _die
    try:
        socket = FakeClientSocket([
            {"type": "websocket.receive", "text": START},
            {"type": "websocket.receive", "bytes": SILENCE},
        ])

        session = asyncio.create_task(handle_livesound_socket(socket, user_id=1))
        await socket.wait_for_sent(2)
        socket.release()
        await asyncio.wait_for(session, timeout=2)

        assert socket.types() == ["ready", "error"]
        assert socket.sent[1]["code"] == "ANALYZER_UNAVAILABLE"
    finally:
        del FakeAnalyzer.analyze
