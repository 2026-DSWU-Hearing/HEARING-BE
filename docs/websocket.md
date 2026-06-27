# WebSocket: Detection In-App Notifications

Local:

```text
ws://localhost:8000/ws/users/me/detections?token={accessToken}
```

## Auth

- `Authorization` header가 아니라 query string의 `token`으로 사용자 access token을 전달함.
- 토큰은 일반 사용자 access token.
- 인증 실패 시 서버가 close code `4401`로 연결을 닫음.

## Message

```json
{
  "type": "detection",
  "data": {
    "id": 1,
    "sound_name": "사이렌",
    "sound_category": "긴급",
    "source": "ai-server",
    "confidence": 0.95,
    "location": null,
    "detected_at": "2026-06-28T00:00:00+09:00"
  }
}
```