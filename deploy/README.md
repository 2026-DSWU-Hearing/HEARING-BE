# 배포 (AWS: EC2 + RDS, FE 는 S3/CloudFront)

EC2 한 대에 Docker Compose 로 `nginx / backend / ai(HEARING-MODEL) / redis` 를 올리고,
PostgreSQL 은 RDS 를 쓴다. 이 디렉터리의 파일:

| 파일 | 역할 |
| --- | --- |
| `docker-compose.prod.yml` | 운영 스택 정의. 항상 `-f deploy/docker-compose.prod.yml` 로 지정 |
| `nginx/default.conf.template` | TLS 종단 + WebSocket 프록시. `${API_DOMAIN}` 만 기동 때 치환 |
| `example.env` | compose 변수(`API_DOMAIN`). `deploy/.env` 로 복사 |
| `../Dockerfile` | 백엔드 이미지. AI 서버 이미지는 MODEL 레포 루트의 `Dockerfile` |

## 전제

- **도메인 + HTTPS 필수.** PWA 서비스워커·FCM·마이크(livesound)는 HTTPS 에서만 동작하고,
  Let's Encrypt 는 EC2 기본 주소(amazonaws.com)에 인증서를 내주지 않는다.
  `api.<도메인>` → EC2, `app.<도메인>` → CloudFront(FE). 백엔드 API 가 루트 경로라 FE 와 같은 호스트에 둘 수 없다.
- **EC2 는 t3.small(2GB) 이상, 여유 있게 t3.medium(4GB).** AI 컨테이너는 YAMNet 로드 직후 유휴 약 400MB,
  TensorFlow 이미지 3.3GB — t3.micro(1GB)는 스왑 없이는 버티지 못한다.
  Ubuntu 24.04, 서울 리전. 보안 그룹 인바운드: 22(내 IP), 80, 443. 탄력적 IP 를 붙인다.
- **RDS PostgreSQL 16**, 퍼블릭 액세스 없음, 초기 DB 이름 `hearing`, 보안 그룹 5432 는 EC2 보안 그룹에서만.
  PG16 RDS 는 SSL 강제가 기본이라 접속 URL 끝에 **`?ssl=require`** 가 꼭 들어간다.

## 서버 디렉터리 배치

compose 의 상대 경로가 이 배치를 전제한다.

```text
~/hearing/
├── HEARING-BE/        ← 이 레포
│   ├── .env                        백엔드 운영 설정 (git 제외)
│   ├── firebase-credentials.json   FCM 서비스 계정 키 (git 제외)
│   └── deploy/.env                 API_DOMAIN (git 제외)
└── HEARING-MODEL/     ← AI 서버 레포 (형제 디렉터리)
    └── .env                        BACKEND_URL / JWT_SECRET / DEVICE_ID (git 제외)
```

## 절차

