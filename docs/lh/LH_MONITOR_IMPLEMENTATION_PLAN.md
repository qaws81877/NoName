# LH 임대주택 공고 모니터링 봇 - 구현계획서

> **문서 목적**: AI 에이전트가 이 문서를 읽고 독립적으로 프로젝트를 구현할 수 있도록 작성된 구현계획서입니다.
> **최종 수정일**: 2025-02-19
> **프로젝트 코드명**: `lh-monitor`

---

## 1. 프로젝트 개요

### 1.1 목적

한국토지주택공사(LH) 청약센터의 **임대주택 공고**를 자동으로 모니터링하여, 새로운 공고가 등록되면 **Telegram**과 **Discord**로 실시간 알림을 발송하는 Python 봇을 개발한다.

### 1.2 핵심 요구사항

- LH 청약센터(`apply.lh.or.kr`) 임대주택 공고를 **30분 간격**으로 자동 확인
- 새 공고 발견 시 **Telegram Bot API** + **Discord Webhook**으로 동시 알림
- 매일 21시에 **일일 요약 리포트** 자동 발송
- **공공데이터포털 API** 우선 사용, 실패 시 **웹 크롤링**으로 자동 폴백
- Docker 기반 **VPS 배포** 지원
- 최초 실행 시 기존 공고는 기록만 하고 알림을 보내지 않음 (중복 알림 방지)

### 1.3 대상 사용자

- 1~2명의 개인 사용자 (개발자 본인)

### 1.4 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| HTTP | `requests` |
| 파싱 | `beautifulsoup4` |
| 환경변수 | `python-dotenv` |
| 컨테이너 | Docker + Docker Compose |
| 데이터 저장 | JSON 파일 (SQLite 불필요) |

---

## 2. 아키텍처

### 2.1 시스템 구조

```
┌─────────────────────────────────────────────────┐
│                  LHMonitor (메인)                 │
│                                                   │
│  ┌───────────┐    ┌──────────┐    ┌───────────┐  │
│  │ LHCrawler │───▶│ DataStore│───▶│ Notifiers │  │
│  │           │    │ (JSON)   │    │ TG + DC   │  │
│  └─────┬─────┘    └──────────┘    └───────────┘  │
│        │                                          │
│  ┌─────┴──────────────────┐                       │
│  │ 데이터 소스 (우선순위)   │                       │
│  │ 1. 공공데이터포털 API   │                       │
│  │ 2. LH 내부 JSON API    │                       │
│  │ 3. HTML 크롤링 (폴백)   │                       │
│  └────────────────────────┘                       │
│                                                   │
│  ┌──────────────┐                                 │
│  │ DailySummary │ ← 매일 21시 자동 발송            │
│  └──────────────┘                                 │
└─────────────────────────────────────────────────┘
```

### 2.2 디렉토리 구조

```
lh-monitor/
├── lh_monitor.py          # 메인 봇 (단일 파일)
├── .env                   # 환경변수 설정
├── .env.example           # 환경변수 템플릿
├── requirements.txt       # Python 의존성
├── Dockerfile             # Docker 이미지
├── docker-compose.yml     # Docker Compose 배포
├── README.md              # 사용 설명서
└── data/                  # 자동 생성 - 런타임 데이터
    ├── seen.json          # 이미 확인한 공고 ID 목록
    └── daily_summary.json # 일일 요약 데이터
```

> **중요**: 이 프로젝트는 **단일 파일(`lh_monitor.py`)** 구조입니다. 모든 클래스를 하나의 파일에 작성하세요. 모듈 분리하지 마세요.

---

## 3. 데이터 소스 상세

### 3.1 공공데이터포털 API (1순위)

- **엔드포인트**: `http://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1`
- **인증**: `ServiceKey` 파라미터 (공공데이터포털에서 발급)
- **응답 형식**: JSON
- **요청 파라미터**:

```
ServiceKey: (API 인증키)
pageNo: 1
numOfRows: 30
type: json
```

- **응답 구조**:

