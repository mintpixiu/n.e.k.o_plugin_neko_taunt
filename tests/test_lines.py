"""Portable tests for the SDK-free line bank and selector (Linux CI safe)."""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pytest

# Imported through pytest so the local module is not a top-level import that
# older ruff/isort versions want to regroup differently.
lines = pytest.importorskip("lines")

ROOT = Path(__file__).resolve().parents[1]


def test_bank_is_large_and_japanese_is_the_majority() -> None:
    counts = lines.counts()
    assert counts["total"] >= 120
    assert counts["by_language"]["ja"] >= 60
    assert counts["by_language"]["ja"] > sum(
        counts["by_language"][code] for code in ("zh", "en", "ko")
    ) * 0.45
    # Every requested language is genuinely present.
    for code in lines.LANGUAGES:
        assert counts["by_language"][code] >= 15, code


def test_every_line_is_well_formed() -> None:
    seen_ids: set[str] = set()
    for line in lines.LINES:
        assert line.id not in seen_ids, f"duplicate id {line.id}"
        seen_ids.add(line.id)
        assert line.lang in lines.LANGUAGES, line.id
        assert line.category in lines.CATEGORIES, line.id
        assert line.intensity in (1, 2, 3), line.id
        assert line.text.strip(), line.id
        assert line.meaning.strip(), line.id
        assert line.tone.strip(), line.id

    for line in lines.LINES:
        if line.lang == "ja":
            assert line.romaji.strip(), f"{line.id} has no romaji"
        else:
            assert not line.romaji, f"{line.id} should not carry romaji"


def test_categories_are_all_populated_per_language_or_fallback_exists() -> None:
    for code in lines.LANGUAGES:
        assert [line for line in lines.LINES if line.lang == code], code
    for category in lines.CATEGORIES:
        assert [line for line in lines.LINES if line.category == category], category


def test_selector_respects_language_category_and_intensity() -> None:
    selector = lines.TauntSelector(rng=random.Random(7))
    for _ in range(80):
        line = selector.select(language="ja", category="zako", intensity=2)
        assert line.lang == "ja"
        assert line.category == "zako"
        assert line.intensity <= 2


def test_selector_avoids_immediate_repeats() -> None:
    selected = lines.TauntSelector(rng=random.Random(11), recent_limit=20)
    picked = [selected.select(language="ja", category="zako", intensity=2).id for _ in range(10)]
    assert len(picked) == len(set(picked))


def test_selector_mix_is_mostly_japanese() -> None:
    selector = lines.TauntSelector(rng=random.Random(3))
    picked = [selector.select(language="mix", category="zako", intensity=2).lang for _ in range(1500)]
    japanese_ratio = picked.count("ja") / len(picked)
    assert 0.50 < japanese_ratio < 0.70, japanese_ratio
    assert set(picked) == set(lines.LANGUAGES)


def test_selector_falls_back_instead_of_crashing() -> None:
    selector = lines.TauntSelector(rng=random.Random(5))
    # Korean praise at intensity 3: no exact intensity-3 line exists, but the
    # selector must still return a Korean praise line.
    line = selector.select(language="ko", category="praise", intensity=3)
    assert line.lang == "ko"
    assert line.category == "praise"
    # Unknown language maps to the default (Japanese).
    line = selector.select(language="xx", category="praise", intensity=1)
    assert line.lang == "ja"


def test_selector_accepts_any_crashing_input() -> None:
    selector = lines.TauntSelector(rng=random.Random(1))
    for language in (None, "", "AUTO", "jp", "zh-cn", "KR", "mix", 123):
        for category in (None, "", "auto", "nonsense", "zako", "雑魚"):
            line = selector.select(language=language, category=category, intensity=None)
            assert isinstance(line, lines.TauntLine)


def test_situation_inference_works_in_all_languages() -> None:
    cases = {
        "游戏输了，好难受": "lose",
        "手滑按错键了": "clumsy",
        "你怎么这么慢啊": "slow",
        "猫娘还没到，等好久": "idle",
        "理理我嘛，好寂寞": "clingy",
        "我赢了！": "praise",
        "我就是个杂鱼": "zako",
        "I lost the game": "lose",
        "too slow, catgirl": "slow",
        "まだ来ないの？": "idle",
        "졌어...": "lose",
        "자코 같아": "zako",
    }
    for text, expected in cases.items():
        assert lines.infer_category(text) == expected, text
    assert lines.infer_category("") == "auto"
    assert lines.infer_category("完全无关的天气话题") == "auto"


