# LH 임대주택 공고 모니터링 봇 - 아키텍처 설계서

> 작성일: 2026-02-19
> 기반 문서: `LH_MONITOR_IMPLEMENTATION_PLAN.md`
> 프로젝트 코드명: `lh-monitor`

---

## 1. 시스템 개요

이 시스템은 LH 청약센터의 임대주택 공고를 주기적으로 수집하고, 새로운 공고가 감지되면 Telegram과 Discord로 실시간 알림을 발송하는 단일 프로세스 Python 봇입니다. 공공데이터포털 API를 1순위로 사용하되, 실패 시 LH 내부 JSON API, 최종적으로 HTML 크롤링 순서로 자동 폴백합니다. 매일 21시에는 그날 발견된 공고를 요약하여 한 번 더 발송합니다.

설계 철학은 "단순함 우선"입니다. 단일 파일, 동기 루프, JSON 파일 저장이라는 제약 안에서 신뢰성과 유지보수성을 확보하는 것이 핵심 목표입니다.

---

## 2. 아키텍처 다이어그램

### 2.1 전체 시스템 구조

```
                          ┌──────────────────────────────┐
                          │        외부 데이터 소스         │
                          │                              │
                          │  ┌────────────────────────┐  │
                          │  │ 공공데이터포털 API (1순위) │  │
                          │  │ apis.data.go.kr         │  │
                          │  └───────────┬────────────┘  │
                          │              │ (실패 시)      │
                          │  ┌───────────▼────────────┐  │
                          │  │ LH JSON API (2순위)     │  │
                          │  │ apply.lh.or.kr/...Json  │  │
                          │  └───────────┬────────────┘  │
                          │              │ (실패 시)      │
                          │  ┌───────────▼────────────┐  │
                          │  │ HTML 크롤링 (3순위)     │  │
                          │  │ apply.lh.or.kr/...List  │  │
                          │  └────────────────────────┘  │
                          └──────────────┬───────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────┐
│                     lh_monitor.py (단일 프로세스)                    │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    LHMonitor (오케스트레이터)                   │  │
│  │                                                              │  │
│  │   run()  ──────────────────────────────────┐                 │  │
│  │     │                                      │                 │  │
│  │     ▼                                      ▼                 │  │
│  │   check_once()                    send_daily_summary()       │  │
│  │     │                              (매일 21시)                │  │
│  │     │                                                        │  │
│  └─────┼────────────────────────────────────────────────────────┘  │
│        │                                                           │
│        ▼                                                           │
│  ┌────────────┐    ┌────────────┐    ┌─────────────────────────┐  │
│  │ LHCrawler  │───▶│ DataStore  │───▶│      Notifiers          │  │
│  │            │    │            │    │                         │  │
│  │ fetch_api()│    │ is_new()   │    │  ┌───────────────────┐  │  │
│  │ fetch_web()│    │ mark_seen()│    │  │TelegramNotifier   │  │  │
│  │            │    │ save()     │    │  │ send() / send_text│  │  │
│  └────────────┘    └─────┬──────┘    │  └───────────────────┘  │  │
│                          │           │  ┌───────────────────┐  │  │
│                          │           │  │DiscordNotifier    │  │  │
│                          ▼           │  │ send() / send_embed│ │  │
│                    ┌────────────┐    │  └───────────────────┘  │  │
│                    │DailySummary│◀───┘                         │  │
│                    │ add()      │                              │  │
│                    │ get_tg_msg │                              │  │
│                    │get_dc_embed│                              │  │
│                    └────────────┘                              │  │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
                    ┌──────────┐
                    │ data/    │
                    │          │
                    │seen.json │
                    │daily_    │
                    │summary   │
                    │  .json   │
                    └──────────┘
```

### 2.2 데이터 흐름 시퀀스

