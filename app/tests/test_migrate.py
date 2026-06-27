"""Tests for the historical CSV parser in migrate.py."""
from datetime import datetime, timezone

import pytest

import timeutils

from migrate import detect_format, extract_year, parse_timestamp, parse_weight


class TestExtractYear:
    def test_old_filename_format(self):
        assert extract_year("red_dwarf_actividad_26-1-2025.csv") == 2025

    def test_new_filename_format(self):
        assert extract_year("red_dwarf_actividad_2025-10-26.csv") == 2025

    def test_year_2026(self):
        assert extract_year("red_dwarf_actividad_2026-04-26.csv") == 2026

    def test_missing_year_raises(self):
        with pytest.raises(ValueError):
            extract_year("weights.csv")


class TestDetectFormat:
    def test_format_a_english_am(self):
        assert detect_format("1/26 9:06AM") == "A"

    def test_format_a_english_pm(self):
        assert detect_format("3/21 11:18PM") == "A"

    def test_format_b_spanish_pm(self):
        assert detect_format("6/21 7:30p. m.") == "B"

    def test_format_b_spanish_am(self):
        assert detect_format("6/21 11:05a. m.") == "B"

    def test_format_c_european_24h(self):
        assert detect_format("27/7 07:49") == "C"

    def test_format_c_two_digit_month(self):
        assert detect_format("26/10 04:58") == "C"


class TestParseTimestamp:
    UTC = timeutils.LOCAL_TZ

    def test_format_a_am(self):
        result = parse_timestamp("1/26 9:06AM", "A", 2025)
        assert result == datetime(2025, 1, 26, 9, 6, tzinfo=self.UTC)

    def test_format_a_pm(self):
        result = parse_timestamp("3/21 11:18PM", "A", 2025)
        assert result == datetime(2025, 3, 21, 23, 18, tzinfo=self.UTC)

    def test_format_b_pm(self):
        result = parse_timestamp("6/21 7:30p. m.", "B", 2025)
        assert result == datetime(2025, 6, 21, 19, 30, tzinfo=self.UTC)

    def test_format_b_am(self):
        result = parse_timestamp("6/21 11:05a. m.", "B", 2025)
        assert result == datetime(2025, 6, 21, 11, 5, tzinfo=self.UTC)

    def test_format_c_single_digit_month(self):
        result = parse_timestamp("27/7 07:49", "C", 2025)
        assert result == datetime(2025, 7, 27, 7, 49, tzinfo=self.UTC)

    def test_format_c_two_digit_month(self):
        result = parse_timestamp("26/10 04:58", "C", 2025)
        assert result == datetime(2025, 10, 26, 4, 58, tzinfo=self.UTC)

    def test_year_is_applied(self):
        result = parse_timestamp("9/3 08:17", "C", 2026)
        assert result.year == 2026


class TestSpanishNonBreakingSpace:
    """The Jun 2025 Whisker export uses \\xa0 (non-breaking space) inside 'p.\\xa0m.'.

    Regression: this used to misdetect as format C and silently drop ~200 rows.
    """
    UTC = timeutils.LOCAL_TZ

    def test_detect_format_b_with_nbsp(self):
        assert detect_format("6/21 7:30p.\xa0m.") == "B"

    def test_detect_format_b_with_narrow_nbsp(self):
        assert detect_format("6/21 11:05a. m.") == "B"

    def test_parse_pm_with_nbsp(self):
        result = parse_timestamp("6/21 7:30p.\xa0m.", "B", 2025)
        assert result == datetime(2025, 6, 21, 19, 30, tzinfo=self.UTC)

    def test_parse_am_with_nbsp(self):
        result = parse_timestamp("6/20 8:33a.\xa0m.", "B", 2025)
        assert result == datetime(2025, 6, 20, 8, 33, tzinfo=self.UTC)


class TestSpanishALasFormat:
    """Jun 2026+ export: 'DD/M, a las H:MM' (European 24h with ', a las ')."""
    UTC = timeutils.LOCAL_TZ

    def test_detected_as_c(self):
        assert detect_format("26/6, a las 8:16") == "C"

    def test_parse_morning(self):
        assert parse_timestamp("26/6, a las 8:16", "C", 2026) == \
            datetime(2026, 6, 26, 8, 16, tzinfo=self.UTC)

    def test_parse_afternoon_24h(self):
        assert parse_timestamp("25/6, a las 15:39", "C", 2026) == \
            datetime(2026, 6, 25, 15, 39, tzinfo=self.UTC)

    def test_day_month_order(self):
        # 26/6 must be day 26, month 6 (not month 26).
        result = parse_timestamp("26/6, a las 1:07", "C", 2026)
        assert (result.day, result.month) == (26, 6)


class TestParseWeight:
    def test_dot_decimal(self):
        assert parse_weight("4.2 kg") == pytest.approx(4.2)

    def test_comma_decimal(self):
        assert parse_weight("4,5 kg") == pytest.approx(4.5)

    def test_no_trailing_space(self):
        assert parse_weight("6.6kg") == pytest.approx(6.6)

    def test_heavy_cat(self):
        assert parse_weight("7.0 kg") == pytest.approx(7.0)
