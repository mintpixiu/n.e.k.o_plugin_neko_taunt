# 发布到 N.E.K.O 插件市场（neko_taunt）

> 状态：**已上架**。市场插件 id `158`，stable 最新版本 `1.0.2`，
> `verification_status: passed`。
> 市场页面：https://market.project-neko.cn/#/plugin/158

---

## 1. 最终状态

| 项 | 值 |
|---|---|
| Market 插件 | id `158` / slug `neko_taunt` / status `approved` |
| 市场页面 | https://market.project-neko.cn/#/plugin/158 |
| stable 最新版 | `1.0.2`（`is_latest=true`） |
| 市场验证 | `passed` — 标准 GitHub Actions 发布证据已通过校验 |
| 首次审核 submission | `219`，`approved`（2026-11-14T10:35:09Z） |
| GitHub 仓库 | https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt |
| 当前 Release | https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt/releases/tag/v1.0.2 |
| Release commit | `8a68b2a312b6ff85a5facc88f69cb46ddc07b7de` |
| Release CI | https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt/actions/runs/43591853831 |
| 包大小 | 68,600 bytes |
| 包 sha256 | `b455ad02426c198d2a8019c3dec45c8b2b6408fb24a672c60202560774dece71` |
| payload hash | `c1c81a0c247e051141c1e4a0819619a9a6d3078a9cd3a5881a4b3de225006a6d` |

本机已验证：Release 包 sha256 与市场登记一致；包内运行时代码与真机启动版本逐字节一致。

---

## 2. 1.0.2 的「配合主动搭话」

这是本轮新增的核心能力：

- `follow_host_proactive = true`（默认）：自动嘲讽只在 N.E.K.O 自己的「主动搭话」开关打开时运行；
- `auto_taunt_interval_minutes = 0`（默认）：跟随宿主 `proactiveChatInterval`，最低 5 分钟，
  不会比宿主更频繁；
- 宿主主服务不可达时自动模式安静跳过，不会乱猜、不会偷偷退回独立计时；
- 新增 `taunt_proactive` 入口：宿主主动搭话关闭时只返回 `sent=false`，不推送；
- 新增 `host_proactive.py`：只对 `http://127.0.0.1:48911/api/proactive/mode` 做只读 GET，
  代码拒绝任何非 loopback 地址；30 秒缓存，不影响宿主；
- `taunt_status` 会显示宿主主动搭话是否可用、是否开启、宿主间隔和实际生效间隔。

用户明确说「现在就骂我」时仍用 `taunt_speak` / `taunt_now`，不受宿主主动搭话开关限制。

---

## 3. 验证证据

### 3.1 插件内测试与 lint

```text
python -m pytest -q                         40 passed
ruff 0.12.4（CI 参数）                      All checks passed
```

覆盖：146 句台词数据、选择器、四语情境推断、跨午夜免打扰、提示契约、
宿主主动搭话 URL 校验/解析/缓存、清单/i18n/schema/入口 async、无外部网络 import。

### 3.2 官方发布检查

```text
neko-plugin check -r --market-release <neko_taunt>
  passed
  version=1.0.2
  payload_hash_verified=True
  tests=passed
```

GitHub Actions：

| 工作流 | 结果 |
|---|---|
| Verify（tag `v1.0.2`） | success |
| Release（tag `v1.0.2`） | success（含 build provenance attestation） |

### 3.3 真机宿主验证（Windows，Steam 版 N.E.K.O）

```text
导入/启动                                    success
日志                                         ready: 146 lines, default=ja, auto=False
入口列表                                     7 个插件入口 + 1 个 LLM 工具
taunt_status                                 host_proactive.available=true, enabled=true, interval=120, mode=custom
taunt_mode(true, 0)                          持久化成功；effective_auto_interval_seconds=300
taunt_proactive                               sent=true，宿主开启时推送成功
taunt_mode(false, 0)                         恢复默认，自动关闭
插件错误日志                                  空
```

> 没有改动宿主的主动搭话设置；测试只读取了它。真实对话里让猫娘逐个角色开口
> 仍未逐条验证，这一点不冒充已验证。

---

## 4. 发布过程中踩到的两个平台细节

这两个都不是插件逻辑问题，但会影响发版：

1. **reusable workflow 权限升级**
   当前上游 `plugin-market-release.yml@main` 的 `attest` job 请求
   `contents: write` + `id-token: write` + `attestations: write`。
   调用方只给 `contents: write` 时，GitHub 在启动阶段直接 `startup_failure`。
   修法：`release.yml` 顶层同时授予三项权限。

2. **Market 要求标准工作流的 attestation**
   早期用 pin 到旧 commit 的 release workflow 能生成包，但 Market 返回
   `release_publish_failed: market-evidence.json 未绑定标准 N.E.K.O release workflow`。
   切回 `@main` + 上面的权限后，Release CI 的 `attest-build-provenance` 成功，
   Market 接受并返回 HTTP 201。

---

## 5. 版本历史

| 版本 | 内容 | 市场 |
|---|---|---|
| `1.0.0` | 146 句四语台词、6 入口、可选自动嘲讽 | 审核通过的基础版本，未发布 Market stable |
| `1.0.1` | 新增主动搭话跟随/`taunt_proactive` | GitHub Release；Market 以非标准 workflow 证据拒绝 |
| `1.0.2` | 标准 workflow + attestation，运行时代码同 1.0.1 | **Market stable，当前最新** |

版本号纪律：已发布过的版本号不复用；改代码必须升版本。

---

## 6. 本机发布环境备注（不影响 CI/Market）

这台 Windows 机器上 DSH 子进程无法写 `%LOCALAPPDATA%`，因此发布时临时用了：

1. `%LOCALAPPDATA%\neko-plugin\sync-locks` → 工作区目录的 junction；
2. `tools/uvx_shim.py` + `.bin\uvx.exe` 把 `uvx ruff==0.12.4` 路由到本地 ruff；
3. `SSL_CERT_FILE` 指向 certifi + Windows 根证书合并的 PEM；
4. `UV_CACHE_DIR` / `UV_TOOL_DIR` 指向工作区。

GitHub Actions 和 Market 使用标准环境，不依赖这些本机措施。
不要把这些临时目录提交进插件仓库。</content>