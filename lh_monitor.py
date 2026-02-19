# -*- coding: utf-8 -*-
"""LH 임대주택 공고 모니터링 봇"""

import os
import sys
import json
import time
import logging
import hashlib
import re
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── 로깅 설정 ──────────────────────────────────────────────

logger = logging.getLogger("lh_monitor")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

_fh = logging.FileHandler("lh_monitor.log", encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

# ── 상수 ────────────────────────────────────────────────────

RENTAL_TYPES = {
    "01": "국민임대",
    "02": "공공임대",
    "03": "영구임대",
    "04": "행복주택",
    "05": "장기전세",
    "06": "공공지원민간임대",
    "07": "통합공공임대",
    "08": "전세임대",
    "09": "매입임대",
    "10": "기타",
}

# ── 유틸리티 ────────────────────────────────────────────────


def normalize_date(s: str) -> str:
    """날짜 문자열을 YYYY-MM-DD 형식으로 정규화한다."""
    if not s:
        return ""
    # 숫자와 하이픈만 남긴다 (슬래시, 점 등 제거)
    cleaned = re.sub(r"[^0-9-]", "", s)
    # 8자리 숫자 → YYYY-MM-DD
    if re.fullmatch(r"\d{8}", cleaned):
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    # 이미 YYYY-MM-DD 형식
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned
    return cleaned


# ── DataStore ───────────────────────────────────────────────


class DataStore:
    """이미 확인한 공고 ID를 JSON 파일로 관리하여 중복 알림을 방지한다."""

    def __init__(self, filepath="data/seen.json"):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.data = {"seen_ids": [], "last_check": None}
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                logger.warning("seen.json 파싱 실패, 초기값으로 대체합니다")

    def is_new(self, ann_id: str) -> bool:
        """새 공고인지 확인한다."""
        return ann_id not in self.data["seen_ids"]

    def mark_seen(self, ann_id: str):
        """확인한 공고로 기록한다 (메모리만, 디스크 쓰기 안 함)."""
        if ann_id in self.data["seen_ids"]:
            return
        self.data["seen_ids"].append(ann_id)
        if len(self.data["seen_ids"]) > 500:
            self.data["seen_ids"] = self.data["seen_ids"][-500:]

    def update_check_time(self):
        """마지막 체크 시간을 갱신하고 파일에 저장한다."""
        self.data["last_check"] = datetime.now().isoformat()
        self.save()

    def save(self):
        """현재 상태를 JSON 파일에 저장한다."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


# ── LHCrawler ──────────────────────────────────────────────


class LHCrawler:
    """3개 데이터 소스에서 공고를 수집하여 통일된 형식으로 반환한다."""

    API_URL = "http://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"
    JSON_URL = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancListJson.do"
    HTML_URL = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026"
    DETAIL_URL = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancView.do?panId={}"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://apply.lh.or.kr",
        })

    def fetch_api(self, api_key: str) -> list[dict]:
        """공공데이터포털 API로 공고를 조회한다."""
        try:
            resp = self.session.get(
                self.API_URL,
                params={"ServiceKey": api_key, "pageNo": 1, "numOfRows": 30, "type": "json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data["response"]["body"]["items"]
            if not items or not items.get("item"):
                return []
            item_list = items["item"]
            if isinstance(item_list, dict):
                item_list = [item_list]

            results = []
            for it in item_list:
                results.append({
                    "id": str(it.get("sn", "")),
                    "title": it.get("sj", ""),
                    "rental_type": it.get("typeCdNm", ""),
                    "status": "",
                    "reg_date": normalize_date(it.get("crtDt", "")),
                    "rcpt_begin": normalize_date(it.get("rceptBgnDt", "")),
                    "rcpt_end": normalize_date(it.get("rceptEndDt", "")),
                    "url": it.get("dtlUrl", ""),
                })
            logger.info("공공데이터 API: %d개 수집", len(results))
            return results
        except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("공공데이터 API 조회 실패: %s", e)
            return []

    def fetch_web(self) -> list[dict]:
        """LH 사이트에서 공고를 수집한다 (JSON API → HTML 크롤링 폴백)."""
        # 1차: JSON API
        try:
            result = self._fetch_json_api()
            if result:
                return result
        except Exception as e:
            logger.warning("LH JSON API 실패, HTML 크롤링으로 폴백: %s", e)

        # 2차: HTML 크롤링
        try:
            return self._fetch_html()
        except Exception as e:
            logger.error("HTML 크롤링도 실패: %s", e)
            return []

    def _fetch_json_api(self) -> list[dict]:
        """LH 내부 JSON API로 공고를 조회한다."""
        resp = self.session.post(
            self.JSON_URL,
            data={"pg": 1, "pgSz": 30, "uppAisTpCd": 13},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("dsList") or data.get("list")
        if not items:
            raise ValueError("JSON API 응답에 dsList/list 키 없음")

        results = []
        for it in items:
            pan_id = it.get("panId") or it.get("PAN_ID", "")
            type_cd = it.get("aisTpCd") or it.get("AIS_TP_CD", "")
            results.append({
                "id": str(pan_id),
                "title": it.get("panNm") or it.get("PAN_NM", ""),
                "rental_type": RENTAL_TYPES.get(type_cd, type_cd),
                "status": it.get("panSttNm") or it.get("PAN_STT_NM", ""),
                "reg_date": normalize_date(it.get("dttmRgst") or it.get("DTTM_RGST", "")),
                "rcpt_begin": normalize_date(it.get("clsgBgnDt") or it.get("CLSG_BGN_DT", "")),
                "rcpt_end": normalize_date(it.get("clsgEndDt") or it.get("CLSG_END_DT", "")),
                "url": self.DETAIL_URL.format(pan_id),
            })
        logger.info("JSON API: %d개 수집", len(results))
        return results

    def _fetch_html(self) -> list[dict]:
        """LH 웹페이지를 HTML 크롤링하여 공고를 수집한다."""
        resp = self.session.get(self.HTML_URL, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = (
            soup.select("table tbody tr")
            or soup.select(".board-list tbody tr")
            or soup.select(".tbl_list tbody tr")
        )
        if not rows:
            return []

        results = []
        for row in rows:
            cols = row.find_all("td")
            if not cols:
                continue
            # 제목 및 링크 추출
            link = row.find("a")
            title = link.get_text(strip=True) if link else cols[0].get_text(strip=True)
            ann_id = self._extract_id(link, title)

            # 컬럼에서 데이터 추출 (컬럼 수가 다를 수 있으므로 안전하게)
            def col_text(idx):
                return cols[idx].get_text(strip=True) if idx < len(cols) else ""

            results.append({
                "id": ann_id,
                "title": title,
                "rental_type": col_text(1),
                "reg_date": normalize_date(col_text(2)),
                "rcpt_begin": normalize_date(col_text(3)),
                "rcpt_end": normalize_date(col_text(4)),
                "status": col_text(5),
                "url": self.DETAIL_URL.format(ann_id),
            })
        logger.info("HTML 크롤링: %d개 수집", len(results))
        return results

    @staticmethod
    def _extract_id(link, title: str) -> str:
        """<a> 태그에서 공고 ID를 추출한다."""
        if link:
            href = link.get("href", "")
            # panId= 파라미터
            m = re.search(r"panId=([^&]+)", href)
            if m:
                return m.group(1)
            # JavaScript 함수 호출에서 숫자 ID
            m = re.search(r"['\"](\d+)['\"]", href)
            if m:
                return m.group(1)
        # fallback: 제목의 MD5 해시 앞 16자
        return hashlib.md5(title.encode("utf-8")).hexdigest()[:16]


# ── TelegramNotifier ────────────────────────────────────────


class TelegramNotifier:
    """Telegram Bot API를 통해 알림 메시지를 발송한다."""

    API_URL = "https://api.telegram.org/bot{}/sendMessage"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)

    def send(self, announcements: list[dict]):
        """공고별 개별 HTML 메시지를 발송한다."""
        if not self.enabled:
            return
        for ann in announcements:
            msg = (
                f"🏠 <b>LH 임대주택 새 공고</b>\n\n"
                f"📋 <b>{ann.get('title', '')}</b>\n"
                f"🏷 유형: {ann.get('rental_type', '')}\n"
                f"🟢 상태: {ann.get('status', '')}\n"
                f"📅 공고일: {ann.get('reg_date', '')}\n"
                f"📆 접수: {ann.get('rcpt_begin', '')} ~ {ann.get('rcpt_end', '')}\n\n"
                f"🔗 <a href=\"{ann.get('url', '')}\">공고 상세보기</a>"
            )
            try:
                requests.post(
                    self.API_URL.format(self.token),
                    json={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
                logger.info("TG ✅ %s...", ann.get("title", "")[:20])
            except Exception as e:
                logger.warning("TG 발송 실패: %s", e)
            time.sleep(0.5)

    def send_text(self, text: str):
        """텍스트를 직접 발송한다."""
        if not self.enabled:
            return
        try:
            requests.post(
                self.API_URL.format(self.token),
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            logger.warning("TG 텍스트 발송 실패: %s", e)


# ── DiscordNotifier ─────────────────────────────────────────


class DiscordNotifier:
    """Discord Webhook을 통해 Embed 형식 알림을 발송한다."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)

    @staticmethod
    def _get_color(status: str) -> int:
        """공고 상태에 따라 Embed 색상을 반환한다."""
        if "접수중" in status or "공고중" in status:
            return 0x00FF00
        if "접수예정" in status:
            return 0x0099FF
        if "마감" in status:
            return 0xFF0000
        return 0x808080

    def send(self, announcements: list[dict]):
        """공고별 Embed를 발송한다."""
        if not self.enabled:
            return
        for ann in announcements:
            embed = {
                "title": f"🏠 {ann.get('title', '')}",
                "url": ann.get("url", ""),
                "color": self._get_color(ann.get("status", "")),
                "fields": [
                    {"name": "🏷 임대유형", "value": ann.get("rental_type", "") or "-", "inline": True},
                    {"name": "🟢 상태", "value": ann.get("status", "") or "-", "inline": True},
                    {"name": "📅 공고일", "value": ann.get("reg_date", "") or "-", "inline": True},
                    {"name": "📆 접수기간", "value": f"{ann.get('rcpt_begin', '')} ~ {ann.get('rcpt_end', '')}", "inline": False},
                ],
                "footer": {"text": "LH 임대주택 공고 모니터링"},
                "timestamp": datetime.now().isoformat(),
            }
            try:
                resp = requests.post(
                    self.webhook_url,
                    json={"embeds": [embed]},
                    timeout=10,
                )
                if resp.status_code in (200, 204):
                    logger.info("DC ✅ %s...", ann.get("title", "")[:20])
                else:
                    logger.warning("DC 응답 코드 %d", resp.status_code)
            except Exception as e:
                logger.warning("DC 발송 실패: %s", e)
            time.sleep(0.5)

    def send_embed(self, embed: dict):
        """Embed를 직접 발송한다."""
        if not self.enabled:
            return
        try:
            requests.post(
                self.webhook_url,
                json={"embeds": [embed]},
                timeout=10,
            )
        except Exception as e:
            logger.warning("DC Embed 발송 실패: %s", e)


# ── DailySummary ────────────────────────────────────────────


class DailySummary:
    """하루 동안 발견된 새 공고를 누적하여 일일 요약 리포트를 생성한다."""

    def __init__(self, filepath="data/daily_summary.json"):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.data = {"date": "", "announcements": []}
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                logger.warning("daily_summary.json 파싱 실패, 초기값으로 대체합니다")

    def add(self, ann: dict):
        """새 공고를 추가한다. 날짜가 바뀌면 자동 리셋."""
        today = date.today().isoformat()
        if self.data["date"] != today:
            self.data["date"] = today
            self.data["announcements"] = []
        self.data["announcements"].append(ann)
        self.save()

    def get_tg_msg(self) -> str | None:
        """Telegram 요약 메시지를 생성한다. 공고가 없으면 None."""
        anns = self.data["announcements"]
        if not anns:
            return None
        lines = [f"📊 <b>LH 임대주택 일일 요약 ({self.data['date']})</b>\n"]
        for a in anns:
            lines.append(f"• {a.get('title', '')} [{a.get('rental_type', '')}]")
        lines.append(f"\n총 {len(anns)}건")
        return "\n".join(lines)

    def get_dc_embed(self) -> dict | None:
        """Discord 요약 Embed를 생성한다. 공고가 없으면 None."""
        anns = self.data["announcements"]
        if not anns:
            return None
        desc_lines = [f"• {a.get('title', '')} [{a.get('rental_type', '')}]" for a in anns]
        return {
            "title": f"📊 LH 임대주택 일일 요약 ({self.data['date']})",
            "description": "\n".join(desc_lines),
            "color": 0x0099FF,
            "footer": {"text": f"총 {len(anns)}건"},
            "timestamp": datetime.now().isoformat(),
        }

    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


# ── LHMonitor ──────────────────────────────────────────────


class LHMonitor:
    """전체 모니터링 루프를 관리하는 오케스트레이터."""

    def __init__(self):
        data_dir = os.getenv("DATA_DIR", "./data")
        self.store = DataStore(os.path.join(data_dir, "seen.json"))
        self.crawler = LHCrawler()
        self.tg = TelegramNotifier(
            os.getenv("TELEGRAM_BOT_TOKEN", ""),
            os.getenv("TELEGRAM_CHAT_ID", ""),
        )
        self.dc = DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL", ""))
        self.summary = DailySummary(os.path.join(data_dir, "daily_summary.json"))
        self.api_key = os.getenv("DATA_GO_KR_API_KEY", "")
        self.interval = int(os.getenv("CHECK_INTERVAL", "1800"))
        self.daily_sent_date = ""

    def check_once(self) -> list[dict]:
        """한 번 체크하여 새 공고를 알림 발송하고 반환한다."""
        # 데이터 수집 (폴백 전략)
        if self.api_key:
            announcements = self.crawler.fetch_api(self.api_key)
            if not announcements:
                announcements = self.crawler.fetch_web()
        else:
            announcements = self.crawler.fetch_web()

        # 지역 필터링 (부산)
        announcements = [a for a in announcements if "부산" in a.get("title", "")]

        # 중복 필터링
        new_list = []
        for ann in announcements:
            if self.store.is_new(ann["id"]):
                new_list.append(ann)
                self.store.mark_seen(ann["id"])
                self.summary.add(ann)

        self.store.update_check_time()

        if new_list:
            logger.info("🆕 새 공고 %d건!", len(new_list))
            self.tg.send(new_list)
            self.dc.send(new_list)
        else:
            logger.info("새 공고 없음")

        return new_list

    def send_daily_summary(self):
        """일일 요약 리포트를 발송한다."""
        tg_msg = self.summary.get_tg_msg()
        if tg_msg:
            self.tg.send_text(tg_msg)
        dc_embed = self.summary.get_dc_embed()
        if dc_embed:
            self.dc.send_embed(dc_embed)
        self.daily_sent_date = date.today().isoformat()
        logger.info("일일 요약 발송 완료")

    def run(self):
        """메인 무한 루프."""
        source = "공공데이터 API + 웹크롤링" if self.api_key else "웹크롤링"
        logger.info("🏠 LH 임대주택 공고 모니터링 봇 시작")
        logger.info("⏱  간격: %d초 (%d분)", self.interval, self.interval // 60)
        logger.info("📬 TG: %s  DC: %s",
                     "✅" if self.tg.enabled else "❌",
                     "✅" if self.dc.enabled else "❌")
        logger.info("🔑 방식: %s", source)

        if not self.tg.enabled and not self.dc.enabled:
            logger.error("알림 채널이 하나도 설정되지 않았습니다. 종료합니다.")
            sys.exit(1)
            return

        # 최초 실행 판단
        if not self.store.data.get("last_check"):
            logger.info("최초 실행: 기존 공고를 기록합니다 (알림 미발송)")
            if self.api_key:
                anns = self.crawler.fetch_api(self.api_key)
                if not anns:
                    anns = self.crawler.fetch_web()
            else:
                anns = self.crawler.fetch_web()
            anns = [a for a in anns if "부산" in a.get("title", "")]
            for ann in anns:
                self.store.mark_seen(ann["id"])
            self.store.update_check_time()
            logger.info("기존 공고 %d건 기록 완료", len(anns))
        else:
            self.check_once()

        # 메인 루프
        while True:
            try:
                time.sleep(self.interval)
                self.check_once()
                # 21시 일일 요약
                now = datetime.now()
                if now.hour == 21 and self.daily_sent_date != date.today().isoformat():
                    self.send_daily_summary()
            except KeyboardInterrupt:
                logger.info("⛔ 종료")
                sys.exit(0)
            except Exception as e:
                logger.error("예외 발생: %s", e)
                time.sleep(60)


# ── 메인 진입점 ─────────────────────────────────────────────

if __name__ == "__main__":
    LHMonitor().run()
