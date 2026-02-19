# -*- coding: utf-8 -*-
"""normalize_date() 및 RENTAL_TYPES 단위 테스트"""

from lh_monitor import normalize_date, RENTAL_TYPES


class TestNormalizeDate:
    """normalize_date() 함수 테스트"""

    def test_eight_digits(self):
        """8자리 숫자 → YYYY-MM-DD"""
        assert normalize_date("20250219") == "2025-02-19"

    def test_slash_separated(self):
        """슬래시 구분 → YYYY-MM-DD"""
        assert normalize_date("2025/02/19") == "2025-02-19"

    def test_already_normalized(self):
        """이미 정규형이면 그대로 반환"""
        assert normalize_date("2025-02-19") == "2025-02-19"

    def test_empty_string(self):
        """빈 문자열 → 빈 문자열"""
        assert normalize_date("") == ""

    def test_dot_separated(self):
        """점 구분 → YYYY-MM-DD"""
        assert normalize_date("2025.02.19") == "2025-02-19"


class TestRentalTypes:
    """RENTAL_TYPES 상수 검증"""

    def test_kukmin(self):
        assert RENTAL_TYPES["01"] == "국민임대"

    def test_haengbok(self):
        assert RENTAL_TYPES["04"] == "행복주택"

    def test_total_count(self):
        assert len(RENTAL_TYPES) == 10
