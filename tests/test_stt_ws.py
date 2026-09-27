"""STT 중계 WS(/ws/conversations/{id}/stt) — 릴레이·EOS 드레인·에러 경로·토큰 캐시.

FE(useSttSocket.ts)와의 계약: 소켓이 열리면 곧바로 PCM 이 온다, 'EOS' 텍스트 뒤 마지막 final 을
받아야 한다, 결과는 {content, isFinal} 이다, 서버 에러는 4xxx close 코드로 안다.
"""

import asyncio
import json
import time
from datetime import datetime, timezone

import pytest

from app.models.conversation import Conversation
from app.models.user import User
from app.services import stt_service
from app.services.stt_service import SttUnavailable, stream_url, to_client_message
from app.websocket import stt_handler
from app.websocket.stt_handler import (
    CLOSE_ALREADY_ENDED,
    CLOSE_NOT_FOUND,
    CLOSE_STT_UNAVAILABLE,
    handle_stt_socket,
    resolve_conversation_close_code,
)

USER_ID = 1
CONV_ID = 7
PCM = b"\x01\x00" * 1600  # 100ms @16kHz int16


def _rtzr(text: str, final: bool) -> dict:
    return {"seq": 0, "start_at": 0, "duration": 100, "final": final, "alternatives": [{"text": text}]}


class FakeClientSocket:
    """FastAPI WebSocket 대역. 미리 넣어둔 프레임을 순서대로 주고, 소진 후엔 release() 까지 매달린다."""

    def __init__(self, incoming: list[dict]):
        self._incoming = list(incoming)
        self._released = asyncio.Event()
        self.sent: list[dict] = []
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        if self._incoming:
            return self._incoming.pop(0)
        await self._released.wait()
        return {"type": "websocket.disconnect"}

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    def release(self) -> None:
        self._released.set()


_CLOSED = object()


class FakeStream:
    """RTZR 대역. push() 한 항목을 순서대로 recv 로 돌려준다 — dict 는 결과, Exception 은 그 자리에서
    던지고(비정상 종료), close_normally() 는 None(정상 종료). 실제 RTZR 은 EOS 를 받아도 남은
    final 을 다 흘린 뒤에야 닫으므로, 닫힘은 EOS 와 묶지 않고 테스트가 명시적으로 넣는다."""

    instances: list["FakeStream"] = []
    connect_error: Exception | None = None

    def __init__(self):
        self.audio: list[bytes] = []
        self.eos = False
        self.closed = False
        self._results: asyncio.Queue = asyncio.Queue()

    @classmethod
    async def connect(cls) -> "FakeStream":
        if cls.connect_error is not None:
            raise cls.connect_error
        instance = cls()
        cls.instances.append(instance)
        return instance

    async def send_audio(self, pcm: bytes) -> None:
        self.audio.append(pcm)

    async def send_eos(self) -> None:
        self.eos = True

    def push(self, item) -> None:
        self._results.put_nowait(item)

    def close_normally(self) -> None:
        self._results.put_nowait(_CLOSED)

    async def recv(self):
        item = await self._results.get()
        if item is _CLOSED:
            return None
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def stream(monkeypatch):
    FakeStream.instances = []
    FakeStream.connect_error = None
    monkeypatch.setattr(stt_handler, "SttStreamClient", FakeStream)
    return FakeStream


# --- 릴레이 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relays_audio_and_maps_results_to_fe_shape(stream):
    ws = FakeClientSocket([{"type": "websocket.receive", "bytes": PCM}] * 3)
    session = asyncio.create_task(handle_stt_socket(ws, USER_ID, CONV_ID))
    await asyncio.sleep(0.05)
    rtzr = stream.instances[0]
    assert ws.accepted and rtzr.audio == [PCM, PCM, PCM]

    rtzr.push(_rtzr("안녕", False))
    rtzr.push(_rtzr("안녕하세요", True))
    rtzr.push({"final": True, "alternatives": []})  # 빈 결과는 FE 로 안 간다
    await asyncio.sleep(0.05)

    assert ws.sent == [
        {"content": "안녕", "isFinal": False},
        {"content": "안녕하세요", "isFinal": True},
    ]
    ws.release()
    await asyncio.wait_for(session, 2)
    assert rtzr.closed


@pytest.mark.asyncio
async def test_eos_is_forwarded_then_remaining_finals_drained_then_closed_normally(stream):
    """FE 는 EOS 를 보낸 뒤 마지막 문장의 final 을 기다린다. 서버가 EOS 직후 닫아버리면 마지막 말이 사라진다."""
    ws = FakeClientSocket(
        [{"type": "websocket.receive", "bytes": PCM}, {"type": "websocket.receive", "text": "EOS"}]
    )
    session = asyncio.create_task(handle_stt_socket(ws, USER_ID, CONV_ID))
    await asyncio.sleep(0.05)
    rtzr = stream.instances[0]
    assert rtzr.eos

    rtzr.push(_rtzr("마지막 문장입니다", True))
    rtzr.close_normally()
    await asyncio.wait_for(session, 2)

    assert ws.sent == [{"content": "마지막 문장입니다", "isFinal": True}]
    assert ws.close_code == 1000
    assert rtzr.closed


