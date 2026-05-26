"""WebSocket 연결 매니저. user_id → 연결 리스트."""

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


manager = ConnectionManager()
