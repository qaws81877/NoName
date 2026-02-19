# -*- coding: utf-8 -*-
"""LHCrawler 모킹 기반 단위 테스트"""

import json
from unittest.mock import patch, MagicMock

import requests

from lh_monitor import LHCrawler

EXPECTED_KEYS = {"id", "title", "rental_type", "status", "reg_date", "rcpt_begin", "rcpt_end", "url"}


# ── 기본 구조 ───────────────────────────────────────────────


class TestLHCrawlerInit:
    def test_session_is_requests_session(self):
        c = LHCrawler()
        assert isinstance(c.session, requests.Session)

    def test_session_has_user_agent(self):
        c = LHCrawler()
        assert "User-Agent" in c.session.headers

    def test_session_has_accept_language(self):
        c = LHCrawler()
        assert "Accept-Language" in c.session.headers

    def test_session_has_referer(self):
        c = LHCrawler()
        assert "Referer" in c.session.headers


# ── fetch_api ────────────────────────────────────────────────


def _make_api_response(items):
    """공공데이터포털 API 응답 형식의 dict를 만든다."""
    return {"response": {"body": {"items": {"item": items}}}}


API_ITEM = {
    "sn": "12345",
    "sj": "파주운정 국민임대",
    "typeCdNm": "국민임대",
    "crtDt": "20260219",
    "rceptBgnDt": "20260301",
    "rceptEndDt": "20260315",
    "dtlUrl": "https://apply.lh.or.kr/detail/12345",
}


class TestFetchApi:
    @patch.object(requests.Session, "get")
    def test_normal_list_response(self, mock_get):
        """items.item이 리스트인 정상 응답 → 공고 리스트 반환."""
        resp = MagicMock()
        resp.json.return_value = _make_api_response([API_ITEM])
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_api("fake_key")
        assert len(result) == 1
        assert set(result[0].keys()) == EXPECTED_KEYS
        assert result[0]["id"] == "12345"
        assert result[0]["reg_date"] == "2026-02-19"

    @patch.object(requests.Session, "get")
    def test_single_dict_response(self, mock_get):
        """items.item이 단일 dict → 리스트로 변환."""
        resp = MagicMock()
        resp.json.return_value = _make_api_response(API_ITEM)
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_api("fake_key")
        assert len(result) == 1

    @patch.object(requests.Session, "get")
    def test_empty_response(self, mock_get):
        """빈 응답 → 빈 리스트."""
        resp = MagicMock()
        resp.json.return_value = {"response": {"body": {"items": ""}}}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_api("fake_key")
        assert result == []

    @patch.object(requests.Session, "get")
    def test_http_error(self, mock_get):
        """HTTP 에러 → 빈 리스트."""
        mock_get.side_effect = requests.RequestException("timeout")
        result = LHCrawler().fetch_api("fake_key")
        assert result == []

    @patch.object(requests.Session, "get")
    def test_json_decode_error(self, mock_get):
        """JSON 파싱 에러 → 빈 리스트."""
        resp = MagicMock()
        resp.json.side_effect = json.JSONDecodeError("err", "", 0)
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_api("fake_key")
        assert result == []


# ── fetch_web: JSON API ──────────────────────────────────────


JSON_ITEM_CAMEL = {
    "panId": "A001",
    "panNm": "행복주택 공고",
    "aisTpCd": "04",
    "panSttNm": "접수중",
    "dttmRgst": "20260219",
    "clsgBgnDt": "20260301",
    "clsgEndDt": "20260315",
}

JSON_ITEM_UPPER = {
    "PAN_ID": "B002",
    "PAN_NM": "영구임대 공고",
    "AIS_TP_CD": "03",
    "PAN_STT_NM": "접수예정",
    "DTTM_RGST": "2026/02/19",
    "CLSG_BGN_DT": "2026/03/01",
    "CLSG_END_DT": "2026/03/15",
}


