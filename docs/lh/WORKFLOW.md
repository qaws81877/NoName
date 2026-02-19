# LH 임대주택 공고 모니터링 봇 - 구현 워크플로우

> 작성일: 2026-02-19
> 기반 문서: `LH_MONITOR_IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`
> 실행 방법: `/sc:implement` 커맨드로 각 Phase를 순차 실행

---

## 워크플로우 개요

이 워크플로우는 6개 Phase로 구성되며, 각 Phase는 이전 Phase의 산출물에 의존합니다. Phase 내부의 Task는 위에서 아래로 순차 실행하되, 명시적으로 "병렬 가능"이라고 표기된 Task는 동시에 진행할 수 있습니다. 모든 Phase는 검증 게이트를 통과해야 다음 Phase로 넘어갑니다.

전체 흐름은 프로젝트 스캐폴딩으로 시작하여 DataStore, LHCrawler, Notifier들을 순서대로 쌓아올린 뒤, LHMonitor 오케스트레이터로 통합하고, 마지막에 Docker 배포 구성으로 마무리합니다.

```
Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5 ──▶ Phase 6
스캐폴딩    DataStore   LHCrawler   Notifiers   통합/오케    Docker배포
                                    (TG + DC)   스트레이션
```

---

## Phase 1: 프로젝트 스캐폴딩 및 기반 구조

이 Phase에서는 프로젝트의 뼈대를 세웁니다. 아직 비즈니스 로직은 없으며, 파일 구조, 의존성 선언, 환경변수 템플릿, 로깅 설정, 그리고 전체 코드에서 공유할 유틸리티 함수와 상수를 준비합니다.

### Task 1.1: 프로젝트 파일 생성

`requirements.txt`, `.env.example`, `.gitignore`를 생성합니다.

`requirements.txt`에는 `requests`, `beautifulsoup4`, `python-dotenv` 세 가지만 선언합니다. 버전 고정은 하되 메이저 버전만 고정합니다(예: `requests>=2.28,<3`). `.env.example`에는 구현계획서 6장에 명시된 6개 환경변수를 빈 값으로 나열하고, 각 변수 위에 한 줄짜리 한국어 주석을 답니다. `.gitignore`에는 `data/`, `.env`, `__pycache__/`, `*.pyc`, `lh_monitor.log`를 포함합니다.

검증: 세 파일이 프로젝트 루트에 존재하고, `pip install -r requirements.txt`가 정상 완료되는지 확인합니다.

### Task 1.2: lh_monitor.py 초기 골격 작성

단일 파일 `lh_monitor.py`를 생성하고 다음 요소를 포함합니다.

파일 최상단에 인코딩 선언(`# -*- coding: utf-8 -*-`)과 임포트 블록을 배치합니다. 임포트는 `os`, `sys`, `json`, `time`, `logging`, `hashlib`, `re`, `datetime`(표준 라이브러리), `requests`, `bs4.BeautifulSoup`(서드파티), `dotenv.load_dotenv`(서드파티) 순서로 그룹핑합니다. 그 아래에 `load_dotenv()` 호출을 배치합니다.

로깅 설정은 구현계획서 9장의 사양을 따릅니다. 콘솔(StreamHandler)과 파일(`lh_monitor.log`, UTF-8 FileHandler)에 동시 출력하며, 포맷은 `%(asctime)s [%(levelname)s] %(message)s`, 레벨은 INFO입니다. `logger = logging.getLogger("lh_monitor")`로 네임드 로거를 생성합니다.

`RENTAL_TYPES` 딕셔너리 상수를 구현계획서 4.2절의 매핑 그대로 선언합니다.

`normalize_date(s)` 함수를 작성합니다. 입력이 빈 문자열이면 빈 문자열을 반환합니다. 숫자와 하이픈 이외의 문자(슬래시 등)를 제거한 뒤, 8자리 숫자이면 `YYYY-MM-DD` 형식으로 변환합니다. 이미 `YYYY-MM-DD` 형식이면 그대로 반환합니다.

파일 최하단에 `if __name__ == "__main__":` 블록을 두고, `pass`만 넣어둡니다(Phase 5에서 채움).

검증: `python lh_monitor.py` 실행 시 에러 없이 종료되고, `normalize_date("20250219")`가 `"2025-02-19"`를, `normalize_date("2025/02/19")`가 `"2025-02-19"`를, `normalize_date("")`가 `""`를 반환하는지 확인합니다.