### 1. EC2 초기 설정

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 certbot git
sudo usermod -aG docker ubuntu        # 적용하려면 재로그인
mkdir -p ~/hearing && cd ~/hearing
git clone https://github.com/2026-DSWU-Hearing/HEARING-BE.git
git clone https://github.com/2026-DSWU-Hearing/HEARING-MODEL.git
```

### 2. 설정 파일

```bash
cd ~/hearing/HEARING-BE
cp example.env .env && nano .env           # 아래 값들
cp deploy/example.env deploy/.env && nano deploy/.env   # API_DOMAIN=api.<도메인>
cp ../HEARING-MODEL/example.env ../HEARING-MODEL/.env && nano ../HEARING-MODEL/.env
```

`HEARING-BE/.env` 에서 바꿀 값 (컨테이너끼리는 서비스 이름으로 통신 — `localhost` 아님):

```ini
ENVIRONMENT=prod
DATABASE_URL=postgresql+asyncpg://<마스터계정>:<비밀번호>@<RDS 엔드포인트>:5432/hearing?ssl=require
REDIS_URL=redis://redis:6379/0
JWT_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(64))">
GOOGLE_CLIENT_ID=<웹 클라이언트 ID>
AI_SERVER_WS_URL=ws://ai:8765/ws/analyze     # 기본값은 8001 포트라 반드시 적는다
CORS_ORIGINS=["https://app.<도메인>"]
DEV_AUTH_BYPASS=false                        # prod 에서 true 면 기동 거부
RTZR_CLIENT_ID=...
RTZR_CLIENT_SECRET=...
```

`HEARING-MODEL/.env`:

```ini
BACKEND_URL=http://backend:8000
JWT_SECRET=<백엔드와 같은 값>      # AI 서버가 이 키로 ai-server 토큰을 서명한다
DEVICE_ID=1
```

FCM 키는 git 에 없으므로 내 PC 에서 올린다. **compose 를 띄우기 전에** 있어야 한다
(없으면 도커가 그 경로에 빈 디렉터리를 만들어 버린다).

```bash
scp -i key.pem firebase-credentials.json ubuntu@<EC2 IP>:~/hearing/HEARING-BE/
```

### 3. 인증서

DNS 에 `api.<도메인>` A 레코드가 EC2 탄력적 IP 를 가리킨 뒤, nginx 가 아직 80 번을 안 잡고 있을 때:

```bash
sudo certbot certonly --standalone -d api.<도메인>
```

갱신은 certbot 의 systemd 타이머가 자동으로 돌린다. standalone 은 80 번이 비어 있어야 하므로
갱신 전후에 nginx 를 잠깐 내렸다 올리는 훅을 넣어 둔다 (훅 디렉터리의 스크립트는 `certbot renew` 가 자동 실행):

```bash
sudo tee /etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh >/dev/null <<'EOF'
#!/bin/sh
docker compose -f /home/ubuntu/hearing/HEARING-BE/deploy/docker-compose.prod.yml stop nginx
EOF
sudo tee /etc/letsencrypt/renewal-hooks/post/start-nginx.sh >/dev/null <<'EOF'
#!/bin/sh
docker compose -f /home/ubuntu/hearing/HEARING-BE/deploy/docker-compose.prod.yml start nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh /etc/letsencrypt/renewal-hooks/post/start-nginx.sh
sudo certbot renew --dry-run
```

### 4. 빌드 → 마이그레이션 → 기동

운영에서는 `app.devinit` 을 쓰지 않는다(개발 유저·토큰 시드용). 스키마와 소리 카탈로그는 alembic 이,
물리 기기 행은 백엔드 기동 시 `ensure_physical_device` 가 만든다.

```bash
cd ~/hearing/HEARING-BE
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f deploy/docker-compose.prod.yml up -d
docker compose -f deploy/docker-compose.prod.yml logs -f backend ai
```

확인:

```bash
curl https://api.<도메인>/health          # {"status":"ok"}
# 하드웨어 소켓: 로컬처럼 scripts/make_device_token.py 로 토큰을 만들어
#   wss://api.<도메인>/ws/devices?token=<토큰>&mac=<MAC>  에 wscat 으로 붙어 본다.
```

### 5. 코드 갱신

```bash
cd ~/hearing/HEARING-BE && git pull && (cd ../HEARING-MODEL && git pull)
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml run --rm backend alembic upgrade head   # 마이그레이션 없으면 no-op
docker compose -f deploy/docker-compose.prod.yml up -d
```

백엔드만 재시작하면 넥밴드 연결 상태는 리셋되고(설계대로) 넥밴드가 재접속한다.

## FE (S3 + CloudFront)

1. FE 레포 `.env.production`: `VITE_APP_BASE_URL=https://api.<도메인>` (+ VAPID 키, Google 클라이언트 ID).
   WS 주소는 FE 가 이 값의 `http` 를 `ws` 로 바꿔 쓰므로 자동으로 `wss` 가 된다.
2. `pnpm build` → `dist/`.
3. S3 버킷: 퍼블릭 액세스 차단 해제, 정적 웹 호스팅 ON, 인덱스·오류 문서 모두 `index.html`,
   버킷 정책으로 `s3:GetObject` 퍼블릭 읽기.
4. CloudFront: 원본 = S3 웹사이트 엔드포인트, 대체 도메인 `app.<도메인>`, 인증서는 **버지니아 북부(us-east-1)** ACM,
   오류 페이지 403/404 → `/index.html` 200 (SPA 라우팅). DNS 에 `app.<도메인>` CNAME → CloudFront 도메인.
5. 배포: `aws s3 sync dist s3://<버킷> --delete && aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"`

CloudFront 를 못 쓰면 `nginx/default.conf.template` 에 `app.<도메인>` server 블록을 추가해 `dist/` 를
`try_files $uri /index.html` 로 서빙하고, certbot 에 `-d app.<도메인>` 을 추가한다.

## 외부 서비스

- Google Cloud Console OAuth 클라이언트 → 승인된 JavaScript 원본에 `https://app.<도메인>`.
- Firebase 콘솔 → Authentication 승인된 도메인에 `app.<도메인>`.
- HW 팀: 넥밴드 접속 주소 `wss://api.<도메인>/ws/neckband`(오디오), `wss://api.<도메인>/ws/devices`(상태·진동).
  ESP32 에서 TLS 가 어려우면 템플릿 끝의 평문 8080 블록을 임시로 쓴다.

## 운영 메모

- `Dockerfile` 의 `--proxy-headers --forwarded-allow-ips=*` 를 빼면 게스트 로그인 rate limit 이 전체 사용자에게
  한 덩어리로 걸린다(모든 요청이 nginx IP 로 보임).
- Redis 는 TTL 임시 데이터만 있어 볼륨이 없다. 재시작하면 비워지는 게 정상.
- `.env`·`firebase-credentials.json` 은 scp 로만 옮긴다. 레포가 public 이라 커밋되면 키를 전부 폐기해야 한다.
- RDS 자동 백업 보존 7일을 켜 두면 시점 복구가 된다. 탄력적 IP 는 인스턴스를 중지해 두면 과금된다.