```
시간축 →

[시작]
  │
  ├─ 환경변수 로드 (.env)
  ├─ 컴포넌트 초기화 (DataStore, LHCrawler, Notifiers, DailySummary)
  ├─ 알림 채널 유효성 검사 (TG/DC 중 하나 이상 필수)
  │
  ├─ [최초 실행 판단: last_check 존재?]
  │     │
  │     ├─ NO → 초기화 모드
  │     │    ├─ fetch (공고 수집)
  │     │    ├─ 모든 공고 ID를 mark_seen
  │     │    └─ 알림 발송 안 함 (조용히 기록만)
  │     │
  │     └─ YES → 즉시 check_once 실행
  │
  └─ [메인 루프 진입]
       │
       ├─ sleep(CHECK_INTERVAL)
       │
       ├─ check_once()
       │    ├─ LHCrawler.fetch_api() 또는 fetch_web()
       │    │    └─ 폴백 체인: API → JSON → HTML
       │    │
       │    ├─ 각 공고에 대해:
       │    │    ├─ DataStore.is_new(id)?
       │    │    │    ├─ YES → new_list에 추가
       │    │    │    │        mark_seen(id)
       │    │    │    │        DailySummary.add(ann)
       │    │    │    └─ NO  → 스킵
       │    │
       │    ├─ DataStore.update_check_time()
       │    │
       │    └─ new_list 비어있지 않으면:
       │         ├─ TelegramNotifier.send(new_list)
       │         └─ DiscordNotifier.send(new_list)
       │
       ├─ [21시이고 오늘 요약 미발송?]
       │    ├─ YES → send_daily_summary()
       │    │         ├─ DailySummary.get_tg_msg() → TG.send_text()
       │    │         └─ DailySummary.get_dc_embed() → DC.send_embed()
       │    └─ NO  → 스킵
       │
       └─ [루프 계속] ──────────────────────▶ sleep ──▶ ...
```

---

## 3. 컴포넌트 상세 설계

### 3.1 LHMonitor (오케스트레이터)

LHMonitor는 전체 시스템의 진입점이자 생명주기를 관리하는 최상위 컴포넌트입니다. 다른 모든 컴포넌트를 생성하고 조율하되, 직접적인 데이터 처리나 네트워크 통신은 수행하지 않습니다. 이 컴포넌트의 핵심 책임은 세 가지로 정리됩니다.

첫째, 초기화 시 환경변수를 읽어 각 컴포넌트를 생성하고 알림 채널 유효성을 검증합니다. Telegram과 Discord 중 하나도 활성화되지 않으면 프로세스를 즉시 종료합니다.

둘째, 최초 실행과 이후 실행을 구분합니다. `DataStore.data["last_check"]`가 존재하지 않으면 최초 실행으로 간주하여 현재 공고를 모두 기록만 하고 알림은 보내지 않습니다. 이 메커니즘이 없으면 봇을 처음 시작할 때마다 수십 건의 기존 공고 알림이 쏟아지게 됩니다.

셋째, `time.sleep` 기반의 무한 루프를 운용합니다. `CHECK_INTERVAL`(기본 1800초) 간격으로 `check_once()`를 호출하고, 매일 21시에는 일일 요약을 발송합니다. 예외 발생 시 로그를 남기고 60초 후 루프를 재개하여 봇이 죽지 않도록 합니다.

```
LHMonitor
├── 속성
│   ├── store: DataStore
│   ├── crawler: LHCrawler
│   ├── tg: TelegramNotifier
│   ├── dc: DiscordNotifier
│   ├── summary: DailySummary
│   ├── use_api: bool (API 키 존재 여부)
│   └── daily_sent_today: bool (오늘 요약 발송 여부)
│
├── check_once() → list[dict]
│   (한 번 체크 + 새 공고 알림 + 반환)
│
├── send_daily_summary()
│   (일일 요약 리포트 발송)
│
└── run()
    (메인 무한 루프)
```

### 3.2 LHCrawler (데이터 수집기)

LHCrawler는 외부 데이터 소스와의 모든 HTTP 통신을 담당합니다. `requests.Session`을 내부에 유지하면서 LH 서버가 요구하는 User-Agent, Referer 등의 헤더를 자동으로 첨부합니다. 이 컴포넌트는 두 개의 공개 메서드만 노출합니다.

`fetch_api(api_key)`는 공공데이터포털 API를 호출합니다. 응답에서 `items.item`이 단일 객체(dict)로 올 수도 있으므로 항상 리스트로 정규화해야 합니다. API가 빈 결과를 반환하면 빈 리스트를 돌려보내되, 예외가 발생하면 이를 상위로 전파하여 폴백 판단을 맡깁니다.

