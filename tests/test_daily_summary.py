# -*- coding: utf-8 -*-
"""DailySummary 단위 테스트"""

import json
from datetime import date

from lh_monitor import DailySummary

SAMPLE_ANN = {
    "id": "12345",
    "title": "파주운정 국민임대",
    "rental_type": "국민임대",
    "status": "접수중",
    "reg_date": "2026-02-19",
    "rcpt_begin": "2026-03-01",
    "rcpt_end": "2026-03-15",
    "url": "https://apply.lh.or.kr/detail/12345",
}


class TestDailySummaryAdd:
    def test_add_appends(self, tmp_path):
        """add() 후 announcements에 공고가 추가된다."""
        ds = DailySummary(str(tmp_path / "daily.json"))
        ds.add(SAMPLE_ANN)
        assert len(ds.data["announcements"]) == 1
        assert ds.data["announcements"][0]["id"] == "12345"

    def test_date_change_resets(self, tmp_path):
        """날짜가 다르면 add() 시 리스트가 자동 리셋된다."""
        ds = DailySummary(str(tmp_path / "daily.json"))
        ds.data["date"] = "2020-01-01"
        ds.data["announcements"] = [{"id": "old"}]
        ds.add(SAMPLE_ANN)
        # 날짜가 오늘로 갱신되고 old 항목은 사라짐
        assert ds.data["date"] == date.today().isoformat()
        assert len(ds.data["announcements"]) == 1
        assert ds.data["announcements"][0]["id"] == "12345"


class TestDailySummaryGetTgMsg:
    def test_returns_string_with_announcements(self, tmp_path):
        """공고가 있으면 문자열을 반환한다."""
        ds = DailySummary(str(tmp_path / "daily.json"))
        ds.add(SAMPLE_ANN)
        msg = ds.get_tg_msg()
        assert msg is not None
        assert isinstance(msg, str)
        assert "파주운정" in msg

    def test_returns_none_when_empty(self, tmp_path):
        """공고가 없으면 None을 반환한다."""
        ds = DailySummary(str(tmp_path / "daily.json"))
        assert ds.get_tg_msg() is None


class TestDailySummaryGetDcEmbed:
    def test_returns_dict_with_announcements(self, tmp_path):
        """공고가 있으면 dict를 반환한다."""
        ds = DailySummary(str(tmp_path / "daily.json"))
        ds.add(SAMPLE_ANN)
        embed = ds.get_dc_embed()
        assert embed is not None
        assert isinstance(embed, dict)
        assert "title" in embed
        assert "color" in embed

    def test_returns_none_when_empty(self, tmp_path):
        """공고가 없으면 None을 반환한다."""
        ds = DailySummary(str(tmp_path / "daily.json"))
        assert ds.get_dc_embed() is None


class TestDailySummaryPersistence:
    def test_reload_preserves_data(self, tmp_path):
        """파일 재로드 후 데이터가 유지된다."""
        fp = str(tmp_path / "daily.json")
        ds = DailySummary(fp)
        ds.add(SAMPLE_ANN)
        ds2 = DailySummary(fp)
        assert len(ds2.data["announcements"]) == 1