```json
{
  "response": {
    "body": {
      "items": {
        "item": [
          {
            "sn": "공고번호",
            "sj": "공고제목",
            "typeCdNm": "임대유형명",
            "crtDt": "등록일",
            "rceptBgnDt": "접수시작일",
            "rceptEndDt": "접수종료일",
            "dtlUrl": "상세URL"
          }
        ]
      }
    }
  }
}
```

- **주의**: `items.item`이 단일 객체일 수 있음 → 항상 리스트로 변환 처리

### 3.2 LH 내부 JSON API (2순위)

- **엔드포인트**: `https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancListJson.do`
- **메서드**: POST
- **요청 파라미터** (form data):

```
pg: 1
pgSz: 30
uppAisTpCd: 13   (임대주택 카테고리)
```

- **응답 필드 매핑** (대소문자 두 가지 모두 처리할 것):

| 필드 | 설명 |
|------|------|
| `panId` / `PAN_ID` | 공고 고유 ID |
| `panNm` / `PAN_NM` | 공고 제목 |
| `aisTpCd` / `AIS_TP_CD` | 임대유형 코드 |
| `panSttNm` / `PAN_STT_NM` | 공고 상태명 |
| `dttmRgst` / `DTTM_RGST` | 등록일시 |
| `clsgBgnDt` / `CLSG_BGN_DT` | 접수시작일 |
| `clsgEndDt` / `CLSG_END_DT` | 접수종료일 |

- **응답 리스트 키**: `dsList` 또는 `list` (둘 다 시도)

### 3.3 HTML 크롤링 (3순위 - 최종 폴백)

- **URL**: `https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026`
- **파싱 대상**: `table tbody tr` 또는 `.board-list tbody tr`, `.tbl_list tbody tr`
- **각 행에서 추출**:
  - `<a>` 태그의 `href`에서 `panId` 파라미터 추출
  - `href`가 JavaScript 함수 호출인 경우, 정규식으로 숫자 ID 추출: `re.search(r"['\"](\d+)['\"]", href)`
  - panId를 추출하지 못할 경우, 제목의 MD5 해시 앞 16자를 ID로 사용
  - `<td>` 컬럼들에서 임대유형, 날짜, 상태 추출

### 3.4 데이터 소스 폴백 전략

```
if 공공데이터 API 키 설정됨:
    결과 = 공공데이터포털 API 호출
    if 결과 비어있음:
        결과 = LH 웹 크롤링 (JSON API → HTML 폴백)
else:
    결과 = LH 웹 크롤링 (JSON API → HTML 폴백)
```

---

## 4. 클래스 설계

### 4.1 DataStore

**역할**: 이미 확인한 공고 ID를 JSON 파일로 관리하여 중복 알림 방지

```python
class DataStore:
    filepath: str          # JSON 파일 경로
    data: dict             # {"seen_ids": [...], "last_check": "ISO datetime"}

    def is_new(ann_id: str) -> bool      # 새 공고인지 확인
    def mark_seen(ann_id: str)           # 확인한 공고로 기록
    def update_check_time()              # 마지막 체크 시간 갱신 + 저장
    def save()                           # JSON 파일에 저장
```

- `seen_ids`는 최대 **500개**만 유지 (오래된 것 자동 삭제)
- `save()`는 `update_check_time()` 호출 시에만 실행 (불필요한 I/O 방지)

### 4.2 LHCrawler

**역할**: 3개 데이터 소스에서 공고 목록을 수집하여 통일된 형식으로 반환

```python
class LHCrawler:
    session: requests.Session    # 헤더가 설정된 세션

    def fetch_web() -> list[dict]                # LH 사이트 크롤링 (JSON API → HTML 폴백)
    def fetch_api(api_key: str) -> list[dict]    # 공공데이터포털 API 조회
```

**반환 데이터 형식** (모든 메서드 동일):

