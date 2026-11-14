"""Market/package contract checks that run on Linux CI without a N.E.K.O host.

These are stdlib-only: they parse the manifest and the entry module as text/AST
instead of importing the SDK-bound facade.  The pure line bank is imported
directly because it has no host dependency.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plugin.toml"
ENTRY = ROOT / "__init__.py"


def _manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def _decorated_ids(tree: ast.Module, decorator: str, keyword: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != decorator:
                continue
            for kw in dec.keywords:
                if kw.arg == keyword and isinstance(kw.value, ast.Constant):
                    found.append(str(kw.value.value))
    return found


def test_manifest_is_market_ready() -> None:
    plugin = _manifest()["plugin"]
    assert plugin["id"] == "neko_taunt"
    assert re.fullmatch(r"[a-z][a-z0-9_]*", plugin["id"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin["version"])
    assert plugin["type"] == "plugin"
    assert plugin["entry"] == "plugin.plugins.neko_taunt:NekoTauntPlugin"
    assert plugin["name"].strip()
    assert len(plugin["description"]) > 40
    assert "日语" in plugin["description"]
    assert "杂鱼" in plugin["description"]
    assert plugin["keywords"] and all(isinstance(item, str) and item.strip() for item in plugin["keywords"])
    # The four requested languages are advertised in the manifest keywords.
    for keyword in ("中文", "日语", "英语", "韩语"):
        assert keyword in plugin["keywords"]


def test_sdk_and_runtime_defaults() -> None:
    manifest = _manifest()
    sdk = manifest["plugin"]["sdk"]
    assert sdk["supported"] == ">=0.1.0,<0.3.0"
    assert sdk["recommended"] == ">=0.1.0,<0.2.0"
    runtime = manifest["plugin_runtime"]
    assert runtime["enabled"] is True
    assert runtime["auto_start"] is True
    assert 0 < runtime["timeout"] <= 300
    # Starting the plugin must not begin taunting on its own.
    assert manifest["taunt"]["auto_taunt"] is False
    assert manifest["taunt"]["default_language"] == "ja"
    assert 1 <= manifest["taunt"]["default_intensity"] <= 3
    assert manifest["taunt"]["quiet_hours"]


def test_required_entries_and_tool_exist_and_are_async() -> None:
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "NekoTauntPlugin" in classes
    assert any(
        isinstance(node, ast.ClassDef)
        and node.name == "NekoTauntPlugin"
        and any(isinstance(dec, ast.Name) and dec.id == "neko_plugin" for dec in node.decorator_list)
        for node in tree.body
    )

    entry_ids = _decorated_ids(tree, "plugin_entry", "id")
    tool_names = _decorated_ids(tree, "llm_tool", "name")
    for required in ("taunt_now", "taunt_speak", "taunt_preview", "taunt_library", "taunt_status", "taunt_mode"):
        assert required in entry_ids, required
    assert tool_names == ["neko_taunt"], tool_names
    assert len(entry_ids) == len(set(entry_ids)), "duplicate @plugin_entry ids"

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_entry = any(
            isinstance(dec, ast.Call)
            and getattr(dec.func, "id", getattr(dec.func, "attr", "")) == "plugin_entry"
            for dec in node.decorator_list
        )
        if is_entry:
            assert isinstance(node, ast.AsyncFunctionDef), f"{node.name} must be async"
        is_timer = any(
            isinstance(dec, ast.Call)
            and getattr(dec.func, "id", getattr(dec.func, "attr", "")) == "timer_interval"
            for dec in node.decorator_list
        )
        if is_timer:
            assert isinstance(node, ast.AsyncFunctionDef), f"{node.name} must be async"


def test_ui_actions_have_labels() -> None:
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    action_ids: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr == "action"):
                continue
            kwargs = {kw.arg: kw.value for kw in dec.keywords if kw.arg}
            assert "label" in kwargs, node.name
            action_id = kwargs.get("id")
            if isinstance(action_id, ast.Constant):
                action_ids.append(str(action_id.value))
    assert {"taunt_speak", "taunt_preview", "taunt_library", "taunt_status"} <= set(action_ids)


def test_locale_files_are_complete_and_consistent() -> None:
    i18n = _manifest()["plugin"]["i18n"]
    assert i18n["default_locale"] == "zh-CN"
    assert i18n["locales_dir"] == "i18n"
    base: set[str] | None = None
    for locale in ("zh-CN", "en", "ja", "ko"):
        data = json.loads((ROOT / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        assert data["plugin.name"].strip()
        assert data["plugin.description"].strip()
        for key in ("taunt_speak", "taunt_preview", "taunt_library", "taunt_status"):
            assert data[f"action.{key}"].strip(), (locale, key)
        if base is None:
            base = set(data)
        else:
            assert set(data) == base, f"{locale} locale keys drifted"
    assert base is not None


def test_config_schema_covers_every_manifest_key() -> None:
    schema = json.loads((ROOT / "config.schema.json").read_text(encoding="utf-8"))
    assert schema["type"] == "object"
    taunt = schema["properties"]["taunt"]
    assert taunt["type"] == "object"
    schema_keys = set(taunt["properties"])
    manifest_keys = set(_manifest()["taunt"])
    assert schema_keys == manifest_keys, (
        f"schema-only={sorted(schema_keys - manifest_keys)} "
        f"manifest-only={sorted(manifest_keys - schema_keys)}"
    )
    for key, prop in taunt["properties"].items():
        assert prop.get("title"), f"{key} has no title"
        assert prop.get("type") in {"string", "number", "integer", "boolean", "object", "array"}, key


def test_no_requirements_or_vendor_or_network_dependencies() -> None:
    assert not (ROOT / "requirements.txt").exists()
    assert not (ROOT / "vendor").exists()
    for filename in ("__init__.py", "lines.py"):
        tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        network_modules = {"requests", "aiohttp", "httpx", "socket", "urllib", "http.client"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in network_modules, (filename, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in network_modules, (filename, node.module)


def test_tool_and_entry_result_contract() -> None:
    text = ENTRY.read_text(encoding="utf-8")
    assert "is_error" in text and "error" in text
    assert "ai_behavior=\"respond\"" in text
    assert "visibility=[]" in text
    assert "Ok(" in text and "Err(SdkError" in text
    # The bank itself must carry all four languages.
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import lines

    assert set(lines.LANGUAGES) == {"ja", "zh", "en", "ko"}
    assert all(count > 0 for count in lines.counts()["by_language"].values())


def test_docs_and_guide_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    for text in (readme, guide):
        assert "杂鱼" in text
        assert "日语" in text
    assert "## 安装" in readme or "## Install" in readme
    assert "安全" in guide or "边界" in guide