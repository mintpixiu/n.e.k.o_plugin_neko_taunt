from pathlib import Path


def test_plugin_manifest_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = root / "plugin.toml"
    assert manifest.is_file()
    text = manifest.read_text(encoding="utf-8")
    assert 'id = "neko_taunt"' in text
    assert 'entry = "plugin.plugins.neko_taunt:NekoTauntPlugin"' in text


def test_entry_module_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "__init__.py").is_file()
    assert (root / "lines.py").is_file()
    assert (root / "docs" / "guide.md").is_file()