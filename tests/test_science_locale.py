"""Tests for locale-aware theory loading."""
from pathlib import Path
from unittest.mock import patch

import yaml

import analysis.science as science


def _write_theory(path: Path, name: str, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "id": path.stem,
        "pillar": "load",
        "name": name,
        "description": description,
        "params": {"ctl_time_constant": 42, "atl_time_constant": 7},
    }), encoding="utf-8")


def test_loader_prefers_localized_file(tmp_path: Path) -> None:
    en_path = tmp_path / "load" / "banister_pmc.yaml"
    zh_path = tmp_path / "zh" / "load" / "banister_pmc.yaml"
    _write_theory(en_path, "Banister PMC", "Performance Management Chart")
    _write_theory(zh_path, "Banister xunlian biao", "jixiao guanli tubiao")

    with patch.object(science, "_SCIENCE_DIR", str(tmp_path)):
        en_theory = science.load_theory("load", "banister_pmc")
        zh_theory = science.load_theory("load", "banister_pmc", locale="zh")

    assert en_theory.name == "Banister PMC"
    assert zh_theory.name == "Banister xunlian biao"
    assert zh_theory.description == "jixiao guanli tubiao"


def test_loader_falls_back_when_locale_missing(tmp_path: Path) -> None:
    _write_theory(tmp_path / "load" / "banister_pmc.yaml", "Banister PMC", "English copy")
    with patch.object(science, "_SCIENCE_DIR", str(tmp_path)):
        zh_theory = science.load_theory("load", "banister_pmc", locale="zh")
    assert zh_theory.name == "Banister PMC"
    assert zh_theory.description == "English copy"


def test_list_theories_resolves_locale_per_file(tmp_path: Path) -> None:
    _write_theory(tmp_path / "load" / "a.yaml", "A", "en A")
    _write_theory(tmp_path / "load" / "b.yaml", "B", "en B")
    _write_theory(tmp_path / "zh" / "load" / "a.yaml", "jia", "zh A")
    with patch.object(science, "_SCIENCE_DIR", str(tmp_path)):
        theories = {t.id: t for t in science.list_theories("load", locale="zh")}
    assert theories["a"].name == "jia"
    assert theories["b"].name == "B"


def test_locale_none_matches_legacy_behavior(tmp_path: Path) -> None:
    _write_theory(tmp_path / "load" / "banister_pmc.yaml", "Banister PMC", "Original")
    _write_theory(tmp_path / "zh" / "load" / "banister_pmc.yaml", "ignored", "ignored")
    with patch.object(science, "_SCIENCE_DIR", str(tmp_path)):
        theory = science.load_theory("load", "banister_pmc", locale=None)
    assert theory.name == "Banister PMC"
