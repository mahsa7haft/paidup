"""Tests for resolve_person_to_company — Anthropic client mocked throughout."""

import json
import pytest
from unittest.mock import patch, MagicMock
from app.ai import resolve_person_to_company


def _mock_client(response_text: str):
    """Return a mock Anthropic client whose messages.create() returns response_text."""
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    client = MagicMock()
    client.messages.create.return_value = msg
    return client


class TestResolvePersonToCompany:
    def test_known_company_owner(self):
        payload = '{"company_name": "Sainsbury\'s", "domain": "sainsburys.co.uk"}'
        with patch("app.ai.anthropic.Anthropic", return_value=_mock_client(payload)), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            name, domain = resolve_person_to_company("Lord David Sainsbury")
        assert name == "Sainsbury's"
        assert domain == "sainsburys.co.uk"

    def test_no_corporate_link(self):
        payload = '{"company_name": null, "domain": null}'
        with patch("app.ai.anthropic.Anthropic", return_value=_mock_client(payload)), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            name, domain = resolve_person_to_company("Sir Trevor Chinn")
        assert name is None
        assert domain is None

    def test_markdown_fence_stripped(self):
        payload = '```json\n{"company_name": "Dyson Ltd", "domain": "dyson.com"}\n```'
        with patch("app.ai.anthropic.Anthropic", return_value=_mock_client(payload)), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            name, domain = resolve_person_to_company("Sir James Dyson")
        assert domain == "dyson.com"

    def test_empty_response_returns_none_none(self):
        with patch("app.ai.anthropic.Anthropic", return_value=_mock_client("")), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            name, domain = resolve_person_to_company("Someone")
        assert name is None
        assert domain is None

    def test_invalid_json_returns_none_none(self):
        with patch("app.ai.anthropic.Anthropic", return_value=_mock_client("not json")), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            name, domain = resolve_person_to_company("Someone")
        assert name is None
        assert domain is None

    def test_no_api_key_returns_none_none(self):
        with patch.dict("os.environ", {}, clear=True):
            # Ensure ANTHROPIC_API_KEY is absent
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            name, domain = resolve_person_to_company("Lord Anyone")
        assert name is None
        assert domain is None

    def test_api_exception_returns_none_none(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("network error")
        with patch("app.ai.anthropic.Anthropic", return_value=client), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            name, domain = resolve_person_to_company("Lord Anyone")
        assert name is None
        assert domain is None

    def test_uses_haiku_model(self):
        payload = '{"company_name": null, "domain": null}'
        client = _mock_client(payload)
        with patch("app.ai.anthropic.Anthropic", return_value=client), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            resolve_person_to_company("Sir Anyone")
        call_kwargs = client.messages.create.call_args
        assert "haiku" in call_kwargs.kwargs.get("model", call_kwargs.args[0] if call_kwargs.args else "")