`fetch_web()`은 LH 사이트에서 직접 데이터를 수집합니다. 내부적으로 JSON API를 먼저 시도하고, 실패하면 HTML 크롤링으로 폴백합니다. JSON API 응답에서 필드명이 camelCase(`panId`)와 UPPER_SNAKE(`PAN_ID`) 두 가지 형식으로 올 수 있으므로 양쪽 모두 처리합니다. HTML 크롤링에서는 `<a>` 태그의 `href`에서 panId 파라미터를 추출하되, JavaScript 함수 호출 형식인 경우 정규식으로 숫자 ID를 뽑아냅니다. 어느 쪽도 실패하면 제목의 MD5 해시 앞 16자를 fallback ID로 사용합니다.

두 메서드 모두 동일한 딕셔너리 형식(`id`, `title`, `rental_type`, `status`, `reg_date`, `rcpt_begin`, `rcpt_end`, `url`)을 반환합니다. 날짜 필드는 `normalize_date()` 유틸리티를 거쳐 항상 `YYYY-MM-DD` 형식으로 통일됩니다.

```
LHCrawler
├── 속성
│   └── session: requests.Session (헤더 사전 설정)
│
├── fetch_api(api_key: str) → list[dict]
│   └── 공공데이터포털 REST API 호출
│       └── 주의: items.item dict→list 변환
│
└── fetch_web() → list[dict]
    ├── [시도 1] LH JSON API (POST)
    │   └── 응답 키: "dsList" 또는 "list"
    │   └── 필드명: camelCase / UPPER_SNAKE 양쪽 처리
    │
    └── [시도 2] HTML 크롤링 (GET + BeautifulSoup)
        └── <a href>에서 panId 추출
        └── JS 함수 호출 패턴: 정규식 fallback
        └── 최종 fallback: MD5(제목)[:16]
```

### 3.3 DataStore (상태 관리)

DataStore는 봇의 유일한 영속 상태를 관리합니다. `data/seen.json` 파일 하나에 이미 확인한 공고 ID 목록과 마지막 체크 시각을 기록합니다. 이 컴포넌트가 "새 공고인가?"에 대한 유일한 판정 근거를 제공하므로, 데이터 무결성이 핵심입니다.

`seen_ids` 리스트는 최대 500개로 제한됩니다. 새 ID를 추가할 때 500개를 초과하면 가장 오래된 항목부터 삭제합니다. LH 공고가 수천 건씩 누적되는 것을 방지하면서도 최근 공고의 중복 검출은 확실히 보장하는 크기입니다.

파일 I/O는 `update_check_time()` 호출 시에만 발생합니다. `mark_seen()`은 메모리 상의 리스트만 수정하고, 실제 디스크 쓰기는 한 체크 사이클이 끝난 후 한 번에 수행합니다. 이렇게 하면 공고 10건을 처리할 때 파일 쓰기가 10번이 아니라 1번만 일어납니다.

최초 실행 판단은 `last_check` 필드의 존재 여부로 이루어집니다. 파일이 없거나 `last_check`가 null이면 최초 실행으로 판단하여 LHMonitor가 알림 없이 기존 공고를 기록만 합니다.

```
DataStore
├── 속성
│   ├── filepath: str ("data/seen.json")
│   └── data: dict
│       ├── seen_ids: list[str] (최대 500개)
│       └── last_check: str | None (ISO 8601)
│
├── is_new(ann_id: str) → bool
│   └── ann_id가 seen_ids에 없으면 True
│
├── mark_seen(ann_id: str)
│   └── seen_ids에 추가 (메모리만, 디스크 쓰기 안 함)
│   └── 500개 초과 시 앞에서부터 삭제
│
├── update_check_time()
│   └── last_check = 현재시각 ISO 8601
│   └── save() 호출
│
└── save()
    └── data를 JSON 파일에 쓰기
```

### 3.4 TelegramNotifier

Telegram Bot API의 `sendMessage` 엔드포인트를 감싸는 얇은 래퍼입니다. `token`과 `chat_id`가 모두 존재할 때만 `enabled`가 `True`가 되며, 비활성 상태에서는 모든 호출이 조용히 무시됩니다.

`send(announcements)`는 공고 리스트를 받아 각 공고마다 개별 HTML 메시지를 전송합니다. 공고 간 0.5초 간격을 두어 Telegram rate limit(초당 30메시지)에 걸리지 않도록 합니다. `send_text(text)`는 일일 요약 등 사전 포맷된 문자열을 그대로 전송하는 데 사용합니다.