### Phase 1 검증 게이트

`python -c "from lh_monitor import normalize_date, RENTAL_TYPES; assert normalize_date('20250219') == '2025-02-19'; assert RENTAL_TYPES['04'] == '행복주택'; print('Phase 1 OK')"` 명령이 `Phase 1 OK`를 출력해야 합니다.

---

## Phase 2: DataStore (상태 관리)

DataStore는 다른 모든 컴포넌트보다 먼저 구현해야 합니다. 이 클래스가 제공하는 `is_new()` / `mark_seen()` 인터페이스는 Phase 3(LHCrawler)와 Phase 5(LHMonitor)에서 직접 사용됩니다.

### Task 2.1: DataStore 클래스 구현

`lh_monitor.py`에 `DataStore` 클래스를 추가합니다.

`__init__(self, filepath="data/seen.json")`에서 파일 경로를 저장하고, 디렉토리가 없으면 `os.makedirs`로 생성합니다. 파일이 존재하면 JSON으로 읽어 `self.data`에 로드하고, 없으면 `{"seen_ids": [], "last_check": None}`으로 초기화합니다. JSON 파싱 실패 시에도 초기값으로 대체하고 경고 로그를 남깁니다.

`is_new(self, ann_id)` 메서드는 `ann_id`가 `self.data["seen_ids"]`에 없으면 `True`를 반환합니다.

`mark_seen(self, ann_id)` 메서드는 `ann_id`가 아직 목록에 없을 때만 추가합니다. 추가 후 리스트 길이가 500을 초과하면 `self.data["seen_ids"] = self.data["seen_ids"][-500:]`으로 앞쪽을 잘라냅니다. 이 메서드는 디스크에 쓰지 않습니다.

`update_check_time(self)` 메서드는 `self.data["last_check"]`를 현재 시각의 ISO 8601 문자열로 갱신하고 `self.save()`를 호출합니다.

`save(self)` 메서드는 `self.data`를 `self.filepath`에 JSON으로 씁니다. `ensure_ascii=False`, `indent=2`를 사용합니다.

검증: 아래 시나리오를 순서대로 확인합니다.

```
1. DataStore 생성 → data/seen.json 파일 생성 확인
2. is_new("test1") → True
3. mark_seen("test1")
4. is_new("test1") → False
5. 501개 ID를 mark_seen → seen_ids 길이가 500인지 확인
6. update_check_time() → 파일에 last_check 기록 확인
7. DataStore를 다시 생성(같은 경로) → 기존 데이터 유지 확인
```

### Phase 2 검증 게이트

`data/seen.json` 파일이 올바른 JSON이고, `seen_ids`와 `last_check` 필드가 존재하며, 501개 삽입 후 길이가 500인지 코드로 확인합니다.

---

## Phase 3: LHCrawler (데이터 수집)

이 Phase는 외부 시스템과의 통신을 담당하므로 가장 복잡합니다. 3개 데이터 소스를 순서대로 구현하되, 각 소스를 독립적으로 테스트한 뒤 폴백 체인을 조립합니다.

### Task 3.1: LHCrawler 기본 구조 및 HTTP 세션

`LHCrawler` 클래스를 생성합니다.

`__init__(self)`에서 `requests.Session()`을 생성하고, 구현계획서 4.2절에 명시된 User-Agent, Accept-Language, Referer 헤더를 세션에 설정합니다. 헤더 값은 구현계획서에 적힌 것을 그대로 사용합니다.

검증: `LHCrawler()` 생성 후 `crawler.session.headers` 딕셔너리에 세 헤더가 포함되어 있는지 확인합니다.

### Task 3.2: fetch_api() 구현 (공공데이터포털 API)

`fetch_api(self, api_key)` 메서드를 구현합니다.

엔드포인트는 `http://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1`이며, 쿼리 파라미터로 `ServiceKey=api_key`, `pageNo=1`, `numOfRows=30`, `type=json`을 전달합니다. `timeout=30`으로 GET 요청을 보내고, 응답 JSON에서 `response.body.items.item`을 추출합니다.

