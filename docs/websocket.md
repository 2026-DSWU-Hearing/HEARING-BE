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

# WebSocket: 실시간 소리 감지 (livesound)

```text
ws://localhost:8000/ws/users/me/livesound?token={accessToken}
```

클라이언트(웹/iOS/Android) **마이크**로 주변 소리를 듣고 지금 뭐가 몇 % 들리는지 보여주는
화면 전용 채널. 위의 detections 채널과 **완전히 별개**다.

- 모드·필터링·방해금지를 적용하지 않는다 — 들리는 건 전부 돌려준다.
- 알림 저장·FCM·진동이 **없다**. 사용자가 직접 켠 화면일 뿐이라 넥밴드/모드 상태를 건드리지 않는다.
- 서버는 AI 분석 서버(`AI_SERVER_WS_URL`, 기본 `ws://localhost:8001/ws/analyze`)로 릴레이만 한다.

## Auth

detections 채널과 동일 — query string `token`, 실패 시 close code `4401`.

## 흐름

| 방향 | 메시지 |
| --- | --- |
| C→S | `{"type":"start","sample_rate":16000,"channels":1,"format":"pcm_s16le"}` |
| S→C | `{"type":"ready"}` |
| C→S | **바이너리** PCM 조각 (권장 100ms 단위) |
| S→C | `{"type":"classification","data":{...}}` — 1초마다 반복 |
| C→S | `{"type":"stop"}` 또는 close |
| S→C | `{"type":"error","code":"...","message":"..."}` |

## 오디오 포맷 (필수)

**PCM signed int16 little-endian, mono, 16kHz.** 서버가 100ms 조각을 모아 1초 창(32,000 바이트)을
만들어 분석기에 넘긴다 — YAMNet 이 최소 15,600 샘플을 요구하기 때문.

`start` 에서 포맷을 선언받아 검증한다. 48kHz 를 그대로 보내면 소리가 느리게 해석돼
**에러 없이 분류 결과만 조용히 망가지므로** 여기서 끊는다(`INVALID_START`).

## classification

```json
{
  "type": "classification",
  "data": {
    "sounds": [
      { "sound_id": 17, "sound_name": "경적", "sound_category": "교통", "confidence": 0.82 },
      { "sound_id": null, "sound_name": "미등록소리", "sound_category": "동물", "confidence": 0.11 }
    ],
    "analyzed_at": "2026-08-09T12:34:56+00:00"
  }
}
```

- 소리 필드명은 detections 채널·`POST /devices/{id}/detections` 와 **동일하다**
  (`sound_id` / `sound_name` / `sound_category` / `confidence`). 클라이언트가 두 채널의
  타입을 섞어 써도 조용히 깨지지 않게 하기 위한 것이다.
- `confidence` 는 **0~1 실수**. 화면 %는 클라이언트가 환산한다.
- `sound_id` 는 이름이 소리 카탈로그에 있을 때만 채워지고, 없으면 `null`.
  **클라이언트는 `null` 을 견뎌야 한다** — AI 가 이름을 하나 추가·변경하면 바로 나온다.
  `sound_id` 가 없다고 그 항목이나 스냅샷을 버리면 화면이 통째로 멈춘다(표시에 필요한 건
  `sound_name`/`confidence` 뿐이다). 목록 key 는 `sound_category` + `sound_name` 조합을 쓴다 —
  `충돌·파손음` 처럼 카테고리가 둘인 이름은 한 스냅샷에 **함께** 올 수 있어 이름만으로는 겹친다.
- 임계값 컷을 하지 않으므로 낮은 신뢰도도 그대로 담긴다.
- 아무것도 안 잡히면 `"sounds": []`.

## error 코드

| code | 상황 |
| --- | --- |
| `INVALID_START` | 첫 메시지가 start 가 아니거나 포맷(샘플레이트/채널)이 규격과 다름 |
| `ANALYZER_UNAVAILABLE` | AI 분석 서버에 못 붙었거나 세션 도중 끊김 |

AI 서버 접속은 **2초**(`AI_CONNECT_TIMEOUT_SECONDS`) 안에 끝내고, 실패하면 곧바로
`ANALYZER_UNAVAILABLE` 을 보낸다. 클라이언트가 `ready` 를 기다리는 시간(FE 기준 5초)보다
짧아야 안내 문구가 먼저 도착한다. 세션 도중 왕복은 별도로 `AI_ANALYZE_TIMEOUT_SECONDS`(5초).