@pytest.mark.asyncio
async def test_client_disconnect_tears_down_rtzr(stream):
    ws = FakeClientSocket([{"type": "websocket.receive", "bytes": PCM}, {"type": "websocket.disconnect"}])

    await asyncio.wait_for(handle_stt_socket(ws, USER_ID, CONV_ID), 2)

    assert stream.instances[0].closed


@pytest.mark.asyncio
async def test_unknown_text_frames_are_ignored_not_forwarded(stream):
    """FE 가 다른 텍스트를 보내도 RTZR 세션을 깨지 않는다 — EOS 만 의미가 있다."""
    ws = FakeClientSocket([{"type": "websocket.receive", "text": json.dumps({"type": "start"})}])
    session = asyncio.create_task(handle_stt_socket(ws, USER_ID, CONV_ID))
    await asyncio.sleep(0.05)

    assert stream.instances[0].eos is False
    ws.release()
    await asyncio.wait_for(session, 2)


# --- 에러 경로 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rtzr_unreachable_closes_with_4503_after_accept(stream):
    """accept 전에 close 하면 브라우저는 코드를 못 받는다(HTTP 403) — accept 후 4503."""
    stream.connect_error = SttUnavailable("no creds")
    ws = FakeClientSocket([])

    await asyncio.wait_for(handle_stt_socket(ws, USER_ID, CONV_ID), 2)

    assert ws.accepted and ws.close_code == CLOSE_STT_UNAVAILABLE


@pytest.mark.asyncio
async def test_rtzr_dropping_mid_session_closes_with_4503(stream):
    ws = FakeClientSocket([])
    session = asyncio.create_task(handle_stt_socket(ws, USER_ID, CONV_ID))
    await asyncio.sleep(0.05)
    rtzr = stream.instances[0]

    rtzr.push(SttUnavailable("closed abnormally"))
    await asyncio.wait_for(session, 2)

    assert ws.close_code == CLOSE_STT_UNAVAILABLE and rtzr.closed


# --- 대화 소유/상태 확인(라우터 단계) ----------------------------------------------


@pytest.fixture
def handler_db(monkeypatch, test_session_factory):
    monkeypatch.setattr(stt_handler, "AsyncSessionLocal", test_session_factory)
    return test_session_factory


@pytest.mark.asyncio
async def test_resolve_close_code_checks_ownership_and_ended(handler_db):
    async with handler_db() as db:
        db.add(User(id=1, email="u@t.local", nickname="u", terms_agreed=True))
        db.add(User(id=2, email="o@t.local", nickname="o", terms_agreed=True))
        await db.flush()
        db.add(Conversation(id=10, user_id=1, started_at=datetime.now(timezone.utc)))
        db.add(
            Conversation(
                id=11, user_id=1, started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc)
            )
        )
        await db.commit()

    assert await resolve_conversation_close_code(1, 10) is None
    assert await resolve_conversation_close_code(1, 11) == CLOSE_ALREADY_ENDED
    assert await resolve_conversation_close_code(2, 10) == CLOSE_NOT_FOUND  # 남의 대화
    assert await resolve_conversation_close_code(1, 999) == CLOSE_NOT_FOUND


# --- RTZR 클라이언트 단위 ----------------------------------------------------------


def test_to_client_message_shape():
    assert to_client_message(_rtzr("  안녕 ", False)) == {"content": "안녕", "isFinal": False}
    assert to_client_message(_rtzr("끝", True)) == {"content": "끝", "isFinal": True}
    assert to_client_message({"final": True, "alternatives": []}) is None
    assert to_client_message({"final": True, "alternatives": [{"text": "  "}]}) is None
    assert to_client_message({"final": True}) is None


def test_stream_url_uses_agreed_query(monkeypatch):
    monkeypatch.setattr(stt_service.settings, "RTZR_API_BASE", "https://openapi.vito.ai")

    url = stream_url()

    assert url.startswith("wss://openapi.vito.ai/v1/transcribe:streaming?")
    for expected in (
        "sample_rate=16000",
        "encoding=LINEAR16",
        "model_name=sommers_ko",
        "use_itn=true",
        "use_disfluency_filter=true",
    ):
        assert expected in url


@pytest.mark.asyncio
async def test_token_is_cached_until_near_expiry_and_reissued_after_invalidate(monkeypatch):
    issued: list[float] = []

    async def _fake_issue():
        issued.append(time.time())
        return stt_service._CachedToken(access_token=f"tok{len(issued)}", expires_at=time.time() + 3600)

    monkeypatch.setattr(stt_service, "_issue_token", _fake_issue)
    stt_service.invalidate_token()

    assert await stt_service.get_access_token() == "tok1"
    assert await stt_service.get_access_token() == "tok1"  # 캐시 적중
    assert len(issued) == 1

    # 만료 여유(60초) 안으로 들어오면 아직 유효해도 새로 받는다.
    stt_service._token = stt_service._CachedToken(access_token="stale", expires_at=time.time() + 30)
    assert await stt_service.get_access_token() == "tok2"

    stt_service.invalidate_token()
    assert await stt_service.get_access_token() == "tok3"
    stt_service.invalidate_token()


@pytest.mark.asyncio
async def test_token_issue_requires_credentials(monkeypatch):
    monkeypatch.setattr(stt_service.settings, "RTZR_CLIENT_ID", "")
    monkeypatch.setattr(stt_service.settings, "RTZR_CLIENT_SECRET", "")
    stt_service.invalidate_token()

    with pytest.raises(SttUnavailable):
        await stt_service.get_access_token()
