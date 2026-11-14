# 发布到 N.E.K.O 插件市场（neko_taunt）

这份文档记录「猫娘嘲讽·杂鱼」的发布进度、验证证据和需要账号才能完成的步骤。

> 市场流程分两段：**首次审核在网页提交**（需要作者账号登录），
> 审核通过后 `neko-plugin publish` 才会创建 GitHub Release 并在市场生成可安装版本。
> `publish` 不能替代首次投稿。

---

## 1. 本地验证（已完成）

在 N.E.K.O 源码目录（`N.E.K.O/`）用官方 CLI：

```text
neko-plugin check -r <neko_taunt 路径>       passed
  version=1.0.0
  package_sha256=a5a136721282e54d0bec369e813ab31cb5dcfbe476c394be9747d302f9287ffd
  payload_hash=8cca06bf12f8c853081d1940c5250024e81e18415547103982d6b86274e01e8d
  payload_hash_verified=True
  tests=passed
```

插件内测试与 lint：

```text
python -m pytest -q                         30 passed
python -m ruff check .                      All checks passed
```

真机宿主导入 + 启动（Windows，Steam 版 N.E.K.O）：

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
> 当前宿主没有活动会话，因此没有产生 LLM 回复。这一点不冒充已验证。

---

## 2. 需要账号才能做的三步

### 2.1 建仓库并推送源码

GitHub 公开空仓库，名称必须是：

```text
n.e.k.o_plugin_neko_taunt
```

```powershell
cd <neko_taunt 目录>
git init
git add .
git commit -m "feat: multilingual catgirl taunts for N.E.K.O"
git remote add origin https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt.git
git push -u origin main
```

### 2.2 等待 Verify 工作流

打开仓库 **Actions**，等 `Verify N.E.K.O Plugin` 变绿。它会在 Ubuntu 上跑
ruff → `sync` → `check -r` → 构建 → payload hash 校验。

### 2.3 提交首次审核

1. 打开 <https://market.project-neko.cn/#/upload> 并登录。
2. 填仓库地址 `https://github.com/mintpixiu/n.e.k.o_plugin_neko_taunt`。
3. 点「读取仓库信息」，确认名称；分区选「娱乐」或「功能」，标签选 1–5 个。
4. 提交审核申请；在「我的插件」里看检查结果与审核意见。

审核通过后：

```powershell
cd <N.E.K.O 源码根目录>
uv run neko-plugin publish "C:\path\to\neko_taunt"
```

它会再次跑发布检查 → 确认 HEAD 已推送 → 打 `v1.0.0` 标签 → 等 Actions 产出
`neko_taunt.neko-plugin`、`neko_taunt.market-release-check.txt`、`market-evidence.json`
→ 通知市场发布 stable 版本。

---

## 3. 审核时最可能被看的点（本插件的对应做法）

| 审核关注 | 本插件的处理 |
|---|---|
| 能否加载、entry 是否 async | 6 个 `@plugin_entry` 全部 `async def`；真机启动成功 |
| 是否会在启用时突然开骂 | `auto_taunt=false`；只有 `taunt_speak` / 用户请求 / 显式开启自动模式才推送 |
| 内容是否越界 | 146 句手写台词，只含「杂鱼/笨蛋/菜/慢」级词汇；提示固定带禁止人身攻击/歧视/性暗示/威胁的规则 |
| 自动模式是否失控 | 最短 5 分钟、每次会话最多 8 次、默认 23:00–08:00 免打扰、失败不刷屏、说停即停 |
| 是否读隐私 | 不联网、不读聊天/屏幕/剪贴板/文件；不持久化对话 |
| 语言支持 | 中文/日语/英语/韩语台词；i18n 四语；配置说明四语 |
| 依赖是否可复现 | 无第三方 Python 依赖，无 `requirements.txt`，无 `vendor/` |
| 测试 | 30 个纯 stdlib 测试，Linux CI 可跑 |
| 文档 | README / DESIGN / docs/guide.md / PUBLISHING.md |

---

## 4. 发布后自查

```powershell
# 1. GitHub Releases 里有三个资产
#    neko_taunt.neko-plugin / neko_taunt.market-release-check.txt / market-evidence.json
# 2. 市场详情页出现 1.0.0，stable 最新版不为空
# 3. 在 N.E.K.O → 插件管理 → 导入 下载回来的包，再说「骂我一句」验证
```

---

## 5. 版本号纪律

- 插件 ID `neko_taunt` 发布后不再变。
- 已发布过的版本号不能复用；改代码就升版本（例如 `1.0.1`），commit、push、再 `publish`。
- 撤回是单向的：撤回过或发布过的版本号都不能再用，只能发新版本。

---

## 6. 当前状态

| 项 | 状态 |
|---|---|
| 本地开发 + 测试 | ✅ 30 passed / ruff clean |
| 官方 `check -r` | ✅ passed / payload hash verified |
| 真机导入 + 启动 | ✅ running，错误日志为空 |
| GitHub 仓库 | ⏳ 待创建/推送 |
| Verify CI | ⏳ 待跑 |
| 市场首次审核 | ⏳ 待提交（需作者账号登录） |
| GitHub Release + Market stable | ⏳ 审核通过后执行 |