`items.item`이 dict(단일 객체)일 수 있으므로, dict이면 `[item]`으로 감싸서 리스트로 만듭니다. 각 항목을 정규화 딕셔너리(`id`, `title`, `rental_type`, `status`, `reg_date`, `rcpt_begin`, `rcpt_end`, `url`)로 변환합니다. API 필드 매핑은 `sn` → `id`, `sj` → `title`, `typeCdNm` → `rental_type`, `crtDt` → `reg_date`, `rceptBgnDt` → `rcpt_begin`, `rceptEndDt` → `rcpt_end`, `dtlUrl` → `url`입니다. `status`는 API에서 직접 제공하지 않으므로 빈 문자열로 두되, 접수 기간으로 유추 가능하면 설정합니다. 날짜 필드에는 `normalize_date()`를 적용합니다.

예외(`requests.RequestException`, `json.JSONDecodeError`, `KeyError`)가 발생하면 경고 로그를 남기고 빈 리스트를 반환합니다.

검증: API 키가 없는 상태에서 호출하면 빈 리스트를 반환하고 에러 로그가 남는지 확인합니다. API 키가 있으면 실제 응답에서 공고 리스트가 반환되고, 각 항목에 8개 필드가 모두 존재하는지 확인합니다.

### Task 3.3: fetch_web() 내부 - LH JSON API (2순위)

`fetch_web(self)` 메서드의 첫 번째 시도로 LH JSON API를 구현합니다.

엔드포인트는 `https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancListJson.do`이며, POST 요청으로 form data `pg=1`, `pgSz=30`, `uppAisTpCd=13`을 전달합니다. `timeout=30`입니다.

응답 JSON에서 리스트를 추출할 때 `dsList` 키를 먼저 시도하고, 없으면 `list` 키를 시도합니다. 둘 다 없으면 예외를 발생시켜 HTML 크롤링으로 폴백합니다.

각 항목의 필드명은 camelCase와 UPPER_SNAKE 두 가지가 올 수 있습니다. `item.get("panId") or item.get("PAN_ID", "")`와 같은 패턴으로 양쪽을 처리합니다. 임대유형 코드(`aisTpCd` / `AIS_TP_CD`)는 `RENTAL_TYPES` 딕셔너리로 변환합니다.

상세 URL은 `f"https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancView.do?panId={pan_id}"` 형식으로 구성합니다.

수집 건수를 INFO 로그로 남깁니다(예: `JSON API: 25개 수집`).

검증: LH 사이트에 실제 POST 요청을 보내 공고 리스트가 반환되는지 확인합니다. 반환된 각 항목에 8개 필드가 모두 존재하고, `rental_type`이 한국어 이름으로 변환되어 있는지 확인합니다.

### Task 3.4: fetch_web() 내부 - HTML 크롤링 (3순위)

JSON API가 실패했을 때의 폴백으로 HTML 크롤링을 구현합니다.

URL은 `https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026`이며, GET 요청으로 `timeout=30`입니다.

BeautifulSoup으로 HTML을 파싱한 뒤, `table tbody tr` 또는 `.board-list tbody tr` 또는 `.tbl_list tbody tr` 셀렉터로 행을 찾습니다. 어느 셀렉터로도 찾지 못하면 빈 리스트를 반환합니다.

각 행에서 `<a>` 태그의 `href`를 검사합니다. `panId=` 파라미터가 있으면 그 값을 ID로 사용합니다. href가 JavaScript 함수 호출(`javascript:fn('12345')` 등)이면 `re.search(r"['\"](\d+)['\"]", href)`로 숫자 ID를 추출합니다. 둘 다 실패하면 제목 텍스트의 MD5 해시 앞 16자를 ID로 사용합니다.

`<td>` 컬럼들에서 임대유형, 공고일, 접수기간, 상태를 추출합니다. 컬럼 순서는 LH 페이지 구조에 따라 다를 수 있으므로, 컬럼 수가 예상과 다르면 가능한 만큼만 추출하고 나머지는 빈 문자열로 둡니다.

수집 건수를 INFO 로그로 남깁니다(예: `HTML 크롤링: 25개 수집`).

검증: LH 웹페이지에 실제 GET 요청을 보내 HTML을 파싱하고, 공고 리스트가 반환되는지 확인합니다.

### Task 3.5: fetch_web() 폴백 체인 조립

`fetch_web()` 메서드의 전체 흐름을 조립합니다. JSON API를 try/except로 시도하고, 실패 시 경고 로그를 남긴 뒤 HTML 크롤링으로 폴백합니다. HTML 크롤링도 실패하면 에러 로그를 남기고 빈 리스트를 반환합니다.

