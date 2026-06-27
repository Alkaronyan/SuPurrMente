"""Tests for SQLiteStore: write, dedup, queries."""
from datetime import datetime, timedelta, timezone

import pytest

import timeutils

from classifier import ClassifiedVisit
from storage.sqlite_store import SQLiteStore

UTC = timezone.utc
NOW = timeutils.now().replace(microsecond=0)  # second precision matches SQLite DATE_FORMAT


def make_config(tmp_path):
    return {"storage": {"sqlite_path": str(tmp_path / "test.db")}}


def make_visit(cat: str, weight_kg: float, offset_hours: int = 0) -> ClassifiedVisit:
    return ClassifiedVisit(
        timestamp=NOW - timedelta(hours=offset_hours),
        cat=cat,
        weight_kg=weight_kg,
        raw_weight_kg=weight_kg,
        confidence=1.0,
    )


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(make_config(tmp_path))


class TestWrite:
    def test_write_creates_rows(self, store):
        store.write([make_visit("pirata", 6.5), make_visit("robin", 4.3, offset_hours=1)])
        history = store.load_history()
        assert len(history) == 2

    def test_deduplication_by_timestamp(self, store):
        visit = make_visit("pirata", 6.5)
        store.write([visit])
        store.write([visit])  # same timestamp → ignored
        assert len(store.load_history()) == 1

    def test_write_empty_list_is_noop(self, store):
        store.write([])
        assert store.last_timestamp() is None


class TestLastTimestamp:
    def test_none_when_empty(self, store):
        assert store.last_timestamp() is None

    def test_returns_most_recent(self, store):
        store.write([
            make_visit("pirata", 6.5, offset_hours=2),
            make_visit("robin", 4.3, offset_hours=1),
        ])
        last = store.last_timestamp()
        assert last == NOW - timedelta(hours=1)


class TestLoadHistory:
    def test_returns_within_30_days(self, store):
        store.write([make_visit("pirata", 6.5, offset_hours=10)])
        history = store.load_history()
        assert len(history) == 1
        assert history[0]["cat"] == "pirata"
        assert history[0]["weight_kg"] == pytest.approx(6.5)

    def test_timestamps_are_timezone_aware(self, store):
        store.write([make_visit("robin", 4.3)])
        history = store.load_history()
        assert history[0]["timestamp"].tzinfo is not None


class TestLoadHistoryForCat:
    def test_filters_by_cat(self, store):
        store.write([
            make_visit("pirata", 6.5, offset_hours=2),
            make_visit("robin", 4.3, offset_hours=1),
        ])
        pirata_history = store.load_history_for_cat("pirata")
        assert all(r["cat"] == "pirata" for r in pirata_history)
        assert len(pirata_history) == 1

    def test_empty_when_no_data_for_cat(self, store):
        store.write([make_visit("pirata", 6.5)])
        assert store.load_history_for_cat("robin") == []