class TestFetchWebJsonApi:
    @patch.object(requests.Session, "post")
    def test_dslist_key(self, mock_post):
        """dsList 키 응답 → 공고 리스트 반환."""
        resp = MagicMock()
        resp.json.return_value = {"dsList": [JSON_ITEM_CAMEL]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        result = LHCrawler().fetch_web()
        assert len(result) == 1
        assert set(result[0].keys()) == EXPECTED_KEYS

    @patch.object(requests.Session, "post")
    def test_list_key(self, mock_post):
        """list 키 응답 → 공고 리스트 반환."""
        resp = MagicMock()
        resp.json.return_value = {"list": [JSON_ITEM_CAMEL]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        result = LHCrawler().fetch_web()
        assert len(result) == 1

    @patch.object(requests.Session, "post")
    def test_camel_case_fields(self, mock_post):
        """camelCase 필드 정상 파싱."""
        resp = MagicMock()
        resp.json.return_value = {"dsList": [JSON_ITEM_CAMEL]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        item = LHCrawler().fetch_web()[0]
        assert item["id"] == "A001"
        assert item["title"] == "행복주택 공고"
        assert item["rental_type"] == "행복주택"
        assert item["status"] == "접수중"

    @patch.object(requests.Session, "post")
    def test_upper_snake_fields(self, mock_post):
        """UPPER_SNAKE 필드 정상 파싱."""
        resp = MagicMock()
        resp.json.return_value = {"dsList": [JSON_ITEM_UPPER]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        item = LHCrawler().fetch_web()[0]
        assert item["id"] == "B002"
        assert item["title"] == "영구임대 공고"
        assert item["rental_type"] == "영구임대"

    @patch.object(requests.Session, "post")
    def test_rental_type_code_mapping(self, mock_post):
        """임대유형 코드 → 한국어 이름 변환."""
        resp = MagicMock()
        resp.json.return_value = {"dsList": [JSON_ITEM_CAMEL]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        item = LHCrawler().fetch_web()[0]
        assert item["rental_type"] == "행복주택"

    @patch.object(requests.Session, "post")
    def test_date_normalization(self, mock_post):
        """날짜 정규화 적용 확인."""
        resp = MagicMock()
        resp.json.return_value = {"dsList": [JSON_ITEM_UPPER]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        item = LHCrawler().fetch_web()[0]
        assert item["reg_date"] == "2026-02-19"
        assert item["rcpt_begin"] == "2026-03-01"


# ── fetch_web: HTML 크롤링 ───────────────────────────────────


HTML_WITH_PANID = """
<html><body>
<table><tbody>
<tr>
  <td><a href="selectWrtancView.do?panId=C003">공공임대 공고</a></td>
  <td>공공임대</td>
  <td>2026-02-19</td>
  <td>2026-03-01</td>
  <td>2026-03-15</td>
  <td>접수중</td>
</tr>
</tbody></table>
</body></html>
"""

HTML_WITH_JS = """
<html><body>
<table><tbody>
<tr>
  <td><a href="javascript:goDetail('99887')">전세임대 공고</a></td>
  <td>전세임대</td>
  <td>2026-02-18</td>
  <td>2026-03-01</td>
  <td>2026-03-15</td>
  <td>접수예정</td>
</tr>
</tbody></table>
</body></html>
"""

HTML_NO_HREF = """
<html><body>
<table><tbody>
<tr>
  <td>매입임대 공고</td>
  <td>매입임대</td>
  <td>2026-02-17</td>
  <td></td>
  <td></td>
  <td>접수마감</td>
</tr>
</tbody></table>
</body></html>
"""

HTML_EMPTY_TABLE = """
<html><body>
<table><tbody>
</tbody></table>
</body></html>
"""


class TestFetchWebHtml:
    @patch.object(requests.Session, "get")
    @patch.object(requests.Session, "post")
    def test_panid_param_extraction(self, mock_post, mock_get):
        """panId= 파라미터 포함 href → ID 정상 추출."""
        # JSON API 실패시키기
        mock_post.side_effect = Exception("JSON API fail")
        # HTML 응답
        resp = MagicMock()
        resp.text = HTML_WITH_PANID
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_web()
        assert len(result) == 1
        assert result[0]["id"] == "C003"
        assert set(result[0].keys()) == EXPECTED_KEYS

    @patch.object(requests.Session, "get")
    @patch.object(requests.Session, "post")
    def test_js_function_extraction(self, mock_post, mock_get):
        """JavaScript 함수 호출 href → 정규식으로 숫자 ID 추출."""
        mock_post.side_effect = Exception("JSON API fail")
        resp = MagicMock()
        resp.text = HTML_WITH_JS
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_web()
        assert len(result) == 1
        assert result[0]["id"] == "99887"

    @patch.object(requests.Session, "get")
    @patch.object(requests.Session, "post")
    def test_md5_fallback(self, mock_post, mock_get):
        """href 없는 행 → MD5 해시 fallback ID."""
        mock_post.side_effect = Exception("JSON API fail")
        resp = MagicMock()
        resp.text = HTML_NO_HREF
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_web()
        assert len(result) == 1
        assert len(result[0]["id"]) == 16  # MD5 해시 앞 16자

    @patch.object(requests.Session, "get")
    @patch.object(requests.Session, "post")
    def test_empty_table(self, mock_post, mock_get):
        """빈 테이블 → 빈 리스트."""
        mock_post.side_effect = Exception("JSON API fail")
        resp = MagicMock()
        resp.text = HTML_EMPTY_TABLE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_web()
        assert result == []


# ── 폴백 체인 ────────────────────────────────────────────────


class TestFallbackChain:
    @patch.object(requests.Session, "get")
    @patch.object(requests.Session, "post")
    def test_json_api_success_skips_html(self, mock_post, mock_get):
        """JSON API 성공 → HTML 크롤링(GET) 호출 안 됨."""
        resp = MagicMock()
        resp.json.return_value = {"dsList": [JSON_ITEM_CAMEL]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        LHCrawler().fetch_web()
        mock_get.assert_not_called()

    @patch.object(requests.Session, "get")
    @patch.object(requests.Session, "post")
    def test_json_api_fail_falls_back_to_html(self, mock_post, mock_get):
        """JSON API 실패 → HTML 크롤링으로 폴백."""
        mock_post.side_effect = Exception("JSON API fail")
        resp = MagicMock()
        resp.text = HTML_WITH_PANID
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = LHCrawler().fetch_web()
        mock_get.assert_called_once()
        assert len(result) == 1