검증: JSON API와 HTML 크롤링 모두에서 공고를 수집할 수 있는지 확인합니다. JSON API를 의도적으로 실패시켜(잘못된 URL 등) HTML 크롤링으로 자동 폴백되는지 확인합니다.

### Phase 3 검증 게이트

`LHCrawler().fetch_web()`이 빈 리스트가 아닌 공고 리스트를 반환하고, 각 항목이 8개 키(`id`, `title`, `rental_type`, `status`, `reg_date`, `rcpt_begin`, `rcpt_end`, `url`)를 포함하는지 확인합니다.

---

## Phase 4: 알림 발송 (Telegram + Discord)

TelegramNotifier와 DiscordNotifier는 서로 독립적이므로 병렬 구현이 가능합니다. 두 클래스 모두 동일한 패턴(enabled 플래그, send 메서드, rate limiting)을 따릅니다.

### Task 4.1: TelegramNotifier 구현

`TelegramNotifier` 클래스를 구현합니다.

`__init__(self, token, chat_id)`에서 두 값을 저장하고, 둘 다 truthy이면 `self.enabled = True`로 설정합니다.

`send(self, announcements)` 메서드는 `enabled`가 `False`이면 즉시 반환합니다. 각 공고에 대해 구현계획서 4.3절의 HTML 메시지 포맷을 생성하고, `https://api.telegram.org/bot{self.token}/sendMessage`에 POST 요청을 보냅니다. 요청 본문은 `{"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"}`이며, `timeout=10`입니다. 성공하면 `TG ✅ {제목 앞 20자}...` 로그를 남기고, 실패하면 경고 로그를 남깁니다. 공고 간 `time.sleep(0.5)`를 적용합니다.

`send_text(self, text)` 메서드는 `enabled`가 `False`이면 즉시 반환합니다. 동일한 API로 `text`를 그대로 전송합니다.

검증: `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`가 설정된 상태에서 테스트 메시지를 발송하여 Telegram에서 수신되는지 확인합니다. 환경변수가 없으면 `enabled=False`로 되어 호출이 무시되는지 확인합니다.

### Task 4.2: DiscordNotifier 구현

`DiscordNotifier` 클래스를 구현합니다.

`__init__(self, webhook_url)`에서 URL을 저장하고, truthy이면 `self.enabled = True`로 설정합니다.

상태별 색상을 결정하는 내부 메서드 또는 로직을 구현합니다. 상태 문자열에 "접수중" 또는 "공고중"이 포함되면 `0x00FF00`, "접수예정"이면 `0x0099FF`, "접수마감" 또는 "마감"이면 `0xFF0000`, 그 외는 `0x808080`입니다.

`send(self, announcements)` 메서드는 `enabled`가 `False`이면 즉시 반환합니다. 각 공고에 대해 구현계획서 4.4절의 Embed JSON을 생성하고, `self.webhook_url`에 POST 요청을 보냅니다. `timeout=10`이며, 응답 코드가 200 또는 204이면 성공입니다. 공고 간 `time.sleep(0.5)`를 적용합니다.

`send_embed(self, embed)` 메서드는 `enabled`가 `False`이면 즉시 반환합니다. 전달받은 Embed를 `{"embeds": [embed]}`로 감싸서 전송합니다.

검증: `DISCORD_WEBHOOK_URL`이 설정된 상태에서 테스트 Embed를 발송하여 Discord 채널에서 수신되는지 확인합니다. 환경변수가 없으면 호출이 무시되는지 확인합니다.

### Phase 4 검증 게이트

Telegram과 Discord 중 하나 이상에서 테스트 메시지가 정상 수신됩니다. 환경변수가 없는 Notifier는 `enabled=False`로 조용히 무시됩니다.

---

## Phase 5: 통합 및 오케스트레이션

이 Phase에서 DailySummary와 LHMonitor를 구현하여 전체 시스템을 조립합니다. Phase 1~4의 모든 컴포넌트가 여기서 하나의 동작하는 봇으로 통합됩니다.

### Task 5.1: DailySummary 구현

`DailySummary` 클래스를 구현합니다.

`__init__(self, filepath="data/daily_summary.json")`에서 파일 경로를 저장하고, 파일이 존재하면 로드합니다. 없으면 `{"date": "", "announcements": []}`로 초기화합니다.

`add(self, ann)` 메서드에서 오늘 날짜(`datetime.date.today().isoformat()`)가 `self.data["date"]`와 다르면 `announcements`를 빈 리스트로 리셋하고 `date`를 오늘로 갱신합니다. 그 다음 공고를 `announcements`에 추가하고 파일에 저장합니다.

