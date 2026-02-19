# -*- coding: utf-8 -*-
"""TelegramNotifier / DiscordNotifier 모킹 기반 단위 테스트"""

from unittest.mock import patch, MagicMock, call

from lh_monitor import TelegramNotifier, DiscordNotifier

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


# ── TelegramNotifier ─────────────────────────────────────────


class TestTelegramEnabled:
    def test_both_set_enabled(self):
        tg = TelegramNotifier("tok", "123")
        assert tg.enabled is True

    def test_missing_token_disabled(self):
        tg = TelegramNotifier("", "123")
        assert tg.enabled is False

    def test_missing_chat_id_disabled(self):
        tg = TelegramNotifier("tok", "")
        assert tg.enabled is False


class TestTelegramSend:
    @patch("lh_monitor.requests.post")
    def test_disabled_no_http(self, mock_post):
        """enabled=False이면 HTTP 요청을 하지 않는다."""
        tg = TelegramNotifier("", "")
        tg.send([SAMPLE_ANN])
        mock_post.assert_not_called()

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_sends_correct_api_url(self, mock_post, _sleep):
        """올바른 Telegram API URL로 POST 요청을 보낸다."""
        mock_post.return_value = MagicMock(status_code=200)
        tg = TelegramNotifier("MYTOKEN", "999")
        tg.send([SAMPLE_ANN])
        args, kwargs = mock_post.call_args
        assert "bot" + "MYTOKEN" in args[0]
        assert "/sendMessage" in args[0]

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_payload_has_html_parse_mode(self, mock_post, _sleep):
        """parse_mode가 HTML로 설정된다."""
        mock_post.return_value = MagicMock(status_code=200)
        tg = TelegramNotifier("tok", "123")
        tg.send([SAMPLE_ANN])
        payload = mock_post.call_args[1].get("json") or mock_post.call_args[1].get("data")
        assert payload["parse_mode"] == "HTML"

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_message_contains_html_tags(self, mock_post, _sleep):
        """메시지에 HTML 태그가 포함된다."""
        mock_post.return_value = MagicMock(status_code=200)
        tg = TelegramNotifier("tok", "123")
        tg.send([SAMPLE_ANN])
        payload = mock_post.call_args[1].get("json") or mock_post.call_args[1].get("data")
        text = payload["text"]
        assert "<b>" in text
        assert "<a href=" in text

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_send_failure_no_exception(self, mock_post, _sleep):
        """발송 실패 시 예외가 전파되지 않는다."""
        mock_post.side_effect = Exception("network error")
        tg = TelegramNotifier("tok", "123")
        tg.send([SAMPLE_ANN])  # 예외 없이 통과

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_send_text(self, mock_post, _sleep):
        """send_text()가 텍스트를 그대로 전송한다."""
        mock_post.return_value = MagicMock(status_code=200)
        tg = TelegramNotifier("tok", "123")
        tg.send_text("hello")
        payload = mock_post.call_args[1].get("json") or mock_post.call_args[1].get("data")
        assert payload["text"] == "hello"

    @patch("lh_monitor.requests.post")
    def test_send_text_disabled_no_http(self, mock_post):
        """enabled=False이면 send_text도 HTTP 요청 안 한다."""
        tg = TelegramNotifier("", "")
        tg.send_text("hello")
        mock_post.assert_not_called()


# ── DiscordNotifier ──────────────────────────────────────────


class TestDiscordEnabled:
    def test_url_set_enabled(self):
        dc = DiscordNotifier("https://discord.com/api/webhooks/xxx")
        assert dc.enabled is True

    def test_empty_url_disabled(self):
        dc = DiscordNotifier("")
        assert dc.enabled is False


class TestDiscordSend:
    @patch("lh_monitor.requests.post")
    def test_disabled_no_http(self, mock_post):
        """enabled=False이면 HTTP 요청을 하지 않는다."""
        dc = DiscordNotifier("")
        dc.send([SAMPLE_ANN])
        mock_post.assert_not_called()

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_embed_has_required_fields(self, mock_post, _sleep):
        """Embed JSON에 title, url, color, fields, footer, timestamp가 포함된다."""
        resp = MagicMock(status_code=204)
        mock_post.return_value = resp
        dc = DiscordNotifier("https://hook")
        dc.send([SAMPLE_ANN])
        payload = mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "title" in embed
        assert "url" in embed
        assert "color" in embed
        assert "fields" in embed
        assert "footer" in embed
        assert "timestamp" in embed

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_color_accepting(self, mock_post, _sleep):
        """접수중 → 0x00FF00."""
        mock_post.return_value = MagicMock(status_code=204)
        dc = DiscordNotifier("https://hook")
        ann = {**SAMPLE_ANN, "status": "접수중"}
        dc.send([ann])
        embed = mock_post.call_args[1]["json"]["embeds"][0]
        assert embed["color"] == 0x00FF00

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_color_upcoming(self, mock_post, _sleep):
        """접수예정 → 0x0099FF."""
        mock_post.return_value = MagicMock(status_code=204)
        dc = DiscordNotifier("https://hook")
        ann = {**SAMPLE_ANN, "status": "접수예정"}
        dc.send([ann])
        embed = mock_post.call_args[1]["json"]["embeds"][0]
        assert embed["color"] == 0x0099FF

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_color_closed(self, mock_post, _sleep):
        """접수마감 → 0xFF0000."""
        mock_post.return_value = MagicMock(status_code=204)
        dc = DiscordNotifier("https://hook")
        ann = {**SAMPLE_ANN, "status": "접수마감"}
        dc.send([ann])
        embed = mock_post.call_args[1]["json"]["embeds"][0]
        assert embed["color"] == 0xFF0000

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_response_200_and_204_both_ok(self, mock_post, _sleep):
        """응답 코드 200, 204 모두 성공 처리."""
        for code in (200, 204):
            mock_post.return_value = MagicMock(status_code=code)
            dc = DiscordNotifier("https://hook")
            dc.send([SAMPLE_ANN])  # 예외 없이 통과

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_send_failure_no_exception(self, mock_post, _sleep):
        """발송 실패 시 예외가 전파되지 않는다."""
        mock_post.side_effect = Exception("network error")
        dc = DiscordNotifier("https://hook")
        dc.send([SAMPLE_ANN])  # 예외 없이 통과

    @patch("lh_monitor.time.sleep")
    @patch("lh_monitor.requests.post")
    def test_send_embed(self, mock_post, _sleep):
        """send_embed()가 Embed를 직접 전송한다."""
        mock_post.return_value = MagicMock(status_code=200)
        dc = DiscordNotifier("https://hook")
        embed = {"title": "요약", "color": 0x0099FF}
        dc.send_embed(embed)
        payload = mock_post.call_args[1]["json"]
        assert payload["embeds"][0]["title"] == "요약"

    @patch("lh_monitor.requests.post")
    def test_send_embed_disabled_no_http(self, mock_post):
        """enabled=False이면 send_embed도 HTTP 요청 안 한다."""
        dc = DiscordNotifier("")
        dc.send_embed({"title": "test"})
        mock_post.assert_not_called()