HTTP 요청의 timeout은 10초로 설정합니다. 전송 실패 시 예외를 로그에 기록하되, 상위로 전파하지 않아 봇 전체가 죽는 것을 방지합니다.

```
TelegramNotifier
├── 속성
│   ├── token: str
│   ├── chat_id: str
│   └── enabled: bool (token && chat_id 존재 시 True)
│
├── send(announcements: list[dict])
│   └── 각 공고마다 HTML 형식 메시지 발송
│   └── 공고 간 0.5초 sleep
│   └── timeout=10, 실패 시 로그만
│
└── send_text(text: str)
    └── 텍스트 직접 발송 (일일 요약용)
```

### 3.5 DiscordNotifier

Discord Webhook URL로 Embed를 전송합니다. 구조적으로 TelegramNotifier와 동일한 패턴을 따르지만, 메시지 포맷이 Discord Embed JSON입니다.

`send(announcements)`는 각 공고를 Embed로 변환하여 개별 전송합니다. Embed의 `color` 필드는 공고 상태에 따라 결정됩니다. 접수중/공고중은 초록(0x00FF00), 접수예정은 파랑(0x0099FF), 접수마감은 빨강(0xFF0000), 기타는 회색(0x808080)입니다. `send_embed(embed)`는 일일 요약 등 사전 구성된 Embed를 직접 전송합니다.

성공 응답 코드는 200 또는 204이며, 그 외는 실패로 간주하여 로그를 남깁니다. 공고 간 0.5초 sleep을 적용합니다.

```
DiscordNotifier
├── 속성
│   ├── webhook_url: str
│   └── enabled: bool (webhook_url 존재 시 True)
│
├── send(announcements: list[dict])
│   └── 각 공고마다 Embed JSON 발송
│   └── 상태별 색상 매핑 적용
│   └── 공고 간 0.5초 sleep
│
└── send_embed(embed: dict)
    └── Embed 직접 발송 (일일 요약용)
```

### 3.6 DailySummary

하루 동안 발견된 새 공고를 누적하여 일일 요약 리포트를 생성하는 컴포넌트입니다. `data/daily_summary.json` 파일에 현재 날짜와 공고 목록을 저장합니다.

`add(ann)` 호출 시 현재 날짜가 저장된 날짜와 다르면 자동으로 리스트를 초기화합니다. 이 메커니즘 덕분에 별도의 "자정 리셋" 로직이 필요 없습니다.

`get_tg_msg()`와 `get_dc_embed()`는 각각 Telegram 텍스트와 Discord Embed 형식으로 요약을 생성합니다. 당일 새 공고가 없으면 `None`을 반환하여 요약 발송 자체를 건너뜁니다.

```
DailySummary
├── 속성
│   ├── filepath: str ("data/daily_summary.json")
│   └── data: dict
│       ├── date: str ("YYYY-MM-DD")
│       └── announcements: list[dict]
│
├── add(ann: dict)
│   └── 날짜 변경 시 자동 리셋
│   └── announcements에 공고 추가 + 저장
│
├── get_tg_msg() → str | None
│   └── 공고 없으면 None
│
└── get_dc_embed() → dict | None
    └── 공고 없으면 None
```

---

## 4. 데이터 모델

### 4.1 공고 정규화 형식

모든 데이터 소스에서 수집된 공고는 아래의 통일된 딕셔너리 구조로 변환됩니다. 이 형식은 시스템 내부의 공용어(lingua franca)로, Crawler부터 Notifier까지 모든 컴포넌트가 동일한 키를 기대합니다.

```python
{
    "id": str,           # 공고 고유 식별자 (panId, sn, 또는 MD5 해시)
    "title": str,        # 공고 제목
    "rental_type": str,  # 임대유형명 (국민임대, 행복주택 등)
    "status": str,       # 접수 상태 (접수중, 접수예정, 접수마감 등)
    "reg_date": str,     # 공고일 (YYYY-MM-DD)
    "rcpt_begin": str,   # 접수시작일 (YYYY-MM-DD)
    "rcpt_end": str,     # 접수종료일 (YYYY-MM-DD)
    "url": str,          # 공고 상세 페이지 URL
}
```

### 4.2 seen.json 구조

