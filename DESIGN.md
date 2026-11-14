# DESIGN — 猫娘嘲讽·杂鱼

## 1. 问题

让对话模型「自由发挥骂人」有三个问题：

1. **不稳定**：同一句「骂我」可能得到安慰、说教、或者一段完全跑偏的发挥。
2. **越界**：模型容易滑向真正的人身攻击、外貌羞辱或性暗示，市场审核和用户体验都不可接受。
3. **多语言质量不可控**：日语雌小鬼的语感（拖长音、♡、自称、终助词）很难要求模型每次现编。

所以这个插件把「说什么」和「怎么说」拆开：

- 插件负责**选一句手写的、可审计的台词**，并给出中文释义、罗马音和语气提示。
- 宿主里的猫娘负责**用自己的声音说出来**，保留称呼、停顿和角色感。
- 提示里固定带边界规则；用户说停就停。

## 2. 非目标

- 不调用任何模型 API（没有密钥、没有外部网络）。
- 唯一的 HTTP 请求是只读 `GET http://127.0.0.1:48911/api/proactive/mode`，
  用于读取宿主自己的「主动搭话」开关；代码拒绝非 loopback 地址。
- 不读聊天历史、屏幕、剪贴板、文件。
- 不修改宿主的人设 / system prompt。
- 不生成新的辱骂词；台词库是固定集合。
- 不做「越骂越狠」的升级机制；强度只是选词档位。

## 3. 模块

```text
┌─────────────────────────────────────────────────────────────┐
│ N.E.K.O Host                                                │
│  ┌───────────────────────┐      ┌────────────────────────┐  │
│  │ Dialogue LLM          │      │ Plugin Center           │  │
│  │  @llm_tool neko_taunt │      │  entries / UI actions   │  │
│  └───────────┬───────────┘      └───────────┬────────────┘  │
│              │ tool call                    │ trigger        │
│              ▼                              ▼                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Plugin process: NekoTauntPlugin                       │  │
│  │  ├─ taunt_now / taunt_preview / taunt_library         │  │
│  │  ├─ taunt_speak  ── push_message(ai_behavior=respond) │  │
│  │  ├─ taunt_proactive ── 先读宿主主动搭话开关            │  │
│  │  ├─ taunt_status / taunt_mode                         │  │
│  │  ├─ auto_taunt_tick (opt-in timer)                    │  │
│  │  ├─ host_proactive.py: loopback GET /api/proactive/mode│  │
│  │  └─ lines.py: 146 lines + TauntSelector               │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

| 文件 | 职责 |
|---|---|
| `lines.py` | 纯数据 + 纯逻辑：台词、分类、语言权重、情境推断、免打扰、提示渲染。无 SDK 依赖，可在 Linux CI 直接 import。 |
| `host_proactive.py` | 只读宿主主动搭话开关：loopback URL 校验、响应解析、30 秒缓存。 |
| `__init__.py` | SDK facade：生命周期、配置、LLM 工具、七个入口、可选的定时器与 `push_message`。 |
| `plugin.toml` | 身份、SDK 约束、`[taunt]` 默认配置。 |
| `config.schema.json` | 配置面板字段与四语说明。 |
| `i18n/` | 插件名 / 描述 / 按钮的 zh-CN、en、ja、ko。 |

## 4. 数据模型

```python
@dataclass(frozen=True)
class TauntLine:
    id: str          # ja-zako-01，发布后不变
    lang: str        # ja | zh | en | ko
    category: str    # zako | clumsy | slow | lose | idle | clingy | praise
    intensity: int   # 1 | 2 | 3
    text: str        # 目标语言原句
    romaji: str      # 仅日语，帮助模型读准
    meaning: str     # 中文释义，帮助模型理解而不是猜
    tone: str        # 中文语气提示