`get_tg_msg(self)` 메서드는 `announcements`가 비어있으면 `None`을 반환합니다. 아니면 구현계획서의 Telegram 메시지 포맷에 준하여 요약 텍스트를 생성합니다. 제목은 `📊 LH 임대주택 일일 요약 ({날짜})`이고, 각 공고를 한 줄씩 나열합니다.

`get_dc_embed(self)` 메서드도 마찬가지로 `announcements`가 비어있으면 `None`을 반환하고, 아니면 Discord Embed 딕셔너리를 생성합니다. Embed title은 `📊 LH 임대주택 일일 요약`, color는 `0x0099FF`(파랑)로 합니다.

검증: `add()`로 공고 2개를 추가한 뒤 `get_tg_msg()`가 `None`이 아닌 문자열을 반환하는지 확인합니다. 날짜를 강제로 변경한 뒤 `add()`를 호출하면 리스트가 리셋되는지 확인합니다.

### Task 5.2: LHMonitor 클래스 구현

`LHMonitor` 클래스를 구현합니다. 이 클래스는 `__init__`, `check_once`, `send_daily_summary`, `run` 네 메서드로 구성됩니다.

`__init__(self)`에서 환경변수를 읽어 각 컴포넌트를 생성합니다.

```
data_dir    = os.getenv("DATA_DIR", "./data")
self.store  = DataStore(os.path.join(data_dir, "seen.json"))
self.crawler = LHCrawler()
self.tg     = TelegramNotifier(os.getenv("TELEGRAM_BOT_TOKEN", ""),
                                os.getenv("TELEGRAM_CHAT_ID", ""))
self.dc     = DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL", ""))
self.summary = DailySummary(os.path.join(data_dir, "daily_summary.json"))
self.api_key = os.getenv("DATA_GO_KR_API_KEY", "")
self.interval = int(os.getenv("CHECK_INTERVAL", "1800"))
self.daily_sent_date = ""
```

`check_once(self)` 메서드는 아키텍처 설계서 2.2절의 데이터 흐름을 구현합니다. API 키가 있으면 `fetch_api()`를 먼저 시도하고, 결과가 비어있으면 `fetch_web()`으로 폴백합니다. API 키가 없으면 바로 `fetch_web()`을 호출합니다. 수집된 공고 중 `store.is_new()`인 것만 새 공고 리스트에 추가하고, `mark_seen()`, `summary.add()`를 호출합니다. `store.update_check_time()`으로 상태를 저장하고, 새 공고가 있으면 `tg.send()`와 `dc.send()`를 호출합니다. 새 공고 수를 INFO 로그로 남깁니다.

`send_daily_summary(self)` 메서드는 `summary.get_tg_msg()`와 `summary.get_dc_embed()`를 호출하여, 결과가 `None`이 아니면 각각 `tg.send_text()`, `dc.send_embed()`로 발송합니다. `self.daily_sent_date`를 오늘 날짜로 갱신합니다.

`run(self)` 메서드는 구현계획서 5.1절의 메인 루프를 구현합니다. 시작 로그(봇 이름, 간격, 채널 상태, 데이터 소스 방식)를 출력합니다. `tg.enabled`와 `dc.enabled`가 모두 `False`이면 에러 로그를 남기고 종료합니다. `store.data.get("last_check")`가 없으면 최초 실행 모드로, 공고를 수집하여 모든 ID를 `mark_seen`하고 `update_check_time()`만 호출합니다(알림 안 보냄). 최초가 아니면 `check_once()`를 즉시 한 번 실행합니다. 이후 무한 루프에서 `time.sleep(self.interval)` → `check_once()` → 21시 요약 체크를 반복합니다. `KeyboardInterrupt`는 종료 로그를 남기고 `sys.exit(0)`, 그 외 예외는 에러 로그 + 60초 sleep 후 계속입니다.

### Task 5.3: 메인 진입점 작성

`if __name__ == "__main__":` 블록에 `LHMonitor().run()`을 호출합니다.

검증: `.env`에 최소한 Telegram 또는 Discord 중 하나의 환경변수를 설정한 상태에서 `python lh_monitor.py`를 실행합니다. 시작 로그가 출력되고, 최초 실행 시 기존 공고를 기록만 하며 알림을 보내지 않는지 확인합니다. `data/seen.json`에 공고 ID들이 기록되고 `last_check`가 설정되는지 확인합니다. `Ctrl+C`로 정상 종료되는지 확인합니다.