## AI 분석 서버 응답 계약 (`AI_SERVER_WS_URL`)

서버가 1초 PCM(32,000 바이트) 1프레임을 보내면 AI 가 JSON 1건으로 답한다(요청-응답 1:1).

```json
{ "status": "ok", "top_sounds": [{ "category": "교통", "block": "경적", "score": 0.82 }] }
```

- **`status` 는 필수다.** 분석 실패도 `top_sounds` 를 `[]` 로 함께 보내기 때문에,
  `status` 를 보지 않으면 **'분석 실패'와 '조용해서 잡힌 게 없음'이 화면에서 똑같아진다.**
  `"ok"` 가 아니면(키가 없는 경우 포함) 실패로 보고 세션을 접는다 → `ANALYZER_UNAVAILABLE`.
- `"status":"ok"` + `"top_sounds":[]` 는 **정상 무음**이다. 그대로 `"sounds": []` 로 클라이언트에 나간다.
- `top_sounds[]` 는 `category`(한글 카테고리) / `block`(한글 소리 이름) / `score`(0~1) 를 쓴다.
  `block` → `sound_name`, `category` → `sound_category`, `score` → `confidence` 로 옮긴다.
- 카탈로그 조회는 **`(category, block)` 쌍**으로 한다 — `충돌·파손음` 처럼 카테고리가 둘인
  이름이 있어 이름만으로 찾으면 한쪽이 다른 쪽 `sound_id` 를 물고 나간다.

## 백프레셔

분석이 밀리면 **가장 최신 창만 남기고 오래된 창은 버린다.** 큐를 쌓으면 화면이 몇 초씩
뒤처지고 중지를 눌러도 결과가 계속 올라온다.

# WebSocket: 하드웨어(ESP32) 상태/명령 채널

Local:

```text
ws://localhost:8000/ws/devices?token={deviceToken}&mac={macAddress}
```

## Auth / 바인딩

- `token`: 장수명 디바이스 토큰 (`python scripts/make_device_token.py` 로 발급, source="device").
  '정품 기기' 증명용 — 어느 기기인지는 MAC 으로 정해진다.
- `mac`: 기기 실제 MAC (`44:1B:F6:D4:47:F0` = 서버 설정 `DEVICE_MAC_ADDRESS`).
  대소문자·공백 무관(서버 설정·접속 양쪽 모두 정규화).
  **물리 기기는 1대, DB 행도 1개**다. 이 WS 는 그 행의 연결 상태를 갱신할 뿐이고,
  누가 알림·진동을 받는지는 웹앱의 [기기 연결] 버튼(`POST /devices/connect`)이 정한다
  — 하드웨어가 접속해 있어야 그 버튼이 성공한다(미접속이면 409 즉시 실패).
- close 코드: 토큰 불량 `4401` · 서버 설정과 다른 MAC `4404` · 같은 기기 재접속 시 기존 연결 `4409` 후 교체.
  거절 시에도 핸드셰이크는 수락된 직후 닫히므로 클라이언트는 close 코드로 원인을 구분할 수 있음.

## 수명주기 → DB (FE 는 GET /devices 폴링으로 자동 반영)

- 접속: `is_connected=true`, `last_seen_at` 갱신
- 해제: `is_connected=false`
- 서버 기동 시 `is_connected=false` 리셋 (WS 는 재시작을 살아남지 못하므로)
- `is_connected` 의 진실 원천은 이 수명주기뿐 — `PATCH /devices/{id}` 는 닉네임(계정별 기기 이름)만
  받고 `is_connected`/`battery_level` 필드는 무시된다 (과거 '유령 연결' 원인 제거)
- `DELETE /devices/{id}` 는 "내 계정에서 연결 해제"(active 포인터 해제)일 뿐 — 이 WS 는 닫히지 않는다

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

- `strength`: **현재 사용자(active user)** 의 진동 세기 설정 (`users.haptic_strength`, 0~100)
- `direction`: 소리가 감지된 방향 (`"FRONT" | "BACK" | "LEFT" | "RIGHT" | "UNKNOWN"`)
  - 감지 요청에 방향값이 없으면 `"UNKNOWN"`
- 기기 오프라인이면 명령은 드롭 (웹앱 알림·감지 기록은 정상 진행)
