# -*- coding: utf-8 -*-
"""DataStore 단위 테스트"""

import json
import os

from lh_monitor import DataStore


class TestDataStoreInit:
    """DataStore 초기화 테스트"""

    def test_creates_directory(self, tmp_path):
        """생성 시 디렉토리를 자동으로 만든다."""
        fp = tmp_path / "sub" / "seen.json"
        DataStore(str(fp))
        assert fp.parent.exists()

    def test_initializes_default_data(self, tmp_path):
        """파일이 없으면 기본값으로 초기화한다."""
        fp = tmp_path / "seen.json"
        ds = DataStore(str(fp))
        assert ds.data["seen_ids"] == []
        assert ds.data["last_check"] is None

    def test_loads_existing_file(self, tmp_path):
        """기존 JSON 파일이 있으면 로드한다."""
        fp = tmp_path / "seen.json"
        fp.write_text(json.dumps({"seen_ids": ["a", "b"], "last_check": "2026-01-01T00:00:00"}))
        ds = DataStore(str(fp))
        assert ds.data["seen_ids"] == ["a", "b"]
        assert ds.data["last_check"] == "2026-01-01T00:00:00"

    def test_corrupted_json_falls_back(self, tmp_path):
        """손상된 JSON 파일은 초기값으로 대체한다."""
        fp = tmp_path / "seen.json"
        fp.write_text("{invalid json!!!")
        ds = DataStore(str(fp))
        assert ds.data["seen_ids"] == []
        assert ds.data["last_check"] is None


class TestIsNew:
    """is_new() 메서드 테스트"""

    def test_new_id_returns_true(self, tmp_path):
        ds = DataStore(str(tmp_path / "seen.json"))
        assert ds.is_new("test1") is True

    def test_seen_id_returns_false(self, tmp_path):
        ds = DataStore(str(tmp_path / "seen.json"))
        ds.mark_seen("test1")
        assert ds.is_new("test1") is False


class TestMarkSeen:
    """mark_seen() 메서드 테스트"""

    def test_adds_id(self, tmp_path):
        ds = DataStore(str(tmp_path / "seen.json"))
        ds.mark_seen("x")
        assert "x" in ds.data["seen_ids"]

    def test_duplicate_ignored(self, tmp_path):
        """중복 호출 시 리스트 길이가 변하지 않는다."""
        ds = DataStore(str(tmp_path / "seen.json"))
        ds.mark_seen("x")
        ds.mark_seen("x")
        assert ds.data["seen_ids"].count("x") == 1

    def test_max_500_limit(self, tmp_path):
        """501개 삽입 후 길이는 500이다."""
        ds = DataStore(str(tmp_path / "seen.json"))
        for i in range(501):
            ds.mark_seen(str(i))
        assert len(ds.data["seen_ids"]) == 500

    def test_oldest_removed_on_overflow(self, tmp_path):
        """501번째 삽입 시 첫 번째 ID가 삭제된다."""
        ds = DataStore(str(tmp_path / "seen.json"))
        for i in range(501):
            ds.mark_seen(str(i))
        assert "0" not in ds.data["seen_ids"]
        assert "500" in ds.data["seen_ids"]


class TestUpdateCheckTime:
    """update_check_time() 메서드 테스트"""

    def test_sets_iso_datetime(self, tmp_path):
        fp = tmp_path / "seen.json"
        ds = DataStore(str(fp))
        ds.update_check_time()
        assert ds.data["last_check"] is not None
        # ISO 8601 형식 확인 (YYYY-MM-DDTHH:MM:SS 패턴)
        assert "T" in ds.data["last_check"]

    def test_persists_to_file(self, tmp_path):
        """update_check_time() 후 파일에 저장된다."""
        fp = tmp_path / "seen.json"
        ds = DataStore(str(fp))
        ds.mark_seen("a")
        ds.update_check_time()
        # 파일 재로드
        ds2 = DataStore(str(fp))
        assert ds2.data["last_check"] is not None
        assert "a" in ds2.data["seen_ids"]
