# LH 임대주택 공고 모니터링 봇

LH(한국토지주택공사) 임대주택 공고를 자동으로 수집하여 Telegram과 Discord로 알림을 보내는 Python 봇입니다.

## 주요 기능

공공데이터포털 API, LH 웹 JSON API, HTML 크롤링의 3단계 폴백 체인으로 공고 데이터를 안정적으로 수집합니다. 새로운 공고가 감지되면 Telegram 메시지와 Discord Embed로 실시간 알림을 발송하며, 매일 21시에 당일 감지된 공고의 일일 요약도 함께 전송합니다. 최초 실행 시에는 기존 공고를 기록만 하고 알림을 보내지 않아 중복 알림을 방지합니다.

## 설치 및 실행

### 사전 요구사항

Python 3.10 이상이 필요합니다. Telegram 봇 토큰과 채팅방 ID, 또는 Discord 웹훅 URL 중 하나 이상을 준비해야 합니다.

### 로컬 실행

```bash
pip install -r requirements.txt
cp .env.example .env
# .env 파일을 편집하여 환경변수를 설정합니다
python lh_monitor.py
```

### Docker 실행

```bash
cp .env.example .env
# .env 파일을 편집하여 환경변수를 설정합니다
docker-compose up -d --build
```

컨테이너 로그 확인과 중지는 다음과 같이 합니다.

```bash
docker-compose logs -f lh-monitor
docker-compose down
```

## 환경변수

`.env.example` 파일을 `.env`로 복사한 뒤 아래 항목을 설정합니다.

| 변수 | 필수 | 설명 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | TG 사용 시 | @BotFather에서 발급받은 봇 토큰 |
| `TELEGRAM_CHAT_ID` | TG 사용 시 | 알림을 받을 채팅방 ID |
| `DISCORD_WEBHOOK_URL` | DC 사용 시 | Discord 웹훅 URL |
| `DATA_GO_KR_API_KEY` | 선택 | 공공데이터포털 API 인증키 (없으면 웹크롤링만 사용) |
| `CHECK_INTERVAL` | 선택 | 체크 간격 초 단위 (기본값 1800 = 30분) |
| `DATA_DIR` | 선택 | 데이터 저장 경로 (기본값 `./data`) |

Telegram과 Discord 중 하나 이상은 반드시 설정해야 합니다. 둘 다 미설정 시 에러 로그를 출력하고 종료됩니다.

## 데이터 수집 방식

봇은 세 가지 데이터 소스를 순차적으로 시도합니다. `DATA_GO_KR_API_KEY`가 설정되어 있으면 공공데이터포털 API를 먼저 호출하고, 결과가 비어있으면 LH 웹 크롤링으로 폴백합니다. API 키가 없으면 LH 웹 크롤링을 직접 호출합니다. 웹 크롤링은 내부적으로 LH JSON API를 먼저 시도하고, 실패하면 HTML 파싱으로 폴백합니다.

## 테스트

```bash
pip install pytest
python -m pytest tests/ -v
```
