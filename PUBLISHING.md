# 发布到 N.E.K.O 插件市场（neko_taunt）

这份文档记录「猫娘嘲讽·杂鱼」的发布进度、验证证据和剩余的人工审核步骤。

> 市场流程分两段：**首次审核**通过后，Market 才会接受 GitHub Release 并生成可安装版本。
> 当前状态：**审核申请已提交、自动检查已通过、等待人工审核**。
> 代码、测试、GitHub Release 和发布证据都已完成；只差审核员点通过。

---

## 1. 当前状态

| 项 | 状态 |
|---|---|
| 本地开发 + 测试 | ✅ 32 passed / ruff clean |
| 官方 `check -r --market-release` | ✅ passed / payload hash verified |
| 真机导入 + 启动 | ✅ running，错误日志为空 |
| GitHub 仓库 | ✅ https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt |
| Verify CI | ✅ success |
| GitHub Release `v1.0.0` | ✅ 3 个标准资产 |
| Market 首次审核 | 🕒 submission `219`，`submitted`，自动检查 `passed`，`awaiting_human` |
| Market stable 版本 | ⏳ 审核通过后执行 `publish market` |

**唯一剩余动作（需要审核员）**：在 Market 后台通过 submission 219。
通过后运行：

```powershell
cd <N.E.K.O 源码根目录>
uv run neko-plugin publish market `
  https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt/releases/tag/v1.0.0
```

本机 2026-11-14 试运行该命令返回：

```json
{"detail": "release_repo_mismatch: GitHub release 未绑定到唯一的已通过插件"}
```

这不是发布配置错误，而是首次审核尚未通过时的预期拒绝。

---

## 2. 可复现的验证证据

### 2.1 官方发布检查（本地）

```text
neko-plugin check -r --market-release <neko_taunt>
  passed
  version=1.0.0
  payload_hash_verified=True
  tests=passed
