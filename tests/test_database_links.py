"""Tests for donor_company_links DB helpers (psycopg2 pool mocked)."""

import pytest
from unittest.mock import MagicMock, patch, call
from app.database import get_donor_company_link, save_donor_company_link, NO_COMPANY


def _make_pool(rows=None, fetchone=None):
    """Build a mock psycopg2 connection pool that returns the given rows."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = rows or []
    cur.__enter__ = lambda s: cur
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur

    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool, conn, cur


class TestGetDonorCompanyLink:
    def test_exact_match_returns_row(self):
        pool, conn, cur = _make_pool(fetchone=("Sainsbury's", "sainsburys.co.uk", "manual"))
        with patch("app.database._get_pool", return_value=pool):
            result = get_donor_company_link("Lord David Sainsbury")
        assert result == {"company_name": "Sainsbury's", "logo_domain": "sainsburys.co.uk", "source": "manual"}

    def test_exact_miss_fuzzy_match_found(self):
        pool, conn, cur = _make_pool(
            fetchone=None,
            rows=[("Lord David Sainsbury", "Sainsbury's", "sainsburys.co.uk", "manual")]
        )
        with patch("app.database._get_pool", return_value=pool), \
             patch("app.database.best_fuzzy_match", return_value="Lord David Sainsbury") as mock_fuzz:
            result = get_donor_company_link("Lord David Sainsburi")
        assert result["logo_domain"] == "sainsburys.co.uk"
        mock_fuzz.assert_called_once()

    def test_exact_miss_fuzzy_miss_returns_none(self):
        pool, conn, cur = _make_pool(
            fetchone=None,
            rows=[("Sir Trevor Chinn", None, NO_COMPANY, "ai")]
        )
        with patch("app.database._get_pool", return_value=pool), \
             patch("app.database.best_fuzzy_match", return_value=None):
            result = get_donor_company_link("Completely Unknown Name")
        assert result is None

    def test_no_pool_returns_none(self):
        with patch("app.database._get_pool", return_value=None):
            assert get_donor_company_link("Anyone") is None

    def test_db_exception_returns_none(self):
        pool = MagicMock()
        pool.getconn.side_effect = Exception("connection refused")
        with patch("app.database._get_pool", return_value=pool):
            assert get_donor_company_link("Anyone") is None

    def test_person_sentinel_row_returned(self):
        pool, conn, cur = _make_pool(fetchone=(None, NO_COMPANY, "ai"))
        with patch("app.database._get_pool", return_value=pool):
            result = get_donor_company_link("Sir Trevor Chinn")
        assert result["logo_domain"] == NO_COMPANY
        assert result["company_name"] is None


class TestSaveDonorCompanyLink:
    def test_upserts_row(self):
        pool, conn, cur = _make_pool()
        with patch("app.database._get_pool", return_value=pool):
            save_donor_company_link("Lord David Sainsbury", "Sainsbury's", "sainsburys.co.uk", "manual")
        cur.execute.assert_called_once()
        sql = cur.execute.call_args[0][0]
        assert "INSERT INTO donor_company_links" in sql
        assert "ON CONFLICT" in sql
        conn.commit.assert_called_once()

    def test_saves_person_sentinel(self):
        pool, conn, cur = _make_pool()
        with patch("app.database._get_pool", return_value=pool):
            save_donor_company_link("Sir Trevor Chinn", None, NO_COMPANY, "ai")
        args = cur.execute.call_args[0][1]
        assert args[2] == NO_COMPANY

    def test_no_pool_is_silent_noop(self):
        with patch("app.database._get_pool", return_value=None):
            save_donor_company_link("Anyone", None, None)  # must not raise

    def test_db_exception_rolls_back(self):
        pool, conn, cur = _make_pool()
        cur.execute.side_effect = Exception("constraint violation")
        with patch("app.database._get_pool", return_value=pool):
            save_donor_company_link("Anyone", None, None)  # must not raise
        conn.rollback.assert_called_once()


class TestNoCompanySentinel:
    def test_sentinel_value(self):
        assert NO_COMPANY == "__person__"
