<p align="center"><strong>中文</strong> · <a href="README_en.md">English</a> · <a href="README_ru.md">Русский</a> · <a href="README_ja.md">日本語</a></p>

<div align="center">

<img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_reverse_searcher/main/logo.png" width="120" alt="ReverseSearcher Logo" />

# 图片反搜助手

**五大引擎反向搜图** —— AnimeTrace 认角色 · SauceNAO 找出处 · Google Lens 兜底 · Yandex 找相似 · ENtai 搜本子

[![Version](https://img.shields.io/badge/version-1.1.2-blue.svg)](https://github.com/OMSociety/astrbot_plugin_reverse_searcher)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/OMSociety/astrbot_plugin_reverse_searcher)](https://github.com/OMSociety/astrbot_plugin_reverse_searcher/stargazers)
[![Issues](https://img.shields.io/github/issues/OMSociety/astrbot_plugin_reverse_searcher)](https://github.com/OMSociety/astrbot_plugin_reverse_searcher/issues)

[核心特性](#核心特性) • [功能概览](#功能概览) • [快速开始](#快速开始) • [支持的搜索引擎](#支持的搜索引擎) • [配置项说明](#配置项说明) • [LLM 可调用工具](#llm-可调用工具) • [常见问题](#常见问题) • [更新日志](CHANGELOG.md)

</div>

> 本项目由 AI 编写，部分源码基于 [astrbot_plugin_img_rev_searcher_Ver2](https://github.com/Yanlyn/astrbot_plugin_img_rev_searcher_Ver2)

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **六大搜索引擎** | AnimeTrace 认角色、SauceNAO 找出处、Google Lens 综合兜底、Yandex 找相似、E-Hentai 搜本子、Soutubot 查 nhentai 图源，各司其职 |
| **AI 生成检测** | 接入 [AI or Not](https://www.aiornot.com/)，每次识图前先判断图片是否为 AI 生成（徽章/文本展示）；额度用完自动切到免费的 Illuminarty 备用，也可用 `ai` 引擎只检测不反搜 |
| **关键词触发** | 发送 `以图搜图` + 图片即可搜索，支持引擎别名快捷指定（`a`/`s`/`e`/`n`/`g`/`y`） |
| **LLM 主动搜图** | 机器人根据对话意图自主判断何时搜图、用哪个引擎，无需手动指令 |
| **意图路由** | 基于关键词加权匹配自动选择最优引擎——说「这是谁」自动走 AnimeTrace |
| **精美结果卡片** | 搜索结果渲染为现代卡片图片（引擎色渐变 Header、相似度彩色徽章、AI 检测标签），云端文转图不可达时自动降级 PIL |
| **多引擎自由切换** | 引擎按需启停，失败时提示原因，可手动更换引擎重搜 |

---

## 功能概览

### 搜索卡片渲染
搜索完成后自动生成一张卡片图片：源图 + 结果缩略图同框，相似度一目了然：

<img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_reverse_searcher/main/docs/search_example.png" alt="搜索结果卡片示例" width="480" />

### 关键词触发
发送 `以图搜图` 并附上图片（或回复引用消息），即可按引导完成搜索：

```
用户: 以图搜图
🤖 → 发送引擎介绍卡片，请选择引擎
用户: a 这张图
🤖 → 已选择 AnimeTrace，正在搜索...
     → 发送搜索结果卡片 ✅
```

### LLM 主动搜图
机器人内置 `reverse_search` 工具，根据对话内容自主判断是否搜图：

```
用户: 芙兰，帮我看看这张图的角色是谁
🤖 → reverse_search(intent=找角色)
    🔍 [AnimeTrace] 找到 3 个结果
    角色: 芙兰朵露·斯卡蕾特 | 作品: 东方Project...
```

### 意图路由
无需指定引擎，说意图即可自动选：

| 意图 | 自动路由 |
|------|---------|
| 「这是谁 / 哪个角色 / cos」 | → AnimeTrace |
| 「找出处 / 找作者 / pixiv pid」 | → SauceNAO |
| 「找相似图 / 像这个」 | → Yandex |
| 「找本子 / 同人」 | → E-Hentai |
| 「找原图 / 综合搜索」 | → Google |

---

## 快速开始

### 第一步：安装

AstrBot WebUI → 插件市场 → 搜索 `astrbot_plugin_reverse_searcher`

### 第二步：最小配置（装好即用）

**无需任何配置**即可使用 AnimeTrace、Yandex、E-Hentai、Soutubot 四个免 Key 引擎：

1. 重启 AstrBot 后，直接发送 `以图搜图` + 图片
2. 或直接对机器人说「帮我看看这个角色是谁」让 LLM 自动搜图

> **提示**：可选增强：配置 SauceNAO `api_key`（[申请地址](https://saucenao.com/user.php)）解锁画师/出处搜索；Google 引擎需 [SerpAPI Key](https://serpapi.com/)；ExHentai 需有效 Cookie。

### 依赖安装
插件依赖 `httpx`、`Pillow`、`pyquery` 等，AstrBot 安装插件时自动处理。

---

## 支持的搜索引擎

| 引擎 | 说明 | 需要配置 |
|:----|:----|:----|
| **animetrace** | 动漫角色识别（最强），返回作品名 + 角色名 | 免配置 |
| **yandex** | 相似图片搜索 | 建议配 Cookie（Yandex 反爬严格，未配置时可能 CAPTCHA/无结果） |
| **ehentai** | E-Hentai 同人本搜索 | 免配置（ExHentai 需 Cookie） |
| **soutubot** | 通过 [soutubot.moe](https://soutubot.moe/) 查 nhentai 图源（标题/作者/页数/标签/直达页码） | 免配置（站点有排队限流；失败时控制台会以 WARNING 输出状态码/响应片段便于排查） |
| **saucenao** | 综合出处搜索，Pixiv 插画首选 | 建议配 `api_key` |
| **google** | Google Lens 综合兜底 | 需 SerpAPI Key |
| **ai** | AI 生成检测：判断图片是不是 AI 画的，**不做反向搜索** | 需 AI or Not API Key 或启用 Illuminarty 备用 |

---

## 配置项说明

### 顶层配置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `output_mode` | string | `card` | 结果输出方式：`card` 渲染为卡片图片（带缩略图/相似度徽章）；`text` 纯文本输出，**按结果逐条发送**（每条附带该结果的图片，不使用卡片设计） |
| `text_merge` | bool | `true` | `text` 模式下把「汇总 + 每条结果」合并为一条**合并转发（聊天记录）**；仅 QQ（aiocqhttp/OneBot）等支持的平台生效，其他平台或关闭时逐条发送 |
| `result_image_size` | string | `standard` | `text` 模式每条结果配图的分辨率：`low` 超低清（直接用引擎缩略图，最省流量）/ `standard` 标清（原始大图缩放到最长边 640）/ `original` 原图（原始大图不缩放） |
| `ai_detect_mode` | string | `fallback` | AI 检测方式：`fallback` 优先 AI or Not、失败才用 Illuminarty；`both` 两个通道同时检测并分别展示（判断可能相反，可对比） |
| `enable_keyword_trigger` | bool | `true` | 关键词触发开关；关闭后仅 LLM 工具可用 |
| `proxies` | string | `""` | 代理地址，如 `http://127.0.0.1:7890`（国内访问必填） |
| `allow_third_party_image_host` | bool | `true` | 是否允许把本地图上传到第三方临时图床（Google/Yandex 本地图搜需要；关闭后这两引擎不可用本地图搜） |

### Cloudflare 过盾 `flaresolverr`（全局，所有引擎通用）

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enabled` | bool | `false` | 是否启用 FlareSolverr 过盾（需要同时填 `url`） |
| `url` | string | `""` | FlareSolverr 服务地址，如 `http://127.0.0.1:8191` |
| `timeout` | int | `90` | 过盾超时（秒），过盾通常要 10~60 秒 |
| `proxy` | string | `""` | FlareSolverr 访问目标站点时用的代理（可选）；Cookie 与出口 IP 绑定，需与搜索请求同出口 |

> 任何被 Cloudflare 人机验证（`Just a moment...`）拦截的引擎都可以复用它：引擎检测到挑战页后，调用这里配置的 FlareSolverr 取 `cf_clearance`，再重试一次；结果按目标站点缓存 10 分钟。目前 **Soutubot** 已接入，以后新增引擎直接调用同一客户端即可，不用重复配置。

### AI 生成检测 `aiornot`

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enabled` | bool | `false` | 启用后每次识图前先调用 [AI or Not](https://www.aiornot.com/) 检测图片是否为 AI 生成，结果与搜索结果一起展示（卡片徽章 / 文本一行）；同时解锁 `ai` 引擎 |
| `api_key` | string | `""` | AI or Not API Key，在 [控制台](https://www.aiornot.com/dashboard/api) 获取；留空则不启用 |
| `timeout` | int | `20` | 检测超时（秒）；超时自动跳过，不影响正常搜图 |

> 接口说明：插件调用 `POST https://api.aiornot.com/v2/image/sync`（`only=ai_generated`，避免 deepfake 等额外计费），只上传图片、不做反向搜索。启用后会把图片发送给 AI or Not，请自行评估隐私与费用。

### AI 生成检测备用 `illuminarty`

AI or Not 免费额度只有 20 张且**不按月重置**，额度用完后会自动切换到 Illuminarty 的免费检测（也可以在没配 AI or Not 时单独使用）。

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enabled` | bool | `false` | 是否启用 Illuminarty 通道（按 `ai_detect_mode` 作为备用或与 AI or Not 同时检测） |
| `timeout` | int | `60` | 检测超时（秒），该接口偶尔偏慢 |

> 两个通道的开关在各自配置块里：`aiornot.enabled` + `api_key`、`illuminarty.enabled`。`ai_detect_mode=both` 时会**同时**请求两个通道，卡片/文本分别展示两个结果（同一张图两者判断相反时可直接对比）；`fallback` 只在主通道失败时请求备用。任一通道失败都会在控制台输出 **WARNING**：`AI 检测通道不可用：<通道> 返回错误：<错误内容>`。
>
> 实现方式：直接请求 `app.illuminarty.ai` 主页上传图片时所用的接口 `POST /api/analysis/image`（multipart `file`，返回 `data.probability`），**不需要安装浏览器/Playwright**。注意这是该网站未公开的网页接口，可能随时变更或被限流；失败时插件会如实提示，不影响正常搜图。单图限制 3MB / png·jpg·webp，插件会自动压缩转换。

### 超时配置 `timeout_settings`

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `search_params_timeout` | int | `30` | 等待用户补充引擎/图片的超时（秒） |

### 关键词 `keyword`

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `trigger_keywords` | list | `["以图搜图", "image search"]` | 触发搜索的关键词列表 |
| `engine_keywords` | object | `a/s/e/n/g/y/ai` | 各引擎的自定义别名（animetrace=`a`、saucenao=`s`、ehentai=`e`、soutubot=`n`、google=`g`、yandex=`y`、ai=`ai`） |

### 引擎启用 `available_apis`

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `animetrace` / `ehentai` / `soutubot` / `google` / `yandex` / `saucenao` | bool | `true` | 各引擎启停开关 |
| `ai` | bool | `true` | 「AI 检测」引擎开关（只检测、不反搜；未配置 AI or Not API Key 时不显示） |

### 引擎默认参数 `default_params`

| 配置项 | 说明 |
|--------|------|
| `animetrace.model` | 识别模型，默认 `full_game_model_kira` |
| `animetrace.is_multi` / `ai_detect` | 多角色搜索 / AI 检测开关 |
| `ehentai.is_ex` / `covers` / `similar` / `exp` | ExHentai 开关、封面/相似/实验模式 |
| `ehentai.cookies` | **E-Hentai Cookie**（ExHentai 必需，获取方法见常见问题 Q5） |
| `ehentai.blur_image` / `blur_radius` | 结果图**模糊化**（过审）：卡片的缩略图与文本模式的配图都会高斯模糊；`blur_radius=0` 自动按尺寸计算（见 Q7） |
| `soutubot.factor` | 搜索模式：`1.2` 常规（推荐）/ `1.4` 严格（更精确但更容易没结果） |
| `soutubot.max_results` | 最多展示多少条 nhentai 图源结果（卡片最多 5 条） |
| `soutubot.cookies` / `user_agent` | Cloudflare 过盾用的 `cf_clearance` 等 Cookie 与对应 UA（见常见问题 Q6） |
| `soutubot.blur_image` / `blur_radius` | 结果图**模糊化**（过审）：含义同 `ehentai.blur_image` |
| `google.serpapi_key` / `zenserp_key` | SerpAPI（推荐）/ Zenserp（备用）Key |
| `google.hl` / `country` / `max_results` | 语言 / 地区 / 最大结果数 |
| `saucenao.api_key` / `minsim` / `numres` | API Key / 最低相似度 / 结果数 |
| `yandex.max_results` / `use_ru_fallback` | 结果数 / `.ru` 域名回退 |
| `yandex.cookies` | **Yandex Cookie**（反爬严格，不填可能 CAPTCHA 无结果，获取方法见 Q5） |

> **隐私披露：本地图会上传第三方图床**——使用**本地图片**搜 **Google / Yandex** 时，插件需把图片先上传到临时图床（按顺序尝试 `uguu.se` / `x0.at` / `pomf.lain.la` / `litterbox.catbox.moe` / `tmpfiles.org`）再以 URL 形式搜索，并回读校验该直链确实返回图片。**这意味着你的图片会被上传到公网临时图床**，保留时长由第三方决定。若需关闭，将 `allow_third_party_image_host` 设为 `false`（此时这两引擎不可用本地图搜，需改用图片 URL 或换用其他引擎）。
>
> **隐私披露：AI 检测会上传图片**——启用 `aiornot` 后，每次识图都会把图片发送给 AI or Not（`api.aiornot.com`）做 AI 生成检测，并按对方规则计费；启用 `illuminarty` 后，图片会发送给 Illuminarty（`app.illuminarty.ai`）——`both` 模式下两个通道都会收到图片，`fallback` 模式下仅在 AI or Not 失败时发送。关闭这两个开关即可完全停止上传。

### 快速配置模板

```json
{
  "output_mode": "card",
  "text_merge": true,
  "result_image_size": "standard",
  "enable_keyword_trigger": true,
  "proxies": "",
  "allow_third_party_image_host": true,
  "aiornot": {
    "enabled": false,
    "api_key": "",
    "timeout": 20
  },
  "illuminarty": {
    "enabled": false,
    "timeout": 60
  },
  "ai_detect_mode": "fallback",
  "flaresolverr": { "enabled": false, "url": "", "timeout": 90, "proxy": "" },
  "timeout_settings": {
    "search_params_timeout": 30
  },
  "keyword": {
    "trigger_keywords": ["以图搜图", "image search"],
    "engine_keywords": { "animetrace": "a", "ehentai": "e", "soutubot": "n", "google": "g", "yandex": "y", "saucenao": "s", "ai": "ai" }
  },
  "available_apis": { "animetrace": true, "ehentai": true, "soutubot": true, "google": true, "yandex": true, "saucenao": true, "ai": true },
  "default_params": {
    "animetrace": { "model": "full_game_model_kira", "is_multi": false, "ai_detect": false },
    "ehentai": { "is_ex": false, "covers": false, "similar": true, "exp": false, "cookies": "", "blur_image": false, "blur_radius": 0 },
    "soutubot": { "factor": "1.2", "max_results": 10, "cookies": "", "user_agent": "", "blur_image": false, "blur_radius": 0 },
    "google": { "serpapi_key": "", "zenserp_key": "", "hl": "zh-CN", "country": "HK", "max_results": 10 },
    "saucenao": { "api_key": "", "hide": 3, "numres": 5, "minsim": 30, "output_type": 2 },
    "yandex": { "max_results": 10, "use_ru_fallback": true, "cookies": "" }
  }
}
```

---

## LLM 可调用工具

插件注册 2 个 LLM 工具，机器人会自主判断何时调用：

```
用户: 这张图是什么角色？
🤖 → reverse_search(intent=找角色)
    🔍 [AnimeTrace] 找到 3 个结果
    角色: 芙兰朵露·斯卡蕾特 | 作品: 东方Project...

用户: 用 SauceNAO 查一下这张图的画师
🤖 → reverse_search_with_engine(engine=saucenao)
    🔍 [SauceNAO] 找到 5 个结果
    Pixiv: 画师 KuroNeko | 相似度 95.2%
```

### reverse_search
通用搜图工具，根据意图自动选择引擎。

| 参数 | 类型 | 说明 |
|------|------|------|
| `image_base64` | string? | 图片 base64 编码（与 URL 二选一） |
| `image_url` | string? | 图片 URL（与 base64 二选一） |
| `intent` | string? | 搜索意图（如「找角色」「找出处」「找相似图」），用于自动选引擎 |

### reverse_search_with_engine
指定引擎搜图，当用户明确要求使用某引擎时调用。

| 参数 | 类型 | 说明 |
|------|------|------|
| `image_base64` / `image_url` | string? | 图片来源（二选一） |
| `engine` | string | **必填**，引擎名：`animetrace` / `saucenao` / `ehentai` / `google` / `yandex` / `ai`（`ai` 只做 AI 生成检测） |

---

## 常见问题

### Q1：哪些引擎需要 API Key？

| 引擎 | 需要配置 |
|------|---------|
| AnimeTrace / Yandex / E-Hentai | 不需要，装好即用 |
| SauceNAO | 建议配置 `api_key`（[免费申请](https://saucenao.com/user.php)，每日 150 次） |
| Google | 需要 [SerpAPI Key](https://serpapi.com/)（推荐）或 Zenserp Key |

### Q2：E-Hentai 搜不了 / 想看 ExHentai 内容？

- E-Hentai 免配置可搜；**ExHentai** 需要账号 Cookie（`ipb_member_id`、`ipb_pass_hash`、`igneous`），填在 `default_params.ehentai.cookies`，并开启 `is_ex`

### Q3：国内服务器搜图很慢 / 搜不到？

在 `proxies` 配置代理（如 `http://127.0.0.1:7890`）。SauceNAO、Google、Yandex 等引擎对国内 IP 有风控，代理是必需的。

### Q4：搜索结果卡片图没生成？

插件优先走 AstrBot 云端文转图（t2i）渲染 HTML 卡片；若云端不可达/超时，**自动降级为内置 PIL 渲染**（仍会出图）。若两者都失败才回退纯文本。升级 AstrBot 到最新版可改善云端渲染稳定性。

### Q5：Yandex / E-Hentai 的 Cookie 怎么获取、填什么？

Cookie 就是浏览器登录网站后自动保存的一段身份凭证。要填的是**一整行 `name1=value1; name2=value2` 格式的字符串**。两种获取方法（任选其一）：

**方法一：控制台一键获取（最简单，先试这个）**
1. 浏览器访问目标网站并**登录**（E-Hentai 用 https://e-hentai.org；ExHentai 用 https://exhentai.org；Yandex 用 https://yandex.com/images）
2. 按 **F12** → 点顶部 **Console（控制台）** 标签页
3. 在下方输入框输入 `document.cookie` 然后**回车**
4. 控制台会直接输出一整行 Cookie 字符串 → **复制它**（形如 `ipb_member_id=123; ipb_pass_hash=abc; ...`）
5. 局限：拿不到 **HttpOnly** 的字段——**E-Hentai 够用**；**Yandex 部分关键字段是 HttpOnly，建议用方法二**

**方法二：Network 面板（完整版，Yandex 建议）**
1. 登录目标网站后按 **F12** → 点 **Network（网络）** 标签页
2. **注意：顶部那个过滤输入框不要填任何东西**（填了会过滤掉请求，列表变空！），保持空白
3. **刷新页面**（F5）→ 左侧出现请求列表 → **点击第一条请求**
4. 右侧打开 **Headers（标头）** → 往下找 **Request Headers（请求标头）** 区域
5. 找到 **`Cookie:`** 开头的那一行 → **复制整行**（`Cookie:` 等号后面的完整内容）

复制的内容形如（值以实际为准）：
```
yandexuid=1587138991653; ymex=1986384493.yrts.159; Session_id=3:163...:0
```
把整行粘贴到插件配置 `default_params.yandex.cookies` / `default_params.ehentai.cookies` 即可。

> **提示**：Yandex 反爬严格，不填 Cookie 可能触发验证码导致搜索无结果；E-Hentai 搜索 ExHentai 内容必须填 Cookie（含 `ipb_member_id`、`ipb_pass_hash`、`igneous` 三个关键字段）。从插件实际请求的域名（yandex.com）获取最稳妥。

### Q6：Soutubot 提示「Just a moment...」/ HTTP 403 怎么办？

这是 **Cloudflare 人机验证**：Soutubot 只对部分服务器 IP 弹出验证，浏览器能打开不代表服务器能直接请求。三种解决方式（任选其一）：

| 方式 | 做法 | 适用 |
|------|------|------|
| **换出口 IP** | 在 `proxies` 填代理（如 `http://127.0.0.1:7890`），让请求从没被拦的 IP 出去 | 最简单，多数情况有效 |
| **手动 Cookie** | 在能正常打开 https://soutubot.moe 的浏览器里通过验证 → F12 → Network → 刷新 → 点 `api/search` 请求 → 复制请求头 `Cookie:` 整行 → 填到 `default_params.soutubot.cookies`；同时把该浏览器 UA 填到 `default_params.soutubot.user_agent` | 服务器 IP 固定、想长期用 |
| **FlareSolverr 自动过盾** | 服务器上运行 [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)（`docker run -d --name flaresolverr -p 8191:8191 flaresolverr/flaresolverr:latest`），在**顶层 `flaresolverr`** 配置里开启并填 `http://127.0.0.1:8191` | 一劳永逸，**所有引擎通用**，过盾后 10 分钟内复用 Cookie |

> `cf_clearance` 与**出口 IP + User-Agent** 绑定：Cookie 方案要求插件请求的 IP/UA 与你复制 Cookie 的浏览器一致（所以才有 `user_agent` 配置）；FlareSolverr 方案由它在同一台服务器上取 Cookie，天然匹配。
>
> 旧版把 FlareSolverr 配在 `default_params.soutubot.flaresolverr`，现在仍会自动兼容（会打一条提示日志），建议迁移到顶层 `flaresolverr.url`。
>
> 若日志里出现 `[Soutubot] 触发 Cloudflare 人机验证` 后仍是 403，说明过盾失败（FlareSolverr 没启动/超时/也被拦），日志会给出具体原因。

### Q7：E-Hentai / Soutubot 的结果太露骨，怕被平台拦怎么办？

在 `default_params.ehentai`（或 `default_params.soutubot`）里把 `blur_image` 设为 `true` 即可：结果卡片里的缩略图、以及纯文本模式下每条结果附带的配图，都会先做高斯模糊再发送。

- `blur_radius` 默认 `0` = 自动：按图片短边的 1/8 计算，并限制在 12~40px，通常已经糊到看不清细节；
- 想更糊就填 `20`~`40`（数值越大越模糊），觉得太糊可填 `8`~`12`；
- **你发送的查询图不会被模糊**，也不影响搜索本身，只影响结果展示。

## 更新日志

> **[查看更新日志 →](CHANGELOG.md)**

## 支持与致谢

如果这个插件对你有帮助，欢迎点亮 Star，有问题和建议请提交 [Issue](https://github.com/OMSociety/astrbot_plugin_reverse_searcher/issues) 或 [Pull Request](https://github.com/OMSociety/astrbot_plugin_reverse_searcher/pulls)。

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) 开源聊天机器人框架
- [astrbot_plugin_img_rev_searcher_Ver2](https://github.com/Yanlyn/astrbot_plugin_img_rev_searcher_Ver2) 原始项目

## 许可证与作者

本项目采用 **AGPL-3.0** 开源协议。

[@OMSociety](https://github.com/OMSociety)
