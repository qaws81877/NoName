# -*- coding: utf-8 -*-
"""LHMonitor 통합 모킹 테스트"""

from unittest.mock import patch, MagicMock, PropertyMock

from lh_monitor import LHMonitor

SAMPLE_ANN = {
    "id": "12345",
    "title": "부산강서 국민임대",
    "rental_type": "국민임대",
    "status": "접수중",
    "reg_date": "2026-02-19",
    "rcpt_begin": "2026-03-01",
    "rcpt_end": "2026-03-15",
    "url": "https://apply.lh.or.kr/detail/12345",
}


def _make_monitor(**env_overrides):
    """환경변수를 모킹하여 LHMonitor를 생성한다."""
    defaults = {
        "DATA_DIR": "",
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "DISCORD_WEBHOOK_URL": "https://hook",
        "DATA_GO_KR_API_KEY": "",
        "CHECK_INTERVAL": "1800",
    }
    defaults.update(env_overrides)

    def fake_getenv(key, default=""):
        return defaults.get(key, default)

    return fake_getenv


# ── check_once 테스트 ────────────────────────────────────────


class TestCheckOnce:
    @patch("lh_monitor.os.getenv")
    def _build(self, mock_getenv, tmp_path, **env):
        mock_getenv.side_effect = _make_monitor(DATA_DIR=str(tmp_path), **env)
        return LHMonitor()

    def test_api_key_success_skips_web(self, tmp_path):
        """API 키 있음 + fetch_api 성공 → fetch_web 호출 안 됨."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path), DATA_GO_KR_API_KEY="mykey")
            mon = LHMonitor()
        mon.crawler.fetch_api = MagicMock(return_value=[SAMPLE_ANN])
        mon.crawler.fetch_web = MagicMock()
        mon.check_once()
        mon.crawler.fetch_api.assert_called_once()
        mon.crawler.fetch_web.assert_not_called()

    def test_api_key_empty_falls_back(self, tmp_path):
        """API 키 있음 + fetch_api 빈 결과 → fetch_web 폴백."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path), DATA_GO_KR_API_KEY="mykey")
            mon = LHMonitor()
        mon.crawler.fetch_api = MagicMock(return_value=[])
        mon.crawler.fetch_web = MagicMock(return_value=[SAMPLE_ANN])
        mon.check_once()
        mon.crawler.fetch_web.assert_called_once()

    def test_no_api_key_calls_web(self, tmp_path):
        """API 키 없음 → fetch_web 직접 호출."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path), DATA_GO_KR_API_KEY="")
            mon = LHMonitor()
        mon.crawler.fetch_api = MagicMock()
        mon.crawler.fetch_web = MagicMock(return_value=[])
        mon.check_once()
        mon.crawler.fetch_api.assert_not_called()
        mon.crawler.fetch_web.assert_called_once()

    def test_new_announcements_trigger_notify(self, tmp_path):
        """새 공고 있음 → tg.send()와 dc.send() 호출."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path))
            mon = LHMonitor()
        mon.crawler.fetch_web = MagicMock(return_value=[SAMPLE_ANN])
        mon.tg.send = MagicMock()
        mon.dc.send = MagicMock()
        mon.check_once()
        mon.tg.send.assert_called_once()
        mon.dc.send.assert_called_once()

    def test_no_new_announcements_no_notify(self, tmp_path):
        """새 공고 없음 → tg.send()와 dc.send() 호출 안 됨."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path))
            mon = LHMonitor()
        # 먼저 mark_seen
        mon.store.mark_seen("12345")
        mon.crawler.fetch_web = MagicMock(return_value=[SAMPLE_ANN])
        mon.tg.send = MagicMock()
        mon.dc.send = MagicMock()
        mon.check_once()
        mon.tg.send.assert_not_called()
        mon.dc.send.assert_not_called()

    def test_update_check_time_always_called(self, tmp_path):
        """check_once() 후 store.update_check_time()이 항상 호출된다."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path))
            mon = LHMonitor()
        mon.crawler.fetch_web = MagicMock(return_value=[])
        mon.store.update_check_time = MagicMock()
        mon.check_once()
        mon.store.update_check_time.assert_called_once()


# ── 초기화 및 최초 실행 테스트 ────────────────────────────────


class TestMonitorInit:
    def test_no_channels_logs_error_and_exits(self, tmp_path):
        """TG/DC 모두 미설정 시 에러 로그 + 조기 종료."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(
                DATA_DIR=str(tmp_path),
                TELEGRAM_BOT_TOKEN="",
                TELEGRAM_CHAT_ID="",
                DISCORD_WEBHOOK_URL="",
            )
            mon = LHMonitor()
        assert not mon.tg.enabled
        assert not mon.dc.enabled
        # run()이 sys.exit를 호출하는지 확인
        with patch("lh_monitor.sys.exit") as mock_exit:
            mon.run()
            mock_exit.assert_called()

    def test_first_run_marks_seen_no_notify(self, tmp_path):
        """last_check 없으면 최초 실행 모드 (알림 미발송, mark_seen만)."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path))
            mon = LHMonitor()
        assert mon.store.data.get("last_check") is None
        mon.crawler.fetch_web = MagicMock(return_value=[SAMPLE_ANN])
        mon.crawler.fetch_api = MagicMock(return_value=[])
        mon.tg.send = MagicMock()
        mon.dc.send = MagicMock()
        # run()이 최초 실행 후 sleep에서 KeyboardInterrupt로 종료하게 만듦
        with patch("lh_monitor.time.sleep", side_effect=KeyboardInterrupt):
            try:
                mon.run()
            except SystemExit:
                pass
        # 알림은 발송되지 않아야 함
        mon.tg.send.assert_not_called()
        mon.dc.send.assert_not_called()
        # 그러나 mark_seen은 되어야 함
        assert not mon.store.is_new("12345")

    def test_existing_last_check_calls_check_once(self, tmp_path):
        """last_check 있으면 즉시 check_once() 실행."""
        with patch("lh_monitor.os.getenv") as mg:
            mg.side_effect = _make_monitor(DATA_DIR=str(tmp_path))
            mon = LHMonitor()
        # last_check를 설정하여 최초 실행이 아닌 상태로 만듦
        mon.store.data["last_check"] = "2026-02-19T10:00:00"
        mon.crawler.fetch_web = MagicMock(return_value=[SAMPLE_ANN])
        mon.tg.send = MagicMock()
        mon.dc.send = MagicMock()
        with patch("lh_monitor.time.sleep", side_effect=KeyboardInterrupt):
            try:
                mon.run()
            except SystemExit:
                pass
        # check_once가 실행되어 새 공고 알림이 발송됨
        mon.tg.send.assert_called_once()
        mon.dc.send.assert_called_once()