```json
{
    "seen_ids": ["panId_001", "panId_002", "..."],
    "last_check": "2026-02-19T14:30:00+09:00"
}
```

`seen_ids` 리스트의 순서는 삽입 순서를 유지합니다. 500개 제한에 도달하면 인덱스 0부터 삭제하므로, 리스트의 뒤쪽이 항상 최신입니다. `last_check`가 `null`이거나 키 자체가 없으면 최초 실행으로 판단합니다.

### 4.3 daily_summary.json 구조

```json
{
    "date": "2026-02-19",
    "announcements": [
        {
            "id": "...",
            "title": "...",
            "rental_type": "...",
            "status": "...",
            "reg_date": "...",
            "rcpt_begin": "...",
            "rcpt_end": "...",
            "url": "..."
        }
    ]
}
```

### 4.4 임대유형 코드 매핑

LH JSON API에서 반환되는 `aisTpCd` 코드를 사람이 읽을 수 있는 이름으로 변환하는 정적 매핑입니다.

```
01 → 국민임대     06 → 공공지원민간임대
02 → 공공임대     07 → 통합공공임대
03 → 영구임대     08 → 전세임대
04 → 행복주택     09 → 매입임대
05 → 장기전세     10 → 기타
```

---

## 5. 데이터 소스 폴백 전략

폴백 전략은 신뢰성과 데이터 정확도 사이의 균형을 잡는 핵심 메커니즘입니다. 공공데이터포털 API가 가장 구조화되고 안정적이지만 API 키가 필요합니다. LH JSON API는 키 없이 사용할 수 있지만 비공식이라 필드명이 변경될 수 있습니다. HTML 크롤링은 최후의 수단으로, 페이지 구조 변경에 가장 취약합니다.

```
                ┌─────────────────────────────┐
                │ DATA_GO_KR_API_KEY 존재?     │
                └─────────┬───────────────────┘
                          │
              ┌───────────┴───────────┐
              │ YES                   │ NO
              ▼                       ▼
    ┌─────────────────┐     ┌─────────────────┐
    │ fetch_api()     │     │ fetch_web()     │
    │ 공공데이터포털    │     │                 │
    └────────┬────────┘     │  ┌───────────┐  │
             │              │  │ JSON API  │  │
             ▼              │  └─────┬─────┘  │
    ┌─────────────────┐     │        │실패     │
    │ 결과 비어있음?   │     │  ┌─────▼─────┐  │
    └────────┬────────┘     │  │HTML 크롤링 │  │
             │              │  └───────────┘  │
     YES     │  NO          └─────────────────┘
      │      │
      ▼      ▼
  fetch_web() 결과 반환
```

각 소스에서 발생할 수 있는 실패 유형과 대응 방식은 다음과 같습니다. 공공데이터포털 API의 경우 HTTP 에러, JSON 파싱 에러, 빈 결과를 감지하면 `fetch_web()`으로 폴백합니다. LH JSON API는 HTTP 에러나 예상 키(`dsList`, `list`)가 없을 때 HTML 크롤링으로 넘어갑니다. HTML 크롤링은 테이블 구조를 찾지 못하면 빈 리스트를 반환하고, 다음 체크 사이클에서 다시 시도합니다.

---

## 6. 에러 처리 및 복원력

### 6.1 계층별 에러 처리

에러 처리 전략의 핵심 원칙은 "봇은 죽지 않아야 한다"입니다. 개인 사용자가 운영하는 모니터링 봇이므로, 일시적 장애로 봇이 종료되면 다시 시작할 때까지 알림 공백이 생깁니다.

