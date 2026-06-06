"""Tests for card badge classification logic."""

import pytest
from unittest.mock import patch, MagicMock
from app.card import _is_person, _initials, _classify_donor


class TestIsPerson:
    # Names that should be detected as individuals
    def test_lord(self):
        assert _is_person("Lord David Sainsbury") is True

    def test_sir(self):
        assert _is_person("Sir James Dyson") is True

    def test_baroness(self):
        assert _is_person("Baroness Michelle Mone") is True

    def test_lady(self):
        assert _is_person("Lady Thatcher") is True

    def test_dame(self):
        assert _is_person("Dame Judi Dench") is True

    def test_mr(self):
        assert _is_person("Mr John Brown") is True

    def test_dr(self):
        assert _is_person("Dr Sarah Jones") is True

    # Names that should NOT be detected as persons
    def test_company_with_ltd(self):
        assert _is_person("Arsenal Football Club Limited") is False

    def test_company_with_plc(self):
        assert _is_person("Tesco PLC") is False

    def test_company_with_group(self):
        assert _is_person("Blackrock Group") is False

    def test_company_with_trust(self):
        assert _is_person("The Rowntree Foundation Trust") is False

    def test_plain_name_no_title(self):
        # No title prefix — not detected (by design; rare plain-name donors stay as company-initials)
        assert _is_person("Jane Smith") is False

    def test_leading_whitespace(self):
        assert _is_person("  Sir Trevor Chinn") is True

    def test_lord_but_has_ltd_suffix(self):
        # Edge case: titled name but also has a company suffix — company wins
        assert _is_person("Lord Holdings Ltd") is False


class TestInitials:
    def test_two_word_name(self):
        assert _initials("Tesco Bank") == "TB"

    def test_strips_ltd(self):
        assert _initials("Tesco Bank Limited") == "TB"

    def test_strips_plc(self):
        # "PLC" stripped → only "Barclays" remains → first 2 letters
        assert _initials("Barclays PLC") == "BA"

    def test_strips_the(self):
        assert _initials("The Guardian Foundation") == "GF"

    def test_strips_holdings_brackets(self):
        # Bug regression: "(Holdings)" must not contribute a "(" initial
        assert _initials("Ascot Authority (Holdings) Limited") == "AA"

    def test_strips_group(self):
        assert _initials("ITV Group") == "IT"

    def test_single_meaningful_word(self):
        assert _initials("HSBC") == "HS"

    def test_all_skip_words(self):
        # Degenerate: only skip words — falls back to first 2 chars of original
        result = _initials("The Ltd")
        assert len(result) == 2

    def test_lord_name(self):
        # "Lord" is not in _initials skip list — it contributes the first initial
        assert _initials("Lord David Sainsbury") == "LS"


class TestClassifyDonor:
    def _mock_link(self, logo_domain):
        return {"company_name": "Test Co", "logo_domain": logo_domain, "source": "manual"}

    # ── Company path (no person prefix) ──────────────────────────────────────

    def test_company_with_guessable_domain(self):
        # Company donors never hit the DB; _guess_domain produces a candidate domain
        badge_type, domain = _classify_donor("Arsenal Football Club Limited")
        assert badge_type in ("company_logo", "company_initials")

    def test_company_no_domain_guess(self):
        # "AB Ltd" → slug "ab" (2 chars) → _guess_domain returns None → initials badge
        badge_type, domain = _classify_donor("AB Ltd")
        assert badge_type == "company_initials"
        assert domain is None

    # ── Person path — DB hit ──────────────────────────────────────────────────

    def test_person_db_hit_with_company(self):
        with patch("app.card.db.get_donor_company_link",
                   return_value=self._mock_link("sainsburys.co.uk")), \
             patch("app.card.db.NO_COMPANY", "__person__"):
            badge_type, domain = _classify_donor("Lord David Sainsbury")
        assert badge_type == "company_logo"
        assert domain == "sainsburys.co.uk"

    def test_person_db_hit_confirmed_person(self):
        with patch("app.card.db.get_donor_company_link",
                   return_value=self._mock_link("__person__")), \
             patch("app.card.db.NO_COMPANY", "__person__"):
            badge_type, domain = _classify_donor("Sir Trevor Chinn")
        assert badge_type == "person"
        assert domain is None

    # ── Person path — DB miss → AI resolves to company ───────────────────────

    def test_person_ai_resolves_company(self):
        with patch("app.card.db.get_donor_company_link", return_value=None), \
             patch("app.card.db.NO_COMPANY", "__person__"), \
             patch("app.card.db.save_donor_company_link") as mock_save, \
             patch("app.card.resolve_person_to_company", return_value=("Dyson Ltd", "dyson.com")):
            badge_type, domain = _classify_donor("Sir James Dyson")
        assert badge_type == "company_logo"
        assert domain == "dyson.com"
        mock_save.assert_called_once_with("Sir James Dyson", "Dyson Ltd", "dyson.com", source="ai")

    # ── Person path — DB miss → AI returns no company ────────────────────────

    def test_person_ai_no_company(self):
        with patch("app.card.db.get_donor_company_link", return_value=None), \
             patch("app.card.db.NO_COMPANY", "__person__"), \
             patch("app.card.db.save_donor_company_link") as mock_save, \
             patch("app.card.resolve_person_to_company", return_value=(None, None)):
            badge_type, domain = _classify_donor("Sir Trevor Chinn")
        assert badge_type == "person"
        assert domain is None
        mock_save.assert_called_once_with("Sir Trevor Chinn", None, "__person__", source="ai")

    # ── Person path — AI errors safely ───────────────────────────────────────

    def test_person_ai_error_falls_back_to_person(self):
        with patch("app.card.db.get_donor_company_link", return_value=None), \
             patch("app.card.db.NO_COMPANY", "__person__"), \
             patch("app.card.db.save_donor_company_link"), \
             patch("app.card.resolve_person_to_company", return_value=(None, None)):
            badge_type, domain = _classify_donor("Lord Unknown Person")
        assert badge_type == "person"
