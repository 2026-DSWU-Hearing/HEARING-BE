"""WebSocket 연결 매니저.
ConnectionManager: 웹앱 유저 (user_id → 연결 리스트)
DeviceConnectionManager: 하드웨어 (정규화 MAC → 단일 연결)
  — 실물 기기 단위 식별. 여러 계정이 같은 MAC 을 공유하므로 Device.id 가 아니라 MAC 으로 키를 잡는다.
"""

from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._user_connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._user_connections[user_id].append(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        if ws in self._user_connections.get(user_id, []):
            self._user_connections[user_id].remove(ws)
        if not self._user_connections.get(user_id):
            self._user_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, message: dict) -> None:
        for ws in list(self._user_connections.get(user_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(user_id, ws)


class DeviceConnectionManager:
    """하드웨어(ESP32) WS 연결 매니저. 기기(MAC)당 연결 하나 — 재접속하면 기존 연결을 교체한다."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, mac: str, ws: WebSocket) -> None:
        await ws.accept()
        old = self._connections.pop(mac, None)
        self._connections[mac] = ws
        if old is not None:
            try:
                await old.close(code=4409)  # 새 연결로 교체됨
            except Exception:
                pass

    def disconnect(self, mac: str, ws: WebSocket) -> bool:
        """이 ws가 현재 활성 연결일 때만 제거하고 True.
        교체·강제종료로 이미 빠진 연결이면 False — 호출측이 DB 상태를 덮어쓰지 않도록."""
        if self._connections.get(mac) is ws:
            self._connections.pop(mac, None)
            return True
        return False

    async def send_to_device(self, mac: str, message: dict) -> bool:
        ws = self._connections.get(mac)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:
            self.disconnect(mac, ws)
            return False

    async def close_device(self, mac: str) -> bool:
        """서버측 강제 종료 (해당 MAC 의 마지막 등록이 삭제됐을 때). 살아있는 연결이 있었으면 True."""
        ws = self._connections.pop(mac, None)
        if ws is None:
            return False
        try:
            await ws.close(code=1000)
        except Exception:
            pass
        return True


manager = ConnectionManager()
device_manager = DeviceConnectionManager()