```

- **id 稳定**：便于诊断、去重、测试；已发布版本不改旧 id。
- **`meaning` 是安全阀**：模型知道「ざぁこ」= 杂鱼，不会误判成严重侮辱而拒绝或过度道歉。
- **无持久化**：台词库随包发布；运行期只在内存里存 recent ids 和自动计数。

### 规模

| 语言 | 句数 |
|---|---|
| 日语 | 70 |
| 中文 | 31 |
| 英语 | 24 |
| 韩语 | 21 |
| **合计** | **146** |

日语刻意占约一半，满足「最主要的还是日语」。

## 5. 选择算法

`TauntSelector.select(language, category, intensity, situation)`：

1. **语言**
   - `auto` → 配置 `default_language`（默认 `ja`）。
   - `mix` → 按 `ja 0.60 / zh 0.15 / en 0.15 / ko 0.10` 加权抽一个语言。
   - 未知值 → 默认语言。

2. **分类**
   - 指定分类直接用。
   - `auto` → 先按 `situation` 关键词推断（四语言都覆盖）；仍推断不出就按权重抽：
     `zako .26 / idle .18 / clumsy .14 / slow .12 / lose .12 / clingy .09 / praise .09`。

3. **强度**
   - 只从 `intensity <= 请求值` 的池子里选。请求 2 时不会冒出 3 级台词。
   - 配置默认值在未传 `intensity` 时使用。

4. **回退阶梯**（保证永远不抛异常）
   - 同语言 + 同分类 + 强度内；
   - 同语言 + 同分类（任意强度）；
   - 同分类 + 强度内（优先日语）；
   - 全部台词中强度内；
   - 全部台词。

5. **不重复**
   - `deque(maxlen=12)` 记住最近 id，优先选不在 recent 的。
   - 池子全被 recent 覆盖时清空约束，避免死循环。
   - 线程安全：`threading.Lock` 保护 deque，entry 与 timer 可并发。

## 6. 交付路径

### 6.1 对话期：`@llm_tool(name="neko_taunt")`

返回：

```json
{
  "line_id": "ja-zako-01",
  "language": "ja",
  "language_name": "日语",
  "category": "zako",
  "intensity": 1,
  "text": "ふふっ、ざぁこ♡ ざぁこ♡",
  "romaji": "fufu, zaa-ko♡ zaa-ko♡",
  "translation_zh": "呵呵，杂鱼♡ 杂鱼♡",
  "tone": "轻飘飘地拖长音",
  "summary": "请用日语说：『…』。只输出这一句…",
  "instruction": "现在是猫娘嘲讽时间。…规则：只许玩闹式嘲讽…"
}
```

模型看到 `summary` / `line` / `instruction`，直接在当前回合说出来。

### 6.2 Agent 入口：`taunt_now`

同样的素材，但作为 `@plugin_entry` 返回。用于宿主 Agent 路由（用户说「骂我」时由宿主选插件），
不主动推送，避免与 Agent 自己的回复重复。

### 6.3 主动推送：`taunt_speak` / `taunt_proactive` / 自动模式

`push_message(visibility=[], ai_behavior="respond", parts=[text])`：

- `visibility=[]`：用户看不到插件原文，只看到猫娘生成的那一句。
- `ai_behavior="respond"`：宿主立即起一轮对话。
- 文本里带 `{MASTER_NAME}` 占位符，由宿主按 session 展开（插件不知道消息会落到哪个角色）。
- `target_lanlan` 从入口 `_ctx` 取，保证多角色时路由正确。

`taunt_speak` 是用户明确要求时的立即版，不检查宿主开关。
`taunt_proactive` 在推送前先读宿主的「主动搭话」开关：关闭或不可用时只返回
`sent=false`，不推送，避免和宿主自己的主动搭话策略打架。自动模式同样使用
这个开关（见第 7 节）。

### 6.4 预览 / 语录库 / 状态

纯读取，不推送。`metadata.result_kind="event"`，避免宿主把查询回执当成「任务完成汇报」。

## 7. 自动模式状态机

```text
startup: auto_taunt=false, last=now, count=0
   │
   ├─ user taunt_mode(true) / 配置开启
   ▼
tick every 60s:
   ├─ disabled            → skip
   ├─ quiet_hours         → skip
   ├─ follow_host_proactive?
   │    ├─ probe loopback /api/proactive/mode
   │    ├─ unavailable    → skip host_unavailable
   │    └─ disabled       → skip host_proactive_off
   ├─ count >= max        → skip
   ├─ now-last < interval → skip
   │    (interval = configured minutes, or host interval when configured 0)
   ├─ reserve slot (last=now)
   ├─ select line (category=auto_taunt_category)
   ├─ push_message
   │    ├─ submitted → count += 1
   │    └─ rejected  → last=0（下个 tick 可重试）
   └─ end
   │
   ├─ user taunt_mode(false) → stop immediately, count=0
   └─ shutdown → timer stops with process
```

设计取舍：

- 定时器固定 60 秒 tick；配置 0 时跟随宿主 `proactiveChatInterval`，最低 5 分钟，避免频繁起 LLM 轮次。
- `follow_host_proactive=true` 时，宿主主动搭话关闭/不可用是**硬门**：自动模式不推送，也不会偷偷退回独立计时。
- 上限是「每次插件会话」，不持久化；重启后重新计数。
- 免打扰用本地时钟；支持 `23:00-08:00` 跨午夜。
- 推送失败不增加计数，但把 `last` 置 0，下一次 tick 可重试；不会在同一 tick 内循环重试。

## 8. 配置与错误处理

- `config.dump()` 读取 `[taunt]`；`normalize_config()` 对每个字段做类型/范围/枚举收敛，坏值回默认。
- `taunt_mode` 先改内存，再 `config.update({"taunt": 当前完整表})`；持久化失败仍生效，返回 `persisted=false`。
- LLM 工具错误用文档形状：`{"output": {"reason": ...}, "is_error": true, "error": "CODE"}`。
- 入口错误用 `Err(SdkError(...))`。
- 失败日志只写 id / 分类 / 原因，不写主人原文或对话内容。
- 宿主探测失败只记录异常类型，不把 HTML/响应体写日志。

## 9. 测试策略

| 层 | 测试 | 说明 |
|---|---|---|
| 数据 | id 唯一、语言/分类/强度合法、日语有罗马音、全部有释义 | 防止手写数据漏字段 |
| 选择 | 语言/分类/强度约束、10 次不重复、mix 日语占比、异常输入 | 纯函数，固定 seed |
| 情境 | 12 个中/日/英/韩关键词 | 防止关键词表退化 |
| 时间 | 跨午夜、边界、坏格式 | 不依赖当前时间 |
| 宿主开关 | loopback URL 校验、响应解析、30 秒缓存、非 loopback 拒绝且不发请求 | 不依赖真实主服务 |
| 提示 | 包含原句、释义、语气、`{MASTER_NAME}`、边界 | 交付契约 |
| 清单 | 入口全 async、工具名、i18n 键集、schema 键集 | 市场/宿主契约 |
| 静态 | 无 requirements.txt / vendor / 外部网络 import | 隐私与打包规则 |

所有测试只用 stdlib；宿主 SDK 不被 import，所以 Linux CI 不需要 N.E.K.O 运行时。

## 10. 为什么不做「更狠」的档位

- 市场审核和真实用户都可能把「狠」理解成攻击；插件定位是**角色扮演式逗弄**。
- 真正有效的「狠」来自角色关系和语境，不是词表里加脏话。
- 3 级已经包含「能一直输也是一种才能」这类更欠揍的句子，但仍在玩闹范围。
- 用户想要更过分的，应该明确去用别的工具，而不是让一个陪伴插件默认越界。