def test_quiet_hours_supports_overnight_and_bad_input() -> None:
    assert lines.in_quiet_hours(datetime(2026, 1, 1, 23, 30), "23:00-08:00") is True
    assert lines.in_quiet_hours(datetime(2026, 1, 1, 7, 59), "23:00-08:00") is True
    assert lines.in_quiet_hours(datetime(2026, 1, 1, 8, 0), "23:00-08:00") is False
    assert lines.in_quiet_hours(datetime(2026, 1, 1, 12, 0), "23:00-08:00") is False
    assert lines.in_quiet_hours(datetime(2026, 1, 1, 12, 0), "12:00-13:00") is True
    for bad in ("", "nope", "25:00-08:00", "23:99-08:00", "08:00-08:00"):
        assert lines.in_quiet_hours(datetime(2026, 1, 1, 12, 0), bad) is False


def test_delivery_prompt_carries_line_meaning_tone_and_boundaries() -> None:
    line = next(item for item in lines.LINES if item.id == "ja-zako-01")
    prompt = lines.delivery_prompt(line, situation="游戏输了")
    assert line.text in prompt
    assert line.meaning in prompt
    assert line.romaji in prompt
    assert line.tone in prompt
    assert "{MASTER_NAME}" in prompt
    assert "游戏输了" in prompt
    assert "不许人身攻击" in prompt
    assert "不要解释" in prompt


def test_delivery_prompt_can_hide_romaji_and_translation() -> None:
    line = next(item for item in lines.LINES if item.id == "ja-zako-01")
    prompt = lines.delivery_prompt(line, include_romaji=False, include_translation=False)
    assert line.text in prompt
    assert line.romaji not in prompt
    assert line.meaning not in prompt


def test_normalize_config_clamps_and_types() -> None:
    cfg = lines.normalize_config({
        "default_language": "JP",
        "default_intensity": 99,
        "auto_taunt": "true",
        "auto_taunt_interval_minutes": 1,
        "auto_taunt_max_per_session": 999,
        "auto_taunt_category": "杂鱼",
        "quiet_hours": "23:00-08:00",
        "include_romaji": "false",
        "include_translation": 0,
    })
    assert cfg["default_language"] == "ja"
    assert cfg["default_intensity"] == 3
    assert cfg["auto_taunt"] is True
    assert cfg["auto_taunt_interval_minutes"] == 1
    assert cfg["auto_taunt_max_per_session"] == 50
    assert cfg["auto_taunt_category"] == "zako"
    assert cfg["include_romaji"] is False
    assert cfg["include_translation"] is False

    default = lines.normalize_config(None)
    assert default == lines.DEFAULT_CONFIG


def test_library_summary_filters_and_counts() -> None:
    data = lines.library_summary(language="ja", category="zako", limit=3)
    assert data["language"] == "ja"
    assert data["category"] == "zako"
    assert data["filtered"] == len([line for line in lines.LINES if line.lang == "ja" and line.category == "zako"])
    assert 1 <= len(data["samples"]) <= 3
    assert all(sample["language"] == "ja" for sample in data["samples"])
    assert data["by_language"]["ja"] >= 60


def test_payload_shapes() -> None:
    line = next(item for item in lines.LINES if item.id == "ko-zako-01")
    payload = lines.as_payload(line)
    assert payload["line_id"] == line.id
    assert payload["language"] == "ko"
    assert payload["text"] == line.text
    assert payload["translation_zh"] == line.meaning
    assert "romaji" not in payload


def test_effective_auto_interval() -> None:
    assert lines.effective_auto_interval_seconds(20) == 20 * 60
    assert lines.effective_auto_interval_seconds(0, host_interval_seconds=120) == 300
    assert lines.effective_auto_interval_seconds(0, host_interval_seconds=600) == 600
    assert lines.effective_auto_interval_seconds(0, host_interval_seconds=0) == 20 * 60
    assert lines.effective_auto_interval_seconds(0, host_interval_seconds=7200) == 3600
    assert lines.effective_auto_interval_seconds(0, host_interval_seconds=120, follow_host=False) == 20 * 60
    assert lines.effective_auto_interval_seconds(1) == 300


@pytest.mark.parametrize("language", ["auto", "ja", "zh", "en", "ko", "mix"])
def test_every_language_option_is_selectable(language: str) -> None:
    selector = lines.TauntSelector(rng=random.Random(9))
    line = selector.select(language=language, category="zako", intensity=2)
    assert line.lang in lines.LANGUAGES