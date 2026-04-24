"""Unit tests for scripts/translate_missing.py placeholder validator + glossary."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from translate_missing import (  # noqa: E402
    _icu_variable_names,
    _placeholders,
    _placeholders_match,
    build_system_prompt,
)


class TestICUVariableNames:
    def test_simple(self):
        assert _icu_variable_names("hello {name}") == ["name"]

    def test_multiple(self):
        assert _icu_variable_names("{a}, {b}, {c}") == ["a", "b", "c"]

    def test_plural_outer_only(self):
        # Nested braces in plural branches don't count as separate vars
        assert _icu_variable_names(
            "{count, plural, one {# item} other {# items}}"
        ) == ["count"]

    def test_collapsed_plural(self):
        # Chinese shape — still just one outer variable named `count`
        assert _icu_variable_names("{count, plural, other {# 项}}") == ["count"]

    def test_numeric_placeholder(self):
        assert _icu_variable_names("got {0} of {1}") == ["0", "1"]

    def test_no_braces(self):
        assert _icu_variable_names("no placeholders here") == []


class TestPlaceholdersMatch:
    def test_identical(self):
        assert _placeholders_match("hello {name}", "hello {name}")

    def test_translated_ok(self):
        # Content between placeholders can change; vars must match
        assert _placeholders_match("hello {name}", "ni hao {name}")

    def test_dropped_placeholder_rejects(self):
        assert not _placeholders_match("hello {name}", "ni hao")

    def test_renamed_placeholder_rejects(self):
        # {x} → {y} is a real bug; the caller's format() would KeyError
        assert not _placeholders_match("a {x}", "a {y}")

    def test_duplicate_placeholder_rejects(self):
        assert not _placeholders_match("{a}, {b}", "{a}, {b}, {b}")

    def test_reordered_placeholders_ok(self):
        # Order changes are fine — the sorted comparison treats them equal
        assert _placeholders_match("{a}, {b}, {c}", "{c} {b} {a}")

    def test_plural_branches_differ_ok(self):
        # The whole reason we compare variable names, not full tokens:
        # zh legitimately collapses one+other branches to other only.
        assert _placeholders_match(
            "{count, plural, one {# item} other {# items}}",
            "{count, plural, other {# 项}}",
        )

    def test_plural_variable_rename_rejects(self):
        assert not _placeholders_match(
            "{count, plural, other {# item}}",
            "{total, plural, other {# item}}",
        )


class TestXMLTags:
    def test_open_close(self):
        assert _placeholders_match("<0>{name}</0>", "<0>{name}</0>")

    def test_reordered_rejects(self):
        # <0> and <1> point to distinct React children — swapping breaks
        assert not _placeholders_match("<0>x</0>", "<1>y</1>")

    def test_dropped_rejects(self):
        assert not _placeholders_match("<0>x</0>", "x")

    def test_self_closing(self):
        s = "click <0/> to retry"
        assert _placeholders(s)["xml"] == ["<0/>"]


class TestGlossaryInjection:
    def test_prompt_includes_canonical_terms(self):
        prompt = build_system_prompt()
        # Core domain terms must be pinned
        assert "HRV" in prompt
        assert "恢复" in prompt  # Recovery → 恢复 (zone + status)
        assert "阈值功率" in prompt  # Critical Power
        assert "乳酸阈" in prompt  # Threshold (zone) — matches both 乳酸阈 and 乳酸阈值心率
        assert "马拉松" in prompt  # Marathon

    def test_prompt_warns_about_placeholders(self):
        prompt = build_system_prompt()
        # The CI bot must be explicitly told to preserve placeholders
        assert "placeholder" in prompt.lower() or "VERBATIM" in prompt


class TestPromptFallbacksGracefully:
    def test_missing_glossary_still_returns_base_prompt(self, tmp_path, monkeypatch):
        """If someone deletes scripts/i18n_glossary.yaml the translator
        still produces a usable prompt — the glossary is best-effort."""
        import translate_missing as tm

        # Monkeypatch the resolved glossary path to something that doesn't exist
        original_file = tm.__file__
        fake_file = str(tmp_path / "translate_missing.py")
        monkeypatch.setattr(tm, "__file__", fake_file)
        try:
            prompt = tm.build_system_prompt()
            # Base rules are still present
            assert "VERBATIM" in prompt
            assert "Praxys" in prompt
        finally:
            monkeypatch.setattr(tm, "__file__", original_file)
