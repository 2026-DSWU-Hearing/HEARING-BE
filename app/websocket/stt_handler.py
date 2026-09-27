"""STT 중계 WS 핸들러. /ws/conversations/{conversation_id}/stt?token=

  클라이언트 마이크 PCM → (여기) → RTZR 스트리밍 → (여기) → 클라이언트 {content, isFinal}

livesound 릴레이와 같은 구조지만 방향이 다르다: 여기는 저장·알림이 전혀 없고 텍스트만 흘린다.
확정된 문장(isFinal)을 버블로 쌓는 건 FE 몫이고, 서버는 [대화 종료] 때 통째로 받는다.

프로토콜
  C→S  바이너리 PCM 조각 (16kHz mono int16, 100ms 단위 — FE 가 소켓 open 직후 바로 보내기 시작한다)
  S→C  {"content":"...","isFinal":false}  (중간 결과, 반복)
  S→C  {"content":"...","isFinal":true}   (문장 확정)
  C→S  텍스트 "EOS"  — 오디오 끝. 남은 final 이 내려온 뒤 서버가 1000 으로 닫는다
                       (FE 는 EOS 후 최대 3초만 기다리고 스스로 닫는다: STT_FINAL_WAIT_MS)

close 코드 (핸드셰이크 거부는 accept 후 close — websocket.py _reject 참고)
  4401  토큰 무효            4404  내 대화가 아니거나 없음
  4409  이미 종료된 대화     4503  RTZR 접속 불가 / 세션 중 두절
"""

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.logger import logger
from app.db.session import AsyncSessionLocal
from app.models.conversation import Conversation
from app.services.stt_service import EOS, SttStreamClient, SttUnavailable, to_client_message

CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_ALREADY_ENDED = 4409
CLOSE_STT_UNAVAILABLE = 4503

# EOS 뒤 RTZR 이 남은 final 을 주고 닫기까지 기다리는 한도. FE 의 3초보다 길게 둬서
# 서버가 먼저 포기하는 일은 없게 한다(FE 가 닫으면 그때 정리된다).
EOS_DRAIN_TIMEOUT_SECONDS = 5.0


async def resolve_conversation_close_code(user_id: int, conversation_id: int) -> int | None:
    """붙어도 되는 대화면 None, 아니면 거부 close 코드."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation.ended_at).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        row = result.one_or_none()
    if row is None:
        return CLOSE_NOT_FOUND
    if row[0] is not None:
        return CLOSE_ALREADY_ENDED
    return None


async def handle_stt_socket(ws: WebSocket, user_id: int, conversation_id: int) -> None:
    """호출 전제: 토큰·대화 소유 확인은 라우터가 끝냈다(websocket.py).

    RTZR 에 먼저 붙고 나서 accept 한다 — FE 는 onopen 에서 곧바로 마이크를 열어 오디오를 쏘므로,
    accept 이후에 상류를 붙이면 그 사이 도착한 첫 청크들을 버리거나 버퍼링해야 한다."""
    try:
        stream = await SttStreamClient.connect()
    except SttUnavailable as e:
        logger.warning("stt: RTZR unavailable user_id=%s conv=%s: %s", user_id, conversation_id, e)
        await ws.accept()
        await ws.close(code=CLOSE_STT_UNAVAILABLE)
        return

    await ws.accept()
    logger.info("stt session started user_id=%s conv=%s", user_id, conversation_id)

    upstream = asyncio.create_task(_pump_upstream(ws, stream), name="stt-upstream")
    downstream = asyncio.create_task(_pump_downstream(ws, stream), name="stt-downstream")
    close_code = 1000
    try:
        done, _ = await asyncio.wait({upstream, downstream}, return_when=asyncio.FIRST_COMPLETED)

        if upstream in done and not upstream.cancelled() and upstream.exception() is None:
            if upstream.result() == "eos" and not downstream.done():
                # 오디오는 끝났지만 마지막 문장의 final 이 아직 안 왔다. RTZR 이 닫을 때까지 흘린다.
                try:
                    await asyncio.wait_for(asyncio.shield(downstream), timeout=EOS_DRAIN_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    logger.warning("stt: RTZR did not close after EOS conv=%s", conversation_id)

        for task in (upstream, downstream):
            if not task.done():
                task.cancel()
            elif not task.cancelled():
                exc = task.exception()
                if isinstance(exc, SttUnavailable):
                    logger.warning("stt: RTZR lost conv=%s: %s", conversation_id, exc)
                    close_code = CLOSE_STT_UNAVAILABLE
                elif exc is not None and not isinstance(exc, WebSocketDisconnect):
                    logger.error("stt session error conv=%s: %s", conversation_id, exc)
                    close_code = CLOSE_STT_UNAVAILABLE
    finally:
        await stream.close()
        try:
            await ws.close(code=close_code)
        except Exception:  # 클라이언트가 먼저 끊었으면 close 가 RuntimeError — 알릴 대상이 없다
            pass
        logger.info("stt session ended user_id=%s conv=%s code=%s", user_id, conversation_id, close_code)


async def _pump_upstream(ws: WebSocket, stream: SttStreamClient) -> str:
    """클라이언트 → RTZR. 반환: 'eos'(오디오 끝, 결과는 계속 받아야 함) | 'disconnect'."""
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return "disconnect"

        text = message.get("text")
        if text is not None:
            if text.strip() == EOS:
                await stream.send_eos()
                return "eos"
            continue  # 알 수 없는 텍스트는 무시 — RTZR 에 그대로 넘기면 세션이 깨질 수 있다

        chunk = message.get("bytes")
        if chunk:
            await stream.send_audio(chunk)


async def _pump_downstream(ws: WebSocket, stream: SttStreamClient) -> None:
    """RTZR → 클라이언트. RTZR 이 정상 종료하면 돌아온다(EOS 처리 완료)."""
    while True:
        payload = await stream.recv()
        if payload is None:
            return
        message = to_client_message(payload)
        if message is not None:
            await ws.send_json(message)
