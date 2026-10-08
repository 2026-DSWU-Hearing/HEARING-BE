# HEARING-MODEL(AI 분석 서버) 운영 이미지.
#
# 이 파일의 주인은 MODEL 레포다 — 그쪽 루트에 `Dockerfile` 로 들어가면 compose 의
# `dockerfile:` 지정을 지우고 기본값을 쓰면 된다. MODEL 레포에 아직 없어서 임시로 여기 둔다.
# 빌드 컨텍스트는 HEARING-MODEL 체크아웃 루트(COPY 경로가 그 기준).
#
# - Python 3.11: MODEL README 요구 버전.
# - setuptools<81: tensorflow_hub 가 pkg_resources 를 아직 쓰는데 81 에서 제거됨(로컬 셋업과 동일).
# - TFHUB_CACHE_DIR: classifier 가 기동 때 tfhub.dev 에서 YAMNet 을 내려받는다. 기본 캐시는 /tmp 라
#   컨테이너를 다시 만들 때마다 재다운로드 — compose 가 이 경로를 볼륨으로 붙여 한 번만 받게 한다.
# - run.py 로 기동: ws ping 비활성(ESP32 는 ping 프레임에 응답하지 않음)이 거기 들어 있다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    TFHUB_CACHE_DIR=/cache/tfhub

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt && pip install "setuptools<81"

COPY app ./app
COPY run.py .

EXPOSE 8765

CMD ["python", "run.py"]
