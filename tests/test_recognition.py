# Tests for koan.agents.recognition -- parse_model_id, version_key, order_by_version.

from __future__ import annotations

import pytest

from koan.agents.recognition import order_by_version, parse_model_id, version_key


# -- parse_model_id ------------------------------------------------------------

class TestParseModelId:
    def test_known_anthropic_opus_returns_family_and_tier(self):
        """claude-opus-4-0 parses to family=claude-opus, recognized=True."""
        p = parse_model_id("claude-opus-4-0")
        assert p.family == "claude-opus"
        assert p.recognized is True

    def test_known_anthropic_sonnet(self):
        """claude-sonnet-4-5 parses to family=claude-sonnet."""
        p = parse_model_id("claude-sonnet-4-5")
        assert p.family == "claude-sonnet"
        assert p.recognized is True

    def test_known_anthropic_haiku(self):
        """claude-3-5-haiku-latest parses to family=claude-haiku."""
        p = parse_model_id("claude-3-5-haiku-latest")
        assert p.family == "claude-haiku"
        assert p.recognized is True

    def test_known_google_flash_lite_beats_flash_prefix(self):
        """gemini-3.1-flash-lite resolves to flash-lite (longer prefix wins over flash)."""
        p = parse_model_id("gemini-3.1-flash-lite")
        assert p.family == "gemini-flash-lite"
        assert p.recognized is True

    def test_known_google_flash(self):
        """gemini-3.5-flash parses to family=gemini-flash."""
        p = parse_model_id("gemini-3.5-flash")
        assert p.family == "gemini-flash"
        assert p.recognized is True

    def test_known_google_pro(self):
        """gemini-3.1-pro-preview parses to family=gemini-pro."""
        p = parse_model_id("gemini-3.1-pro-preview")
        assert p.family == "gemini-pro"
        assert p.recognized is True

    def test_known_openai_gpt4o(self):
        """gpt-4o parses to family=gpt-4o."""
        p = parse_model_id("gpt-4o")
        assert p.family == "gpt-4o"
        assert p.recognized is True

    def test_known_openai_gpt4o_mini_beats_gpt4o_prefix(self):
        """gpt-4o-mini resolves to gpt-4o-mini (longer prefix wins)."""
        p = parse_model_id("gpt-4o-mini")
        assert p.family == "gpt-4o-mini"
        assert p.recognized is True

    def test_bedrock_anthropic_prefix_stripped(self):
        """anthropic.claude-opus-4-0 (bedrock-style) strips the vendor prefix."""
        p = parse_model_id("anthropic.claude-opus-4-0")
        assert p.family == "claude-opus"
        assert p.recognized is True

    def test_unknown_model_id_returns_recognized_false(self):
        """An unrecognized model id returns recognized=False without raising."""
        p = parse_model_id("some-totally-unknown-llm-xyz-9000")
        assert p.recognized is False
        assert p.family is None

    def test_unknown_does_not_raise(self):
        """parse_model_id never raises for any input (brief D5 graceful fallthrough)."""
        for mid in ("", "???", "gpt-", "-claude", "gemini/flash"):
            result = parse_model_id(mid)
            assert isinstance(result.recognized, bool)


# -- version_key ---------------------------------------------------------------

class TestVersionKey:
    def test_plain_numeric_version(self):
        """claude-opus-4-0 extracts (4, 0) as its version key."""
        key = version_key("claude-opus-4-0")
        assert key == (4, 0)

    def test_override_takes_precedence(self):
        """claude-3-5-haiku-latest uses _VERSION_OVERRIDES rather than segment extraction."""
        from koan.agents.recognition import _VERSION_OVERRIDES
        key = version_key("claude-3-5-haiku-latest")
        assert key == _VERSION_OVERRIDES["claude-3-5-haiku-latest"]

    def test_non_override_model_extracts_numerics(self):
        """claude-sonnet-4-5 extracts (4, 5)."""
        key = version_key("claude-sonnet-4-5")
        assert key == (4, 5)

    def test_no_numeric_segments_returns_empty_tuple(self):
        """A model id with no numeric segments returns ()."""
        key = version_key("gpt-four-o")
        assert key == ()


# -- order_by_version ----------------------------------------------------------

class TestOrderByVersion:
    def test_newest_first_within_family(self):
        """Models are sorted newest-first by version_key."""
        models = ["claude-opus-4-0", "claude-opus-3-5", "claude-opus-3-0"]
        ordered = order_by_version(models)
        # claude-opus-4-0 -> (4,0) newest; claude-opus-3-5 -> (3,5); claude-opus-3-0 -> (3,0) oldest
        assert ordered[0] == "claude-opus-4-0"
        assert ordered[-1] == "claude-opus-3-0"

    def test_override_sorts_correctly(self):
        """A model with a _VERSION_OVERRIDES entry sorts correctly relative to versioned ids."""
        models = ["claude-3-5-haiku-latest", "claude-3-5-haiku-20241022", "claude-3-0-haiku-20240307"]
        ordered = order_by_version(models)
        # "latest" override (3,5,99) should be newest.
        assert ordered[0] == "claude-3-5-haiku-latest"

    def test_single_model_returns_singleton(self):
        """order_by_version with one model returns a one-element list."""
        assert order_by_version(["gpt-4o"]) == ["gpt-4o"]

    def test_empty_list(self):
        """order_by_version with empty input returns []."""
        assert order_by_version([]) == []
