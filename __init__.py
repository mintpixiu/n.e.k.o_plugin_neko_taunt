"""N.E.K.O plugin facade: multilingual catgirl taunts ("zako♡").

The plugin owns no model client and no external network client.  It keeps a
hand-written line bank (``lines.py``), picks a line with a small no-repeat
selector, and hands the exact line plus delivery guidance to the host:

* ``neko_taunt`` is the dialogue-time LLM tool; the model speaks the returned
  line in character.
* ``taunt_now`` is the agent-routed entry that returns the same material.
* ``taunt_speak`` is the explicit Plugin Center / UI action that pushes a
  proactive turn, used when no dialogue turn is already in flight.
* ``taunt_proactive`` is the host-proactive-aware push: it only speaks while
  N.E.K.O's own "主动搭话" switch is on.
* ``taunt_preview``, ``taunt_library``, ``taunt_status`` and ``taunt_mode`` are
  read/control entries.

Auto-taunt is opt-in (``auto_taunt = false`` by default), rate-limited and
silent during quiet hours.  When ``follow_host_proactive`` is on it also
follows N.E.K.O's own proactive-chat switch; the only network call is a
read-only loopback GET to the host's ``/api/proactive/mode``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping

from plugin.sdk.plugin import (
    Err,
    NekoPluginBase,
    Ok,
    SdkError,
    get_plugin_logger,
    lifecycle,
    llm_tool,
    neko_plugin,
    plugin_entry,
    timer_interval,
    ui,
)

from . import host_proactive, lines

# ---------------------------------------------------------------------------
# JSON schemas shared by entries and tools
# ---------------------------------------------------------------------------

LANG_ENUM = ["auto", "ja", "zh", "en", "ko", "mix"]
CATEGORY_ENUM = ["auto", *lines.CATEGORIES]

TAUNT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "language": {
            "type": "string",
            "enum": LANG_ENUM,
            "default": "auto",
            "description": (
                "auto = 按插件配置（默认日语 ja）；ja/zh/en/ko 指定语言；"
                "mix = 以日语为主随机混入中/英/韩（日语约 60%）。"
            ),
        },
        "category": {
            "type": "string",
            "enum": CATEGORY_ENUM,
            "default": "auto",
            "description": (
                "auto 会根据 situation 自动判断；也可指定 zako（杂鱼）、clumsy（手笨）、"
                "slow（磨蹭）、lose（输了）、idle（猫娘还没到/等待）、clingy（黏人）、"
                "praise（嘴硬夸奖）。"
            ),
        },
        "intensity": {
            "type": "integer",
            "minimum": 1,
            "maximum": 3,
            "default": 2,
            "description": "1=轻飘飘撒娇，2=标准雌小鬼，3=更欠揍（仍只是玩闹）。不传用配置默认值。",
        },
        "situation": {
            "type": "string",
            "maxLength": 300,
            "description": (
                "可选：主人刚发生的事，例如「游戏输了」「等你等太久」「按错键了」。"
                "只用于选分类和让台词更贴情境，不要写隐私信息。"
            ),
        },
    },
    "required": [],
}

LIBRARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "language": {
            "type": "string",
            "enum": ["all", "ja", "zh", "en", "ko"],
            "default": "all",
            "description": "只看某一语言的台词库；all 看全部。",
        },
        "category": {
            "type": "string",
            "enum": ["all", *lines.CATEGORIES],
            "default": "all",
            "description": "只看某一分类；all 看全部。",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 12,
            "default": 4,
            "description": "返回的示例条数。",
        },
    },
    "required": [],
}

MODE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "enabled": {
            "type": "boolean",
            "description": "true = 开启定时自动嘲讽；false = 关闭。",
        },
        "interval_minutes": {
            "type": "integer",
            "minimum": 0,
            "maximum": 180,
            "default": 0,
            "description": (
                "自动嘲讽间隔（分钟）；0 表示跟随宿主主动搭话间隔（最低 5 分钟），"
                "设置 1-4 会按 5 分钟执行。"
            ),
        },
    },
    "required": ["enabled"],
}

STATUS_SCHEMA: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

# ---------------------------------------------------------------------------
# Descriptions (written for the dialogue model and for Market reviewers)
# ---------------------------------------------------------------------------

TAUNT_TOOL_DESCRIPTION = (
    "从「猫娘嘲讽语录库」里取一句，交给你用角色口吻说出来。台词覆盖中文、日语、"
    "英语、韩语，以日语为主（含「杂鱼♡」等雌小鬼台词）。\n\n"
    "调用时机：主人说「骂我」「嘲讽我」「叫我杂鱼」「来点雌小鬼台词」"
    "「用日语嘲讽我」「猫娘还没到，说点什么」；或者主人刚输了/失误了/等太久，"
    "你想主动逗他一句。\n\n"
    "参数：\n"
    "  language: auto（按配置，默认日语）/ ja / zh / en / ko / mix。\n"
    "  category: auto，或 zako / clumsy / slow / lose / idle / clingy / praise。\n"
    "  intensity: 1 轻 / 2 标准 / 3 更欠揍；不传用配置默认值。\n"
    "  situation: 主人刚发生的事，例如「游戏输了」「等你等太久」。\n\n"
    "返回的 line 要原样说出来（最多加一个语气词），不要改成安慰、不要解释台词。"
    "规则：" + lines.TAUNT_RULES
)

TAUNT_NOW_DESCRIPTION = (
    "取一句猫娘嘲讽台词并返回给对话模型，用于「现在立刻嘲讽主人一句」。"
    "覆盖中/日/英/韩，以日语为主；不主动推送消息，由当前对话直接说出来。"
    "适用于「骂我」「嘲讽我」「叫我杂鱼」「用日语嘲讽」「猫娘还没到」等要求。"
)

TAUNT_SPEAK_DESCRIPTION = (
    "让猫娘主动说一句嘲讽：插件会推送一条对话事件，猫娘会单独起一轮回复。"
    "这条入口适合插件中心按钮；**在已经有对话回合时不要同时调用**，"
    "否则会多出一轮。对话中优先用 neko_taunt 或 taunt_now。"
)

TAUNT_PROACTIVE_DESCRIPTION = (
    "按宿主「主动搭话」的开关状态说一句嘲讽：只有 N.E.K.O 的主动搭话开启时才推送，"
    "关闭时安静返回 sent=false，不会打扰主人。适合让猫娘在主动搭话时顺便损一句；"
    "如果主人明确要求「现在就骂我」，用 taunt_speak 或 taunt_now，不要用这个入口。"
)

TAUNT_PREVIEW_DESCRIPTION = (
    "预览一句嘲讽和同分类的其他例子，不推送、不触发对话。适合「先看看有什么台词」"
    "「给我几个例子」「这句中文什么意思」。"
)

TAUNT_LIBRARY_DESCRIPTION = (
    "查看嘲讽语录库的语言/分类统计和示例。适合「你会哪些嘲讽」「日语的有多少句」"
    "「杂鱼台词给我看看」。"
)

TAUNT_STATUS_DESCRIPTION = (
    "查询嘲讽插件状态：默认语言、默认强度、自动嘲讽是否开启、是否跟随宿主主动搭话、"
    "宿主主动搭话的开关/间隔、本次已自动嘲讽次数、语录总数和最近用过的台词 id。"
    "不会推送消息。"
)

TAUNT_MODE_DESCRIPTION = (
    "开关定时自动嘲讽，并调整间隔。自动嘲讽只在主人明确开启后运行，"
    "默认跟随 N.E.K.O 的主动搭话开关：宿主关闭主动搭话时绝不主动打扰；"
    "间隔传 0 表示跟随宿主主动搭话间隔（最低 5 分钟）。"
    "仍受每次会话上限和免打扰时段限制，关闭时立即停止。"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_error(code: str, message: str) -> Dict[str, Any]:
    """The documented LLM-tool error shape."""

    return {"output": {"reason": message}, "is_error": True, "error": code}


def _submitted(result: Any) -> tuple[bool, str]:
    if isinstance(result, Mapping):
        return bool(result.get("submitted")), str(result.get("reason") or "")
    return bool(getattr(result, "submitted", False)), str(getattr(result, "reason", "") or "")


def _lanlan_from_kwargs(kwargs: Mapping[str, Any]) -> str | None:
    ctx = kwargs.get("_ctx")
    if isinstance(ctx, Mapping):
        name = ctx.get("lanlan_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


@neko_plugin
class NekoTauntPlugin(NekoPluginBase):
    """Small, deterministic taunt generator with an opt-in auto mode."""

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = getattr(ctx, "logger", None) or get_plugin_logger(self.plugin_id, "neko_taunt")
        self._cfg: Dict[str, Any] = dict(lines.DEFAULT_CONFIG)
        self._selector = lines.TauntSelector()
        self._host_probe = host_proactive.HostProactiveProbe()
        self._auto_lock = threading.Lock()
        self._auto_last_at = time.time()
        self._auto_count = 0
        self._last_line_id = ""
        self._started_at = time.time()

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _apply_config(self, cfg: Mapping[str, Any]) -> None:
        raw = cfg.get("taunt") if isinstance(cfg.get("taunt"), Mapping) else cfg
        self._cfg = lines.normalize_config(raw)
        self._selector.set_default_language(self._cfg["default_language"])

    async def _load_config(self) -> Dict[str, Any]:
        cfg = await self.config.dump(timeout=5.0)
        self._apply_config(cfg if isinstance(cfg, Mapping) else {})
        return self._cfg

    async def _read_host_proactive(self, *, force: bool = False) -> host_proactive.HostProactiveState:
        """Probe the host without blocking the plugin's event loop."""

        try:
            return await asyncio.to_thread(self._host_probe.get, force=force)
        except Exception as exc:  # the probe itself should already be total
            self.logger.warning("[neko_taunt] host proactive probe failed: {}", type(exc).__name__)
            return host_proactive.HostProactiveState(False, False, 0, "unknown", "probe_failed")

    def _effective_auto_interval_seconds(
        self,
        host_state: host_proactive.HostProactiveState | None,
    ) -> int:
        """Configured minutes win; 0 means follow the host's own interval."""

        host_interval = 0
        if host_state is not None and host_state.available:
            host_interval = host_state.interval_seconds
        return lines.effective_auto_interval_seconds(
            self._cfg.get("auto_taunt_interval_minutes", 0),
            host_interval_seconds=host_interval,
            follow_host=bool(self._cfg.get("follow_host_proactive", True)),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @lifecycle(id="startup")
    async def startup(self, **_):
        cfg = await self._load_config()
        self._auto_last_at = time.time()
        self._auto_count = 0
        self.logger.info(
            "[neko_taunt] ready: {} lines, default={}, auto={}",
            len(lines.LINES), cfg["default_language"], cfg["auto_taunt"],
        )
        return Ok({
            "status": "ready",
            "lines": len(lines.LINES),
            "languages": list(lines.LANGUAGES),
            "default_language": cfg["default_language"],
            "auto_taunt": cfg["auto_taunt"],
            "follow_host_proactive": cfg["follow_host_proactive"],
        })

    @lifecycle(id="shutdown")
    async def shutdown(self, **_):
        self.logger.info("[neko_taunt] shutdown")
        return Ok({"status": "shutdown"})

    @lifecycle(id="config_change")
    async def config_change(self, **_):
        cfg = await self._load_config()
        self._auto_last_at = time.time()
        self.logger.info(
            "[neko_taunt] config changed: default={}, auto={}",
            cfg["default_language"], cfg["auto_taunt"],
        )
        return Ok({"status": "reconfigured", "auto_taunt": cfg["auto_taunt"]})

    # ------------------------------------------------------------------
    # Selection / delivery
    # ------------------------------------------------------------------

    def _pick_line(
        self,
        *,
        language: Any = "auto",
        category: Any = "auto",
        intensity: Any = None,
        situation: Any = "",
    ) -> lines.TauntLine:
        default_level = int(self._cfg.get("default_intensity", 2))
        if intensity in (None, "", 0, "0"):
            level = default_level
        else:
            level = lines.clamp_intensity(intensity, default_level)
        return self._selector.select(
            language=str(language or "auto"),
            category=str(category or "auto"),
            intensity=level,
            situation=str(situation or ""),
            default_language=str(self._cfg.get("default_language", "ja")),
        )

    def _payload(self, line: lines.TauntLine, *, situation: str = "") -> Dict[str, Any]:
        include_romaji = bool(self._cfg.get("include_romaji", True))
        include_translation = bool(self._cfg.get("include_translation", True))
        data = lines.as_payload(
            line,
            include_romaji=include_romaji,
            include_translation=include_translation,
        )
        data["summary"] = (
            f"请用{data['language_name']}说：『{line.text}』。"
            "只输出这一句，保持猫娘语气；不要解释、不要说教。"
        )
        data["instruction"] = lines.delivery_prompt(
            line,
            situation=situation,
            include_romaji=include_romaji,
            include_translation=include_translation,
        )
        return data

    def _push_line(
        self,
        line: lines.TauntLine,
        *,
        situation: str = "",
        auto: bool = False,
        proactive: bool = False,
        target_lanlan: str | None = None,
    ) -> tuple[bool, str]:
        prompt = lines.delivery_prompt(
            line,
            situation=situation,
            include_romaji=bool(self._cfg.get("include_romaji", True)),
            include_translation=bool(self._cfg.get("include_translation", True)),
            auto=auto,
        )
        if proactive:
            event_type = "proactive_taunt"
        elif auto:
            event_type = "auto_taunt"
        else:
            event_type = "taunt"
        result = self.push_message(
            visibility=[],
            ai_behavior="respond",
            parts=[{"type": "text", "text": prompt}],
            source="neko_taunt",
            priority=5 if proactive else (4 if auto else 7),
            target_lanlan=target_lanlan or None,
            metadata={
                "event_type": event_type,
                "line_id": line.id,
                "language": line.lang,
                "category": line.category,
                "intensity": line.intensity,
            },
        )
        submitted, reason = _submitted(result)
        if not submitted:
            self.logger.warning("[neko_taunt] push rejected: {}", reason or "unknown")
        return submitted, reason

    # ------------------------------------------------------------------
    # LLM tool
    # ------------------------------------------------------------------

    @llm_tool(
        name="neko_taunt",
        description=TAUNT_TOOL_DESCRIPTION,
        parameters=TAUNT_SCHEMA,
        timeout=10.0,
    )
    async def neko_taunt_tool(
        self,
        *,
        language: Any = "auto",
        category: Any = "auto",
        intensity: Any = None,
        situation: Any = "",
        **_: Any,
    ):
        try:
            line = self._pick_line(
                language=language,
                category=category,
                intensity=intensity,
                situation=situation,
            )
        except Exception as exc:  # never leak a raw exception into the conversation
            self.logger.exception("[neko_taunt] selection failed")
            return _tool_error("SELECTION_FAILED", f"台词选择失败（{type(exc).__name__}），稍后再试。")
        self._last_line_id = line.id
        return self._payload(line, situation=str(situation or ""))

    # ------------------------------------------------------------------
    # Entries: generation and delivery
    # ------------------------------------------------------------------

    @plugin_entry(
        id="taunt_now",
        name="现在嘲讽我一句",
        description=TAUNT_NOW_DESCRIPTION,
        input_schema=TAUNT_SCHEMA,
        llm_result_fields=["summary", "line", "instruction"],
        metadata={"result_kind": "event", "expires_in_s": 60},
    )
    async def taunt_now_entry(
        self,
        *,
        language: Any = "auto",
        category: Any = "auto",
        intensity: Any = None,
        situation: Any = "",
        **_,
    ):
        try:
            line = self._pick_line(
                language=language,
                category=category,
                intensity=intensity,
                situation=situation,
            )
        except Exception as exc:
            self.logger.exception("[neko_taunt] taunt_now selection failed")
            return Err(SdkError(f"台词选择失败（{type(exc).__name__}）"))
        self._last_line_id = line.id
        return Ok(self._payload(line, situation=str(situation or "")))

    @ui.action(
        id="taunt_speak",
        label="让猫娘嘲讽一句",
        icon="message-circle",
        tone="primary",
        order=10,
    )
    @plugin_entry(
        id="taunt_speak",
        name="让猫娘主动嘲讽一句",
        description=TAUNT_SPEAK_DESCRIPTION,
        input_schema=TAUNT_SCHEMA,
        llm_result_fields=["summary"],
        metadata={"result_kind": "event", "expires_in_s": 30},
    )
    async def taunt_speak_entry(
        self,
        *,
        language: Any = "auto",
        category: Any = "auto",
        intensity: Any = None,
        situation: Any = "",
        **kwargs: Any,
    ):
        try:
            line = self._pick_line(
                language=language,
                category=category,
                intensity=intensity,
                situation=situation,
            )
        except Exception as exc:
            self.logger.exception("[neko_taunt] taunt_speak selection failed")
            return Err(SdkError(f"台词选择失败（{type(exc).__name__}）"))
        self._last_line_id = line.id
        submitted, reason = self._push_line(
            line,
            situation=str(situation or ""),
            target_lanlan=_lanlan_from_kwargs(kwargs),
        )
        if not submitted:
            return Err(SdkError(f"嘲讽没有送出去（{reason or 'transport unavailable'}）"))
        return Ok({
            "summary": f"已经让猫娘用{lines.LANGUAGE_NAMES[line.lang]}说：『{line.text}』。",
            "line": line.text,
            "language": line.lang,
            "category": line.category,
            "intensity": line.intensity,
            "line_id": line.id,
            "submitted": True,
        })

    @plugin_entry(
        id="taunt_proactive",
        name="主动搭话式嘲讽",
        description=TAUNT_PROACTIVE_DESCRIPTION,
        input_schema=TAUNT_SCHEMA,
        llm_result_fields=["summary", "line"],
        metadata={"result_kind": "event", "expires_in_s": 30},
    )
    async def taunt_proactive_entry(
        self,
        *,
        language: Any = "auto",
        category: Any = "auto",
        intensity: Any = None,
        situation: Any = "",
        **kwargs: Any,
    ):
        host_state = await self._read_host_proactive(force=True)
        if not host_state.available:
            return Ok({
                "summary": "读不到 N.E.K.O 的主动搭话设置，这次没有打扰主人。",
                "sent": False,
                "reason": "host_unavailable",
                "host_proactive": host_state.as_dict(),
            })
        if not host_state.enabled:
            return Ok({
                "summary": "N.E.K.O 的主动搭话开关是关闭的，这次没有打扰主人。",
                "sent": False,
                "reason": "host_proactive_off",
                "host_proactive": host_state.as_dict(),
            })
        try:
            line = self._pick_line(
                language=language,
                category=category,
                intensity=intensity,
                situation=situation,
            )
        except Exception as exc:
            self.logger.exception("[neko_taunt] taunt_proactive selection failed")
            return Err(SdkError(f"台词选择失败（{type(exc).__name__}）"))
        self._last_line_id = line.id
        submitted, reason = self._push_line(
            line,
            situation=str(situation or "这是猫娘主动搭话时顺便说的一句。"),
            proactive=True,
            target_lanlan=_lanlan_from_kwargs(kwargs),
        )
        if not submitted:
            return Err(SdkError(f"主动搭话没有送出去（{reason or 'transport unavailable'}）"))
        return Ok({
            "summary": (
                f"已经按 N.E.K.O 的主动搭话设置，让猫娘用{lines.LANGUAGE_NAMES[line.lang]}"
                f"说：『{line.text}』。"
            ),
            "line": line.text,
            "language": line.lang,
            "category": line.category,
            "intensity": line.intensity,
            "line_id": line.id,
            "sent": True,
            "host_proactive": host_state.as_dict(),
        })

    # ------------------------------------------------------------------
    # Entries: library / preview / status / mode
    # ------------------------------------------------------------------

    @ui.action(id="taunt_preview", label="预览一句嘲讽", icon="eye", order=20)
    @plugin_entry(
        id="taunt_preview",
        name="预览嘲讽台词",
        description=TAUNT_PREVIEW_DESCRIPTION,
        input_schema=TAUNT_SCHEMA,
        llm_result_fields=["summary", "line", "variants"],
        metadata={"result_kind": "event", "expires_in_s": 120},
    )
    async def taunt_preview_entry(
        self,
        *,
        language: Any = "auto",
        category: Any = "auto",
        intensity: Any = None,
        situation: Any = "",
        **_,
    ):
        try:
            line = self._pick_line(
                language=language,
                category=category,
                intensity=intensity,
                situation=situation,
            )
        except Exception as exc:
            return Err(SdkError(f"台词选择失败（{type(exc).__name__}）"))
        self._last_line_id = line.id
        variants: List[Dict[str, Any]] = []
        for other in lines.LINES:
            if other.id == line.id:
                continue
            if other.lang == line.lang and other.category == line.category:
                variants.append(lines.as_payload(other))
            if len(variants) >= 3:
                break
        data = self._payload(line, situation=str(situation or ""))
        data["variants"] = variants
        data["summary"] = (
            f"{lines.LANGUAGE_NAMES[line.lang]}·{data['category_name']}："
            f"{line.text}（{line.meaning}）"
        )
        return Ok(data)

    @ui.action(id="taunt_library", label="查看嘲讽语录库", icon="book-open", order=30)
    @plugin_entry(
        id="taunt_library",
        name="查看嘲讽语录库",
        description=TAUNT_LIBRARY_DESCRIPTION,
        input_schema=LIBRARY_SCHEMA,
        llm_result_fields=["summary"],
        metadata={"result_kind": "event", "expires_in_s": 300},
    )
    async def taunt_library_entry(
        self,
        *,
        language: Any = "all",
        category: Any = "all",
        limit: Any = 4,
        **_,
    ):
        lang = str(language or "all").strip().lower()
        cat = str(category or "all").strip().lower()
        try:
            count = max(1, min(12, int(limit)))
        except (TypeError, ValueError):
            count = 4
        data = lines.library_summary(
            language=None if lang in {"", "all"} else lang,
            category=None if cat in {"", "all"} else cat,
            limit=count,
        )
        by_lang = data["by_language"]
        data["summary"] = (
            f"语录库共 {data['total']} 句：日语 {by_lang.get('ja', 0)}、"
            f"中文 {by_lang.get('zh', 0)}、英语 {by_lang.get('en', 0)}、"
            f"韩语 {by_lang.get('ko', 0)}。"
        )
        return Ok(data)

    @ui.action(id="taunt_status", label="刷新嘲讽插件状态", icon="refresh", order=40)
    @plugin_entry(
        id="taunt_status",
        name="查询嘲讽插件状态",
        description=TAUNT_STATUS_DESCRIPTION,
        input_schema=STATUS_SCHEMA,
        llm_result_fields=["summary"],
        metadata={"result_kind": "event", "expires_in_s": 60},
    )
    async def taunt_status_entry(self, **_):
        with self._auto_lock:
            auto_count = self._auto_count
            auto_last_at = self._auto_last_at
        host_state = await self._read_host_proactive(force=True)
        effective_interval = self._effective_auto_interval_seconds(host_state)
        host_note = ""
        if self._cfg.get("follow_host_proactive", True):
            host_note = (
                "；跟随宿主主动搭话（已开启）"
                if host_state.available and host_state.enabled
                else "；跟随宿主主动搭话（当前关闭或不可用，自动嘲讽不会触发）"
            )
        data = {
            "summary": (
                f"语录 {len(lines.LINES)} 句，默认语言 {self._cfg['default_language']}，"
                f"默认强度 {self._cfg['default_intensity']}，"
                f"自动嘲讽 {'开启' if self._cfg['auto_taunt'] else '关闭'}"
                f"（本次已 {auto_count}/{self._cfg['auto_taunt_max_per_session']} 次）"
                f"{host_note}。"
            ),
            "config": dict(self._cfg),
            "counts": lines.counts(),
            "auto_count": auto_count,
            "auto_last_at": auto_last_at,
            "effective_auto_interval_seconds": effective_interval,
            "host_proactive": host_state.as_dict(),
            "started_at": self._started_at,
            "last_line_id": self._last_line_id,
            "recent_line_ids": list(self._selector.recent_ids),
        }
        return Ok(data)

    @plugin_entry(
        id="taunt_mode",
        name="开关定时自动嘲讽",
        description=TAUNT_MODE_DESCRIPTION,
        input_schema=MODE_SCHEMA,
        llm_result_fields=["summary"],
        metadata={"result_kind": "event", "expires_in_s": 30},
    )
    async def taunt_mode_entry(
        self,
        *,
        enabled: Any,
        interval_minutes: Any = None,
        **_,
    ):
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
        enabled = bool(enabled)
        interval: int | None
        if interval_minutes in (None, ""):
            interval = None
        else:
            try:
                interval = int(interval_minutes)
            except (TypeError, ValueError):
                interval = None

        update: Dict[str, Any] = {"auto_taunt": enabled}
        if interval is not None:
            update["auto_taunt_interval_minutes"] = max(0, min(180, interval))
        self._cfg.update(lines.normalize_config({**self._cfg, **update}))
        with self._auto_lock:
            self._auto_last_at = time.time()
            if not enabled:
                self._auto_count = 0

        persisted = False
        try:
            await self.config.update({"taunt": dict(self._cfg)}, timeout=5.0)
            persisted = True
        except Exception as exc:
            self.logger.warning("[neko_taunt] config persist failed: {}", type(exc).__name__)

        minutes = self._cfg["auto_taunt_interval_minutes"]
        follow_host = bool(self._cfg.get("follow_host_proactive", True))
        if enabled and minutes == 0 and follow_host:
            interval_note = "，跟随 N.E.K.O 主动搭话间隔（最低 5 分钟）"
        elif enabled:
            interval_note = f"，间隔 {minutes} 分钟"
        else:
            interval_note = ""
        summary = (
            f"自动嘲讽已{'开启' if enabled else '关闭'}"
            + interval_note
            + ("（已写入配置）" if persisted else "（仅本次运行生效）")
        )
        return Ok({
            "summary": summary,
            "auto_taunt": enabled,
            "interval_minutes": minutes,
            "follow_host_proactive": follow_host,
            "persisted": persisted,
        })

    # ------------------------------------------------------------------
    # Opt-in timer
    # ------------------------------------------------------------------

    @timer_interval(
        id="auto_taunt_tick",
        seconds=60,
        name="自动嘲讽检查",
        auto_start=True,
    )
    async def auto_taunt_tick(self, **_):
        if not self._cfg.get("auto_taunt"):
            return Ok({"skipped": "disabled"})

        if lines.in_quiet_hours(datetime.now(), str(self._cfg.get("quiet_hours", ""))):
            return Ok({"skipped": "quiet_hours"})

        host_state: host_proactive.HostProactiveState | None = None
        if self._cfg.get("follow_host_proactive", True):
            host_state = await self._read_host_proactive()
            if not host_state.available:
                return Ok({"skipped": "host_unavailable"})
            if not host_state.enabled:
                return Ok({"skipped": "host_proactive_off"})

        now = time.time()
        interval_seconds = self._effective_auto_interval_seconds(host_state)
        max_per_session = max(1, int(self._cfg.get("auto_taunt_max_per_session", 8)))

        with self._auto_lock:
            if self._auto_count >= max_per_session:
                return Ok({"skipped": "session_cap"})
            if now - self._auto_last_at < interval_seconds:
                return Ok({"skipped": "interval"})
            # Reserve this slot before the (synchronous) push so two ticks
            # cannot both pass the checks.
            self._auto_last_at = now

        category = self._cfg.get("auto_taunt_category", "auto")
        line = self._pick_line(
            language="auto",
            category=category,
            situation="这是自动嘲讽：主人已经有一阵子没动静了。",
        )
        submitted, reason = self._push_line(line, auto=True)
        if not submitted:
            with self._auto_lock:
                self._auto_last_at = 0.0
            return Ok({"sent": False, "reason": reason, "line_id": line.id})

        with self._auto_lock:
            self._auto_count += 1
            count = self._auto_count
        self._last_line_id = line.id
        self.logger.info("[neko_taunt] auto taunt sent ({}), line={}", count, line.id)
        return Ok({
            "sent": True,
            "line_id": line.id,
            "auto_count": count,
            "follow_host_proactive": bool(self._cfg.get("follow_host_proactive", True)),
            "host_proactive": host_state.as_dict() if host_state is not None else None,
        })