```
┌─────────────────────────────────────────────────────────┐
│                    메인 루프 (run)                        │
│  try/except: 모든 예외 → 로그 + 60초 sleep + 루프 재개   │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │              check_once                            │  │
│  │                                                   │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌─────────────┐  │  │
│  │  │ LHCrawler   │  │DataStore │  │ Notifiers   │  │  │
│  │  │             │  │          │  │             │  │  │
│  │  │ Requests    │  │ JSON I/O │  │ HTTP 전송   │  │  │
│  │  │ Exception   │  │ 에러 →   │  │ 실패 →     │  │  │
│  │  │ → 폴백 or  │  │ 로그     │  │ 로그만     │  │  │
│  │  │   빈 리스트  │  │          │  │ (계속 진행) │  │  │
│  │  └─────────────┘  └──────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

데이터 수집 단계에서는 `requests.RequestException`을 캐치하여 다음 데이터 소스로 폴백합니다. JSON 파싱 에러(`json.JSONDecodeError`)도 마찬가지로 폴백 트리거입니다. 모든 소스가 실패하면 빈 리스트를 반환하고 다음 체크 사이클을 기다립니다.

알림 발송 단계에서는 Telegram이든 Discord든 전송 실패 시 예외를 로그에 기록하되 상위로 전파하지 않습니다. Telegram이 실패해도 Discord 발송은 계속 진행됩니다.

메인 루프에서는 `KeyboardInterrupt`를 제외한 모든 예외를 캐치하여 에러 로그를 남기고 60초 후 루프를 재개합니다.

### 6.2 타임아웃 정책

모든 HTTP 요청에는 명시적 timeout을 설정합니다. 데이터 수집(크롤링, API 호출)은 30초, 알림 발송(Telegram, Discord)은 10초입니다. 크롤링이 더 긴 이유는 LH 서버의 응답 속도가 일정하지 않기 때문이고, 알림은 외부 API 서버가 안정적이라 짧은 timeout이면 충분합니다.

### 6.3 Rate Limiting

LH 서버에 대한 요청은 `CHECK_INTERVAL`(기본 30분)로 자연스럽게 제한됩니다. Telegram과 Discord 알림은 공고 간 0.5초 sleep을 두어 rate limit에 걸리지 않도록 합니다.

---

## 7. 배포 아키텍처

### 7.1 Docker 컨테이너 구조

```
┌──────────────────────────────────────────┐
│            VPS (Linux)                    │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │      Docker Engine                 │  │
│  │                                    │  │
│  │  ┌──────────────────────────────┐  │  │
│  │  │  lh-monitor 컨테이너         │  │  │
│  │  │                              │  │  │
│  │  │  python:3.11-slim 기반       │  │  │
│  │  │  TZ=Asia/Seoul               │  │  │
│  │  │                              │  │  │
│  │  │  /app/lh_monitor.py          │  │  │
│  │  │  /app/.env                   │  │  │
│  │  │  /app/data/ ←─── volume ───┐ │  │  │
│  │  │                            │ │  │  │
│  │  └────────────────────────────┘ │  │  │
│  │                                 │  │  │
│  └─────────────────────────────────┘  │  │
│                                  │       │
│               ┌──────────────────┘       │
│               ▼                          │
│        ./data/ (호스트)                   │
│        ├── seen.json                     │
│        └── daily_summary.json            │
└──────────────────────────────────────────┘
```

컨테이너는 `restart: unless-stopped` 정책으로 실행되어, 예기치 않은 종료 시 자동으로 재시작됩니다. `data/` 디렉토리는 Docker volume으로 호스트에 마운트되어 컨테이너가 재생성되어도 상태가 유지됩니다. `.env` 파일도 volume으로 마운트하여 이미지에 포함시키지 않습니다(보안상 민감 정보이므로).

로그는 Docker의 json-file 드라이버로 관리되며, 최대 10MB 크기의 파일 3개까지 로테이션됩니다. Python의 `-u` 플래그로 출력 버퍼링을 비활성화하여 `docker-compose logs -f`로 실시간 로그를 확인할 수 있습니다.

타임존은 `TZ=Asia/Seoul`로 설정하여 일일 요약의 "21시" 기준이 한국 시간에 맞도록 합니다.

---

## 8. 프로젝트 파일 구조

```
lh-monitor/
├── lh_monitor.py          # 모든 클래스가 포함된 단일 파일
│   ├── normalize_date()   # 유틸리티: 날짜 문자열 정규화
│   ├── RENTAL_TYPES       # 상수: 임대유형 코드 매핑
│   ├── class DataStore    # 상태 관리 (seen.json)
│   ├── class LHCrawler    # 데이터 수집 (3소스 폴백)
│   ├── class TelegramNotifier  # Telegram 알림
│   ├── class DiscordNotifier   # Discord 알림
│   ├── class DailySummary      # 일일 요약
│   ├── class LHMonitor         # 오케스트레이터
│   └── if __name__ == "__main__":  # 진입점
│
├── .env                   # 환경변수 (gitignore 대상)
├── .env.example           # 환경변수 템플릿
├── requirements.txt       # Python 의존성
│   ├── requests
│   ├── beautifulsoup4
│   └── python-dotenv
│
├── Dockerfile             # Docker 이미지 정의
├── docker-compose.yml     # Docker Compose 배포 설정
├── .gitignore             # Git 무시 파일 목록
├── README.md              # 사용 설명서
│
└── data/                  # 런타임 데이터 (자동 생성, gitignore 대상)
    ├── seen.json
    └── daily_summary.json
