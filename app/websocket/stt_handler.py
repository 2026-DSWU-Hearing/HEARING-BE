"""실시간 STT WS 핸들러. /ws/conversations/{id}/stt.
클라이언트가 오디오 청크를 보내면 RTZR API로 전달, 결과를 ConversationBubble로 저장."""

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.models.conversation import ConversationBubble
from app.services import stt_service


async def handle_stt_socket(ws: WebSocket, conversation_id: int, db: AsyncSession) -> None:
    await ws.accept()
    try:
        while True:
            audio_chunk = await ws.receive_bytes()
            text = await stt_service.transcribe_audio(audio_chunk)
            if not text:
                continue
            bubble = ConversationBubble(
                conversation_id=conversation_id,
                speaker="other",
                text=text,
            )
            db.add(bubble)
            await db.commit()
            await db.refresh(bubble)
            await ws.send_json(
                {
                    "type": "bubble",
                    "data": {
                        "id": bubble.id,
                        "speaker": bubble.speaker,
                        "text": bubble.text,
                        "created_at": bubble.created_at.isoformat(),
                    },
                }
            )
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error("stt ws error conv=%s: %s", conversation_id, e)
