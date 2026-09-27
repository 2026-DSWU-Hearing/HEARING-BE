"""양방향 소통 라이브 스모크 — 기동 중인 서버(:8000)에 실제로 붙는다.

  python scripts/smoke_flow_b.py            # HTTP(대화·자주 쓰는 답변) + WS 거부 코드 + RTZR 실연결
  python scripts/smoke_flow_b.py --no-rtzr  # RTZR 실연결(시크릿·외부망 필요)만 건너뜀

RTZR 실연결 단계는 무음 PCM 1초를 보내고 EOS 를 보낸다 — 인식 결과는 (무음이라) 없을 수 있지만,
서버가 RTZR 에 붙어 세션을 정상(1000)으로 닫는지까지 확인한다. 4503 이면 시크릿/외부망을 본다.
"""

import asyncio
import json
import sys

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000"
USER_ID = 1


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        sys.exit(1)


async def smoke_http(token: str) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=10) as c:
        print("대화 API")
        r = await c.post("/api/conversations", json={"latitude": None, "longitude": None})
        _check("POST /api/conversations 201", r.status_code == 201, r.text[:120])
        conversation_id = r.json()["conversation_id"]

        bubbles = [
            {"direction": "left", "inputType": "stt", "content": "주문 도와드릴까요?"},
            {"direction": "right", "inputType": "text", "content": "아메리카노요"},
        ]
        r = await c.post(f"/api/conversations/{conversation_id}/end", json={"bubbles": bubbles})
        _check("POST /end 200 + title/summary", r.status_code == 200 and r.json()["title"], r.text[:160])

        r = await c.post(f"/api/conversations/{conversation_id}/end", json={"bubbles": bubbles})
        _check("POST /end 두 번째 409 ALREADY_ENDED", r.status_code == 409, r.text[:120])

        r = await c.get(f"/api/conversations/{conversation_id}")
        _check("GET 상세 bubbles 2 + inputType", len(r.json()["bubbles"]) == 2 and "inputType" in r.json()["bubbles"][0])

        r = await c.get("/api/conversations", params={"page": 1, "limit": 20})
        _check("GET 목록 total>=1", r.status_code == 200 and r.json()["total"] >= 1, r.text[:120])

        print("자주 쓰는 답변 API")
        r = await c.post("/api/quick-replies", json={"content": "천천히 말씀해 주세요"})
        _check("POST 201", r.status_code == 201, r.text[:120])
        reply_id = r.json()["reply_id"]
        r = await c.put(f"/api/quick-replies/{reply_id}", json={"content": "조금만 천천히요"})
        _check("PUT 200", r.status_code == 200 and r.json()["content"] == "조금만 천천히요")
        r = await c.get("/api/quick-replies")
        _check("GET 목록 포함", any(q["reply_id"] == reply_id for q in r.json()["quick_replies"]))
        r = await c.delete(f"/api/quick-replies/{reply_id}")
        _check("DELETE 200", r.status_code == 200)

        # 새 대화 하나 더 — WS 테스트용(종료 안 함). 끝나면 지운다.
        r = await c.post("/api/conversations", json={"latitude": 37.5, "longitude": 127.0})
        return r.json()["conversation_id"], conversation_id


async def _close_code(url: str) -> int:
    try:
        async with websockets.connect(url) as ws:
            await ws.recv()
    except ConnectionClosed as e:
        return e.rcvd.code if e.rcvd else -1
    return 1000


async def smoke_ws_rejections(token: str, open_conv: int, ended_conv: int) -> None:
    print("STT WS 거부 코드")
    code = await _close_code(f"{WS_BASE}/ws/conversations/{open_conv}/stt?token=bad")
    _check("잘못된 토큰 → 4401", code == 4401, str(code))
    code = await _close_code(f"{WS_BASE}/ws/conversations/999999/stt?token={token}")
    _check("없는 대화 → 4404", code == 4404, str(code))
    code = await _close_code(f"{WS_BASE}/ws/conversations/{ended_conv}/stt?token={token}")
    _check("종료된 대화 → 4409", code == 4409, str(code))


async def smoke_ws_rtzr(token: str, conv: int) -> None:
    print("STT WS RTZR 실연결")
    url = f"{WS_BASE}/ws/conversations/{conv}/stt?token={token}"
    received: list[dict] = []
    try:
        async with websockets.connect(url) as ws:
            silence = b"\x00" * 3200  # 100ms
            for _ in range(10):
                await ws.send(silence)
                await asyncio.sleep(0.1)
            await ws.send("EOS")
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=6)
                    received.append(json.loads(raw))
            except asyncio.TimeoutError:
                _check("EOS 후 6초 내 서버 종료", False, "서버가 닫지 않음")
    except ConnectionClosed as e:
        code = e.rcvd.code if e.rcvd else -1
        _check("RTZR 세션 정상 종료(1000)", code == 1000, f"close code={code} (4503=RTZR 접속 실패: 시크릿/외부망 확인)")
    _check("결과 메시지 형태 {content,isFinal}", all(set(m) == {"content", "isFinal"} for m in received), str(received))
    print(f"  (수신 {len(received)}건 — 무음이라 0건이 정상)")


async def main() -> None:
    token = create_access_token(USER_ID, source="user")
    open_conv, ended_conv = await smoke_http(token)
    await smoke_ws_rejections(token, open_conv, ended_conv)
    if "--no-rtzr" not in sys.argv:
        await smoke_ws_rtzr(token, open_conv)
    async with httpx.AsyncClient(base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        await c.delete(f"/api/conversations/{open_conv}")
        await c.delete(f"/api/conversations/{ended_conv}")
    print("smoke_flow_b: ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