```

`lh_monitor.py` 파일 내부의 코드 배치 순서는 위에 나열한 순서를 따릅니다. 유틸리티 함수와 상수가 최상단에 위치하고, 의존성이 적은 클래스부터 많은 클래스 순서로 나열하여, 파일을 위에서 아래로 읽을 때 자연스럽게 전체 구조를 파악할 수 있도록 합니다.

---

## 9. 설계 결정 근거

### 9.1 왜 단일 파일인가

이 프로젝트는 클래스가 6개이고 총 코드량이 500줄 내외로 예상됩니다. 이 규모에서 모듈을 분리하면 임포트 관리, 패키지 구조, `__init__.py` 등의 부수적 복잡도가 오히려 유지보수를 어렵게 만듭니다. 단일 파일은 배포도 단순합니다. `lh_monitor.py` 하나만 복사하면 끝입니다.

### 9.2 왜 동기 루프인가

30분 간격의 폴링 작업에 비동기(async/await)는 과잉 설계입니다. 동시 요청이 필요 없고, I/O 대기 시간도 몇 초에 불과합니다. `time.sleep` 기반 루프는 디버깅이 쉽고 예외 처리가 명확하며, asyncio의 이벤트 루프 관리에 따르는 복잡도를 피할 수 있습니다.

### 9.3 왜 JSON 파일 저장인가

저장해야 하는 데이터가 최대 500개의 문자열 ID와 하루치 공고 목록뿐입니다. SQLite조차 불필요한 규모입니다. JSON 파일은 사람이 직접 열어볼 수 있고, 디버깅 시 상태를 즉시 확인할 수 있으며, 백업이 파일 복사 한 번입니다.

### 9.4 왜 3단계 폴백인가

공공데이터포털 API는 가장 안정적이지만 API 키 발급이 필요하고 간헐적으로 장애가 발생합니다. LH JSON API는 키 없이 사용 가능하지만 비공식이라 언제 변경될지 모릅니다. HTML 크롤링은 가장 느리고 취약하지만 웹페이지가 존재하는 한 동작합니다. 세 단계를 조합하면 어느 한 소스에 장애가 생겨도 모니터링이 중단되지 않습니다.

---

## 10. 구현 순서 권장안

아키텍처의 의존성 방향을 고려하면, 아래 순서로 구현하는 것이 가장 효율적입니다. 각 단계가 완료될 때마다 독립적으로 테스트할 수 있습니다.

```
Phase 1: 기반 구조
  ├── 프로젝트 스캐폴딩 (파일 생성, .env.example, requirements.txt)
  ├── 로깅 설정
  ├── normalize_date() 유틸리티
  └── RENTAL_TYPES 상수

Phase 2: 데이터 계층
  ├── DataStore 클래스
  └── 검증: seen.json 생성/로드/저장 동작 확인

Phase 3: 데이터 수집
  ├── LHCrawler.fetch_api()
  ├── LHCrawler.fetch_web() (JSON API + HTML 크롤링)
  └── 검증: 각 소스에서 공고 리스트 정상 반환 확인

Phase 4: 알림 발송
  ├── TelegramNotifier
  ├── DiscordNotifier
  └── 검증: 테스트 메시지 발송 확인

Phase 5: 통합 및 오케스트레이션
  ├── DailySummary
  ├── LHMonitor (check_once, send_daily_summary, run)
  └── 검증: 전체 플로우 동작 확인

Phase 6: 배포
  ├── Dockerfile
  ├── docker-compose.yml
  └── 검증: 컨테이너 빌드 + 실행 + 로그 확인
```

---

이 문서는 `LH_MONITOR_IMPLEMENTATION_PLAN.md`의 요구사항을 아키텍처 관점에서 정리한 것입니다. 구현 시 상세 로직, 메시지 포맷, 환경변수 사양 등은 원본 구현계획서를 참조하세요.
