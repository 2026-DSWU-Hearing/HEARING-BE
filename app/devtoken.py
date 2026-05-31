"""개발용 JWT 액세스 토큰 발급기 (로그인 미구현 동안 흐름 A 테스트용).

DB 없이 토큰만 찍어준다. 사용자/소리 데이터가 필요하면 `python -m app.devinit` 먼저 실행.

사용:
  python -m app.devtoken              # user_id=1, source=user (앱 API 호출용)
  python -m app.devtoken 1 device     # 웨어러블 감지 POST 테스트용 (source=device)
  python -m app.devtoken 1 ai-server  # HEARING-AI-SE 감지 POST 테스트용
"""

import sys

from app.core.security import create_access_token


def main() -> None:
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    source = sys.argv[2] if len(sys.argv) > 2 else "user"
    token = create_access_token(user_id, source=source)
    print(token)
    print()
    print(f"Authorization: Bearer {token}")


if __name__ == "__main__":
    main()