```

`GITHUB_REF_NAME` 在本地未设置时会警告 tag/version 对齐未检查；CI 中该检查已通过。

### 2.2 插件内测试与 lint

```text
python -m pytest -q                         32 passed
ruff 0.12.4（CI 参数）                      All checks passed
```

CI 的 ruff 0.12.4 第一次抓到了 `tests/test_lines.py` 的 E402 / I001；
已通过 `conftest.py` + `pytest.importorskip("lines")` 修掉，并在 GitHub Actions 复验。

### 2.3 GitHub Actions

| 工作流 | 结果 | 链接 |
|---|---|---|
| Verify（tag `v1.0.0`） | success | https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt/actions/runs/43551205658 |
| Release（tag `v1.0.0`） | success | https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt/actions/runs/43551205744 |

> Release 工作流 pin 到 `0ac2afd0e40250a4cff1501a32f2db1124fe971d`：
> 2026-11-14 当天 upstream `@main` 的 `plugin-market-release.yml` 作为 reusable
> workflow 会 `startup_failure`（same-repo Verify `@main` 正常）。诊断分支用
> pinned commit 调用后正常进入 job 并按预期报 `requires a tag ref`，因此 pin
> 是该 upstream 故障的规避，不是插件配置问题。

### 2.4 GitHub Release

- 页面：https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt/releases/tag/v1.0.0
- tag/commit：`v1.0.0` → `739c3fcf1b89da5736464bec8c4edc590b051b81`
- 资产：
  - `neko_taunt.neko-plugin`（59,592 bytes）
  - `neko_taunt.market-release-check.txt`
  - `market-evidence.json`

`market-evidence.json` 登记值：

```json
{
  "plugin_id": "neko_taunt",
  "version": "1.0.0",
  "source_commit": "739c3fcf1b89da5736464bec8c4edc590b051b81",
  "package": {
    "name": "neko_taunt.neko-plugin",
    "sha256": "44373f6e85333e12a739c73a5f346a9696153891005b97848a2281806565b5a7",
    "payload_hash": "1ad7027f09d3c16abcc79b01c89a3df9418da192bcfa315950dde7b63e0f0465",
    "size": 59592
  },
  "workflow_run_id": 43551205744
}
```

本地下载 Release 包后复核：

```text
sha256 == 44373f6e…  OK
runtime files 与真机已启动版本逐字节一致（仅 tests 文件不同）  OK
```

### 2.5 真机宿主验证（Windows，Steam 版 N.E.K.O）

```text
导入 .neko-plugin                             payload_hash_verified=true
启动插件                                      success
日志                                         ready: 146 lines, default=ja, auto=False
入口列表                                     6 个插件入口 + 1 个 LLM 工具
neko_taunt 工具                              ToolRegistry registered ×3（三个猫娘）
taunt_now                                    返回 ja-zako-03，situation 正确进入提示
taunt_library                                146 句 / ja70 zh31 en24 ko21
taunt_status                                 默认 ja、强度 2、自动关闭
taunt_mode(true, 5min)                       持久化成功，配置表其余键未丢失
taunt_speak                                   push_message submitted=true
taunt_mode(false, 20min)                     恢复默认，自动关闭
插件错误日志                                  空
```

> 尚未在真实对话会话里让三个猫娘逐个开口；`taunt_speak` 的 push 已提交到宿主，
> 测试时宿主没有活动会话，因此没有产生 LLM 回复。这一点不冒充已验证。

---

## 3. Market 投稿记录

| 项 | 值 |
|---|---|
| submission id | `219` |
| snapshot id | `298` |
| 状态 | `submitted` |
| decision | 空（等待人工） |
| 审核阶段 | `awaiting_human` / `next_actor=reviewer` |
| 自动检查 | `idle` / `passed` / 0 findings |
| 提交 commit | `bb224a3acebfa51b8889d6fffb0ed3f46c43bb54` |
| 名称 | 猫娘嘲讽·杂鱼 |
| slug | `neko_taunt` |
| 分区 | 娱乐 |
| 标签 | 娱乐 / 互动 / 功能 / 情感 |
| license | MIT |

投稿使用的是桌面端 Market OAuth（`~/.neko/market_auth.json`），
`repository-preview` 返回 `identity_status=matched`、
`workflow_status=available`，`preflight` 返回 `ready=true`、0 issues。

> 审核提交后 main 又前进了两个 docs/CI 提交（`3c64b48`、`739c3fc`）；
> 运行时代码未变，Release 的 payload 与审核快照一致到可执行文件级别。
> 审核员若要求按最新 commit 重新绑定，可用 submission 的 Revision 流程更新；
> 当前不主动重置审核队列。

---

## 4. 市场审核关注点（本插件对应做法）

| 审核关注 | 本插件的处理 |
|---|---|
| 能否加载、entry 是否 async | 6 个 `@plugin_entry` 全部 `async def`；真机启动成功 |
| 是否会在启用时突然开骂 | `auto_taunt=false`；只有 `taunt_speak` / 用户请求 / 显式开启自动模式才推送 |
| 内容是否越界 | 146 句手写台词，只含「杂鱼/笨蛋/菜/慢」级词汇；提示固定带禁止人身攻击/歧视/性暗示/威胁的规则 |
| 自动模式是否失控 | 最短 5 分钟、每次会话最多 8 次、默认 23:00–08:00 免打扰、失败不刷屏、说停即停 |
| 是否读隐私 | 不联网、不读聊天/屏幕/剪贴板/文件；不持久化对话 |
| 语言支持 | 中文/日语/英语/韩语台词；i18n 四语；配置说明四语 |
| 依赖是否可复现 | 无第三方 Python 依赖，无 `requirements.txt`，无 `vendor/` |
| 测试 | 32 个纯 stdlib 测试，Linux CI 可跑 |
| 文档 | README / DESIGN / docs/guide.md / PUBLISHING.md |

---

## 5. 本机发布环境备注（不影响 CI/Market）

这台 Windows 机器上 DSH 子进程无法写 `%LOCALAPPDATA%`，导致：

- `portalocker` 无法在 `%LOCALAPPDATA%\neko-plugin\sync-locks` 建锁；
- `uvx` 无法使用 `%LOCALAPPDATA%\uv\cache`；
- Python `httpx` 不信任本机代理的 GitHub 证书链。

本机用三个临时措施绕过后完成了 GitHub Release：

1. 把 `%LOCALAPPDATA%\neko-plugin\sync-locks` 指向工作区目录的 junction；
2. 用 `tools/uvx_shim.py` + `.bin\uvx.exe` 把 `uvx ruff==0.12.4` 路由到已安装的 ruff；
3. `SSL_CERT_FILE` 指向 certifi + Windows 根证书合并的 PEM。

这些只影响本机 CLI 发布，GitHub Actions 和 Market 使用的是标准环境；
不要把 junction、`.certs`、`.uv-cache` 提交进插件仓库。

---

## 6. 版本号纪律

- 插件 ID `neko_taunt` 发布后不再变。
- 已发布过的版本号不能复用；改代码就升版本（例如 `1.0.1`），commit、push、再 `publish`。
- 撤回是单向的：撤回过或发布过的版本号都不能再用，只能发新版本。