```python
{
    "id": str,              # 공고 고유 ID
    "title": str,           # 공고 제목
    "rental_type": str,     # 임대유형 (국민임대, 행복주택 등)
    "status": str,          # 상태 (접수중, 접수예정, 접수마감 등)
    "reg_date": str,        # 공고일 (YYYY-MM-DD)
    "rcpt_begin": str,      # 접수시작일
    "rcpt_end": str,        # 접수종료일
    "url": str,             # 공고 상세 페이지 URL
}
```

**HTTP 요청 헤더** (반드시 설정):

```python
{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://apply.lh.or.kr",
}
```

**임대유형 코드 매핑**:

```python
RENTAL_TYPES = {
    "01": "국민임대", "02": "공공임대", "03": "영구임대",
    "04": "행복주택", "05": "장기전세", "06": "공공지원민간임대",
    "07": "통합공공임대", "08": "전세임대", "09": "매입임대", "10": "기타",
}
```

**날짜 정규화 함수**: `"20250219"` → `"2025-02-19"`, `"2025/02/19"` → `"2025-02-19"`

### 4.3 TelegramNotifier

**역할**: Telegram Bot API를 통해 알림 메시지 발송

```python
class TelegramNotifier:
    token: str
    chat_id: str
    enabled: bool          # token과 chat_id 모두 있으면 True

    def send(announcements: list[dict])     # 공고별 개별 메시지 발송
    def send_text(text: str)                # 텍스트 직접 발송 (일일 요약용)
```

**API 호출**:

```
POST https://api.telegram.org/bot{TOKEN}/sendMessage
Body (JSON):
{
    "chat_id": CHAT_ID,
    "text": 메시지,
    "parse_mode": "HTML"
}
```

**메시지 포맷**:

```
🏠 <b>LH 임대주택 새 공고</b>

📋 <b>{공고제목}</b>
🏷 유형: {임대유형}
🟢 상태: {접수상태}
📅 공고일: {날짜}
📆 접수: {시작일} ~ {종료일}

🔗 <a href="{URL}">공고 상세보기</a>
```

- 공고 간 발송 간격: **0.5초** (Telegram rate limit 방지)

### 4.4 DiscordNotifier

**역할**: Discord Webhook을 통해 Embed 형식 알림 발송

```python
class DiscordNotifier:
    webhook_url: str
    enabled: bool

    def send(announcements: list[dict])     # 공고별 Embed 발송
    def send_embed(embed: dict)             # Embed 직접 발송 (일일 요약용)
```

**API 호출**:

```
POST {WEBHOOK_URL}
Body (JSON):
{
    "embeds": [{
        "title": "🏠 {공고제목}",
        "url": "{공고URL}",
        "color": 0x00FF00,       // 상태별 색상
        "fields": [
            {"name": "🏷 임대유형", "value": "행복주택", "inline": true},
            {"name": "🟢 상태", "value": "접수중", "inline": true},
            {"name": "📅 공고일", "value": "2025-02-19", "inline": true},
            {"name": "📆 접수기간", "value": "시작일 ~ 종료일", "inline": false}
        ],
        "footer": {"text": "LH 임대주택 공고 모니터링"},
        "timestamp": "ISO8601"
    }]
}
```

**상태별 Embed 색상**:

| 상태 | 색상코드 | 아이콘 |
|------|----------|--------|
| 접수중 / 공고중 | `0x00FF00` (초록) | 🟢 |
| 접수예정 | `0x0099FF` (파랑) | 🔵 |
| 접수마감 | `0xFF0000` (빨강) | 🔴 |
| 기타 | `0x808080` (회색) | ⚪ |

- 발송 간격: **0.5초**, 성공 응답: `200` 또는 `204`

### 4.5 DailySummary

**역할**: 하루 동안 발견된 새 공고를 모아서 일일 요약 리포트 생성

```python
class DailySummary:
    filepath: str
    data: dict             # {"date": "2025-02-19", "announcements": [...]}

    def add(ann: dict)                          # 새 공고 추가 (날짜 바뀌면 자동 리셋)
    def get_tg_msg() -> Optional[str]           # Telegram 요약 메시지 생성
    def get_dc_embed() -> Optional[dict]        # Discord 요약 Embed 생성
```

