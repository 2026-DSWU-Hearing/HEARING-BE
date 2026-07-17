# WebSocket: Detection In-App Notifications

Local:

```text
ws://localhost:8000/ws/users/me/detections?token={accessToken}
```

## Auth

- `Authorization` header가 아니라 query string의 `token`으로 사용자 access token을 전달함.
- 토큰은 일반 사용자 access token.
- 인증 실패 시 서버가 close code `4401`로 연결을 닫음 (핸드셰이크는 수락된 직후 닫힘 — 클라이언트는 onclose 의 code 로 구분).

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

# WebSocket: 하드웨어(ESP32) 상태/명령 채널

Local:

```text
ws://localhost:8000/ws/devices?token={deviceToken}&mac={macAddress}
```

## Auth / 바인딩

- `token`: 장수명 디바이스 토큰 (`python scripts/make_device_token.py` 로 발급, source="device").
  '정품 기기' 증명용 — 어느 기기인지는 MAC 으로 정해지므로 기기 재등록에도 토큰은 유효.
- `mac`: 기기 실제 MAC (`44:1B:F6:D4:47:F0`). 대소문자·공백 무관(등록·접속 양쪽 모두 정규화).
  **실물 기기는 한 대를 여러 계정이 공유**할 수 있다. 로그인만으로 기기 행을 만들지는 않고,
  사용자가 `POST /devices`로 이름을 등록하면 서버가 이 MAC을 저장한다. 초기
  `is_connected=false`는 FE의 기기 연결 중 상태이며, 이 WS 하나가 그 MAC을 등록한
  **모든 계정**의 연결 상태를 갱신한다. 같은 계정의 재등록은 멱등이다.
- close 코드: 토큰 불량 `4401` · 미등록 MAC `4404` · 같은 기기 재접속 시 기존 연결 `4409` 후 교체.
  거절 시에도 핸드셰이크는 수락된 직후 닫히므로 클라이언트는 close 코드로 원인을 구분할 수 있음.

## 수명주기 → DB (FE 는 GET /devices 폴링으로 자동 반영)

- 접속: `is_connected=true`, `last_seen_at` 갱신 (해당 MAC 의 전 계정)
- 해제: `is_connected=false`
- 서버 기동 시 전 기기 `is_connected=false` 리셋 (WS 는 재시작을 살아남지 못하므로)
- `is_connected` 의 진실 원천은 이 수명주기뿐 — `PATCH /devices/{id}` 는 닉네임만 받고
  `is_connected`/`battery_level` 필드는 무시된다 (과거 '유령 연결' 원인 제거)
- 마지막 남은 등록 계정이 기기를 `DELETE` 하면 서버가 이 WS 를 닫음

## 수신 (기기 → 서버) — 권장 주기 30초

```json
{ "type": "status", "battery_level": 85, "connection_type": "wifi" }
```

- `battery_level`: 0~100 (범위 밖은 절삭) → DB 반영
- `connection_type`: `"wifi" | "hotspot"` — 로그만 남김 (FE 미표시)

## 송신 (서버 → 기기) — 감지가 활성 모드에 매칭될 때

```json
{ "type": "vibrate", "strength": 50, "sound_name": "사이렌", "sound_category": "긴급", "direction": "LEFT" }
```

- `strength`: 사용자 설정 진동 세기 (`users.haptic_strength`, 0~100)
- `direction`: 소리가 감지된 방향 (`"FRONT" | "BACK" | "LEFT" | "RIGHT" | "UNKNOWN"`)
  - 감지 요청에 방향값이 없으면 `"UNKNOWN"`
- 기기 오프라인이면 명령은 드롭 (웹앱 알림·감지 기록은 정상 진행)
