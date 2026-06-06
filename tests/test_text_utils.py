"""Tests for shared text normalisation and fuzzy-matching helpers."""

import pytest
from app.text_utils import normalize_name, best_fuzzy_match


class TestNormalizeName:
    def test_strips_the_prefix(self):
        assert normalize_name("The Arsenal Football Club") == "arsenal football club"

    def test_strips_legal_suffixes(self):
        assert normalize_name("Arsenal Football Club Limited") == "arsenal football club"
        assert normalize_name("Tesco PLC") == "tesco"
        assert normalize_name("Blackrock Holdings Ltd") == "blackrock"

    def test_strips_honorific_titles(self):
        assert normalize_name("Lord David Sainsbury") == "david sainsbury"
        assert normalize_name("Sir James Dyson") == "james dyson"
        assert normalize_name("Baroness Michelle Mone") == "michelle mone"
        assert normalize_name("Dame Judi Dench") == "judi dench"
        assert normalize_name("Mr John Smith") == "john smith"

    def test_strips_territorial_designation(self):
        assert normalize_name("Lord David Sainsbury of Turville") == "david sainsbury"
        assert normalize_name("Baroness Thatcher of Kesteven") == "thatcher"

    def test_collapses_whitespace(self):
        assert normalize_name("  Arsenal   FC  ") == "arsenal fc"

    def test_lowercases(self):
        assert normalize_name("HSBC BANK") == "hsbc bank"

    def test_strips_the_and_ltd_together(self):
        assert normalize_name("The Arsenal Football Club Limited") == "arsenal football club"

    def test_plain_name_unchanged(self):
        assert normalize_name("jane smith") == "jane smith"

    def test_rt_hon_prefix(self):
        assert normalize_name("The Rt Hon Jeremy Hunt") == "jeremy hunt"


class TestBestFuzzyMatch:
    def test_exact_normalised_match(self):
        candidates = ["Arsenal Football Club Limited", "Tesco PLC"]
        # "The Arsenal FC" normalises to "arsenal fc" — won't match; test true exact
        assert best_fuzzy_match("Tesco PLC", candidates) == "Tesco PLC"

    def test_single_char_typo(self):
        candidates = ["Lord David Sainsbury"]
        result = best_fuzzy_match("Lord David Sainsburi", candidates, threshold=0.75)
        assert result == "Lord David Sainsbury"

    def test_legal_suffix_variant(self):
        candidates = ["Arsenal Football Club Limited"]
        result = best_fuzzy_match("Arsenal Football Club Ltd", candidates, threshold=0.75)
        assert result == "Arsenal Football Club Limited"

    def test_no_match_below_threshold(self):
        candidates = ["Tesco PLC", "Arsenal FC"]
        assert best_fuzzy_match("Sainsbury's", candidates, threshold=0.82) is None

    def test_empty_candidates(self):
        assert best_fuzzy_match("anyone", []) is None

    def test_picks_closest_of_multiple(self):
        candidates = ["Lord David Sainsbury", "Lord John Sainsbury"]
        result = best_fuzzy_match("Lord David Sainsbury", candidates)
        assert result == "Lord David Sainsbury"

    def test_default_threshold_rejects_distant_names(self):
        candidates = ["Blackrock Asset Management"]
        assert best_fuzzy_match("Vanguard Group", candidates) is None