### Phase 5 검증 게이트

봇이 시작되어 공고를 수집하고, 최초 실행 시 알림 없이 기록하며, 두 번째 실행부터 새 공고만 감지하여 알림을 발송합니다. `Ctrl+C`로 정상 종료됩니다.

---

## Phase 6: Docker 배포

최종 Phase에서는 프로덕션 배포를 위한 Docker 구성을 만듭니다. 코드 변경은 없으며 인프라 파일만 추가합니다.

### Task 6.1: Dockerfile 작성

구현계획서 7.1절의 사양을 그대로 따릅니다.

`python:3.11-slim` 베이스 이미지, `/app` 작업 디렉토리, `requirements.txt` 먼저 복사하여 `pip install`, 그 다음 `lh_monitor.py` 복사, `data/` 디렉토리 생성, `CMD ["python", "-u", "lh_monitor.py"]`로 구성합니다.

주의사항으로 `.env`는 Dockerfile에서 `COPY`하지 않습니다. docker-compose에서 volume으로 마운트하므로 이미지에 포함시키면 안 됩니다. 구현계획서 7.1절에 `COPY .env .`가 있지만 이는 보안상 제거하는 것이 맞습니다. 대신 docker-compose의 volume 마운트로 대체합니다.

검증: `docker build -t lh-monitor .`가 성공하는지 확인합니다.

### Task 6.2: docker-compose.yml 작성

구현계획서 7.2절의 사양을 따르되, `.env` 파일은 volumes로 마운트합니다.

`restart: unless-stopped`, `TZ=Asia/Seoul`, 로그 드라이버 `json-file`(max-size 10m, max-file 3), volume으로 `./data:/app/data`와 `./.env:/app/.env:ro`를 마운트합니다.

검증: `docker-compose up -d --build`로 컨테이너가 정상 시작되고, `docker-compose logs -f lh-monitor`에서 시작 로그가 실시간으로 출력되는지 확인합니다. `docker-compose down`으로 정상 중지되는지 확인합니다.

### Phase 6 검증 게이트

Docker 컨테이너가 빌드, 실행, 중지 모두 정상 동작하고, `data/` 디렉토리의 상태가 컨테이너 재시작 후에도 유지됩니다.

---

## 최종 검증 체크리스트

모든 Phase가 완료된 후 아래 항목을 순서대로 검증합니다. 이 체크리스트는 구현계획서 11장의 항목과 일치합니다.

```
[  ] .env 없이 실행해도 크래시하지 않는지 확인
[  ] python lh_monitor.py 실행 시 시작 로그 정상 출력
[  ] 최초 실행 시 기존 공고 기록되고 알림 안 보내지는지 확인
[  ] data/seen.json 파일 정상 생성 확인
[  ] 2번째 실행 시 기존 공고는 무시하고 새 공고만 감지하는지 확인
[  ] Telegram 메시지 포맷 (HTML 파싱 정상, 링크 클릭 가능)
[  ] Discord Embed 포맷 (색상, 필드, URL 정상)
[  ] 네트워크 오류 시 봇이 죽지 않고 계속 동작하는지 확인
[  ] Docker 빌드 + 실행 정상 동작
[  ] Ctrl+C로 정상 종료되는지 확인
```

---

## 의존성 맵 요약

```
Phase 1 (스캐폴딩)
  │
  ▼
Phase 2 (DataStore)
  │
  ├────────────────────┐
  ▼                    ▼
Phase 3 (LHCrawler)  Phase 4 (Notifiers) ← 병렬 가능하나
  │                    │                     Phase 2 완료 필요
  └────────┬───────────┘
           ▼
Phase 5 (통합: DailySummary + LHMonitor)
           │
           ▼
Phase 6 (Docker 배포)
```

Phase 3과 Phase 4는 이론적으로 병렬 진행이 가능합니다. 둘 다 Phase 2의 DataStore에 직접 의존하지 않지만, 같은 `lh_monitor.py` 파일을 편집하므로 충돌 방지를 위해 순차 실행을 권장합니다. Phase 5는 반드시 Phase 3과 4가 모두 완료된 후에 시작해야 합니다.

---

이 워크플로우의 다음 단계는 `/sc:implement`로 Phase 1부터 순차적으로 실행하는 것입니다.
