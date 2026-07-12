"""하드웨어(ESP32)용 장수명 디바이스 토큰 발급.

용도: 기기 WS 접속 ws://{host}/ws/devices?token={출력값}&mac={기기 MAC}
토큰은 '정품 기기' 증명용이고 어느 기기인지는 MAC 으로 정해지므로,
기기를 삭제/재등록해도 토큰은 그대로 유효하다. 하드웨어 팀에 펌웨어 설정값으로 전달.

실행:
  python scripts/make_device_token.py            # 기본 365일
  python scripts/make_device_token.py --days 730
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (어느 cwd에서 실행해도 app 패키지를 찾도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import create_device_token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="디바이스 토큰 발급")
    parser.add_argument("--days", type=int, default=365, help="만료(일), 기본 365")
    args = parser.parse_args()
    print(create_device_token(days=args.days))


if __name__ == "__main__":
    main()