- 날짜가 바뀌면 `announcements` 자동 초기화
- 공고가 없으면 `None` 반환 (요약 발송 안 함)

### 4.6 LHMonitor (메인)

**역할**: 전체 모니터링 루프 관리

```python
class LHMonitor:
    store: DataStore
    crawler: LHCrawler
    tg: TelegramNotifier
    dc: DiscordNotifier
    summary: DailySummary
    use_api: bool          # 공공데이터 API 키 존재 여부

    def check_once() -> list[dict]    # 한 번 체크 + 알림
    def send_daily_summary()          # 일일 요약 발송
    def run()                         # 메인 무한 루프
```

---

## 5. 핵심 로직 흐름

### 5.1 메인 루프 (`run`)

```
1. 시작 로그 출력 (간격, 알림 채널 활성 상태, 데이터 소스 방식)
2. Telegram/Discord 중 하나도 설정 안 됐으면 에러 로그 + 종료
3. 최초 실행 판단 (last_check 없으면):
   a. 기존 공고 전부 fetch → 모든 ID를 mark_seen
   b. 알림은 보내지 않음 (중복 방지)
4. 최초가 아닌 경우:
   a. check_once() 실행
5. 무한 루프 시작:
   a. CHECK_INTERVAL 만큼 sleep
   b. check_once() 실행
   c. 현재 시간이 21시이고 오늘 요약을 아직 안 보냈으면:
      → send_daily_summary() 실행
   d. KeyboardInterrupt → 종료
   e. 기타 예외 → 에러 로그 + 60초 대기 후 계속
```

### 5.2 단일 체크 (`check_once`)

```
1. 공고 목록 수집 (폴백 전략 적용)
2. 각 공고에 대해:
   a. store.is_new(id) 확인
   b. 새 공고면 → new 리스트에 추가 + mark_seen + summary.add
3. store.update_check_time()
4. 새 공고가 있으면:
   a. Telegram 알림 발송
   b. Discord 알림 발송
5. 새 공고 리스트 반환
```

---

## 6. 환경변수 설정

| 변수명 | 필수 | 기본값 | 설명 |
|--------|------|--------|------|
| `TELEGRAM_BOT_TOKEN` | △ | `""` | Telegram 봇 토큰 (@BotFather 발급) |
| `TELEGRAM_CHAT_ID` | △ | `""` | Telegram 채팅방 ID |
| `DISCORD_WEBHOOK_URL` | △ | `""` | Discord 웹훅 URL |
| `DATA_GO_KR_API_KEY` | ✕ | `""` | 공공데이터포털 API 인증키 |
| `CHECK_INTERVAL` | ✕ | `1800` | 체크 간격 (초) |
| `DATA_DIR` | ✕ | `./data` | 데이터 저장 디렉토리 경로 |

> △ = Telegram/Discord 중 **최소 하나**는 필수

---

## 7. Docker 배포

### 7.1 Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lh_monitor.py .
COPY .env .
RUN mkdir -p /app/data
CMD ["python", "-u", "lh_monitor.py"]
```

- `-u` 플래그: 파이썬 출력 버퍼링 비활성화 (Docker 로그 실시간 확인용)

### 7.2 docker-compose.yml

```yaml
version: '3.8'

services:
  lh-monitor:
    build: .
    container_name: lh-monitor
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env
    environment:
      - TZ=Asia/Seoul
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### 7.3 배포 명령어

```bash
# 빌드 + 백그라운드 실행
docker-compose up -d --build

# 로그 확인
docker-compose logs -f lh-monitor

# 중지
docker-compose down

# 재시작
docker-compose restart
```

---

## 8. 에러 처리 규칙

