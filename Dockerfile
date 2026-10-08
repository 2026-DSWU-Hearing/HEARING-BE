# HEARING-BE 운영 이미지. deploy/docker-compose.prod.yml 이 빌드한다 (deploy/README.md 참고).
#
# - 설정은 전부 환경변수로 받는다(compose 의 env_file). .env 와 firebase-credentials.json 은
#   .dockerignore 로 이미지에서 제외 — 비밀은 이미지에 굽지 않고 실행 시점에 주입한다.
# - nginx 뒤에서 돈다. --proxy-headers 가 없으면 모든 요청의 클라이언트 IP 가 nginx 주소로 보여
#   게스트 로그인 rate limit(IP 당 10회/시간)이 전체 사용자에게 한 덩어리로 걸린다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성 레이어를 소스와 분리 — 코드만 바뀐 배포는 pip 를 다시 돌지 않는다.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

# 마이그레이션은 기동과 분리한다: docker compose run --rm backend alembic upgrade head
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