1. **네트워크 오류**: `requests.RequestException` 캐치 → 에러 로그 → 다음 주기에 재시도
2. **JSON 파싱 오류**: `json.JSONDecodeError` 캐치 → 다음 데이터 소스로 폴백
3. **알림 발송 실패**: 로그만 남기고 계속 진행 (봇이 죽지 않도록)
4. **메인 루프 예외**: 에러 로그 + 60초 대기 후 루프 재개
5. **모든 HTTP 요청**: `timeout=30` (크롤링), `timeout=10` (알림)

---

## 9. 로깅 설정

- **파일**: `lh_monitor.log` (UTF-8)
- **콘솔**: 표준 출력
- **레벨**: INFO
- **포맷**: `%(asctime)s [%(levelname)s] %(message)s`

### 주요 로그 메시지

```
시작:     🏠 LH 임대주택 공고 모니터링 봇 시작
간격:     ⏱  간격: 1800초 (30분)
채널:     📬 TG: ✅  DC: ✅
방식:     🔑 방식: 웹크롤링
수집:     JSON API: 25개 수집
새공고:   🆕 새 공고 3건!
전송:     TG ✅ 파주운정2단지 국민임대...
없음:     새 공고 없음
종료:     ⛔ 종료
```

---

## 10. 구현 시 주의사항

### 10.1 반드시 지킬 것

- [ ] 단일 파일 구조 유지 (`lh_monitor.py` 하나에 모든 클래스)
- [ ] 최초 실행 시 알림 보내지 않기 (기존 공고 기록만)
- [ ] 모든 HTTP 요청에 timeout 설정
- [ ] Telegram/Discord 발송 사이 0.5초 sleep (rate limit)
- [ ] JSON API 필드명 대소문자 두 가지 모두 처리 (`panId` / `PAN_ID`)
- [ ] `items.item`이 dict일 수 있으므로 list 변환 처리
- [ ] 환경변수가 없어도 크래시하지 않기 (빈 문자열 기본값)
- [ ] `seen_ids` 최대 500개 유지
- [ ] 날짜 정규화 처리 (`20250219` → `2025-02-19`)
- [ ] Docker 타임존 `Asia/Seoul` 설정

### 10.2 하지 말 것

- [ ] 파일을 여러 모듈로 분리하지 않기
- [ ] 데이터베이스(SQLite, PostgreSQL 등) 사용하지 않기
- [ ] async/await 사용하지 않기 (단순 time.sleep 루프)
- [ ] 외부 스케줄러(APScheduler, cron 등) 사용하지 않기
- [ ] Selenium/Playwright 같은 브라우저 자동화 사용하지 않기
- [ ] LH 서버에 과도한 요청 보내지 않기 (30분 간격 유지)

---

## 11. 테스트 체크리스트

구현 완료 후 아래 항목을 순서대로 검증:

1. [ ] `.env` 없이 실행해도 크래시하지 않는지 확인
2. [ ] `python lh_monitor.py` 실행 시 시작 로그 정상 출력
3. [ ] 최초 실행 시 기존 공고 기록되고 알림 안 보내지는지 확인
4. [ ] `data/seen.json` 파일 정상 생성 확인
5. [ ] 2번째 실행 시 기존 공고는 무시하고 새 공고만 감지하는지 확인
6. [ ] Telegram 메시지 포맷 (HTML 파싱 정상, 링크 클릭 가능)
7. [ ] Discord Embed 포맷 (색상, 필드, URL 정상)
8. [ ] 네트워크 오류 시 봇이 죽지 않고 계속 동작하는지 확인
9. [ ] Docker 빌드 + 실행 정상 동작
10. [ ] `Ctrl+C`로 정상 종료되는지 확인

---

## 12. 향후 확장 가능성 (현재 구현 범위 아님)

참고용으로만 기재합니다. 현재 구현에 포함하지 마세요.

- 지역 필터링 (부산, 서울 등 특정 지역만 알림)
- 키워드 필터링 (행복주택, 신혼부부 등)
- 웹 대시보드 (Flask/FastAPI)
- 공고 상세 페이지 크롤링 (세대수, 면적, 임대료 정보)
- Supabase 연동 (공고 이력 DB 저장)
