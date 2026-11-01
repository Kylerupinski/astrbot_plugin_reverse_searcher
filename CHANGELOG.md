# 更新日志

> 本文件面向**使用者**，记录插件在**原版（1.1.2）之后**做了哪些改动、会带来什么变化。
> 原版及更早版本的记录保留在文末「历史版本（原版及以前）」。
> 更新日期 2026.11.01
> 当前版本：**1.2.0**

---

## 1.2.0 — Soutubot（nhentai 图源）+ 结果图模糊 + Cloudflare 过盾

### 新引擎：Soutubot（简称 `n`）

- 专门查 **nhentai** 图源：本子标题、作者、页数 / 语言 / 类型、标签、**直达该页的 nhentai 链接**，以及相似度。
- 和 E-Hentai 收录不同，两个都开着命中率更高；同一本命中多页只显示一条（保留最高相似度并合并命中页数）。
- 免 Key 免 Cookie 开箱可用；站点排队限流时会原样提示「当前搜索任务较多，请稍后重试」，不会伪装成「没找到」。
- 配置：`available_apis.soutubot`、`engine_keywords.soutubot`（默认 `n`）、`default_params.soutubot.factor`（`1.2` 常规 / `1.4` 严格）、`max_results`。

### 结果图模糊（过平台审核）

- E-Hentai / Soutubot 各有一个 **`blur_image`** 开关：开启后，卡片里的缩略图、文本模式每条结果的配图都会先做高斯模糊再发送。
- **`blur_radius`** 默认 `0` = 自动（按图片短边 1/8，限制在 12~40px，通常已足够糊）；想更糊填 `20`~`40`，想轻一点填 `8`~`12`。
- **你发送的查询图不会被模糊**，搜索本身也不受影响，只影响结果展示。两个引擎互相独立。

### Cloudflare 过盾（全局 FlareSolverr）

- 新增**顶层 `flaresolverr`** 配置：`enabled`、`url`（如 `http://127.0.0.1:8191`）、`timeout`、`proxy`（可选）。
- **配一次，所有引擎通用**：遇到 `Just a moment...` 挑战页会自动过盾取 `cf_clearance` 并重试一次，结果按站点缓存 10 分钟。目前 Soutubot 已接入，以后新增引擎直接复用。
- 也可以用 `proxies` 换出口 IP，或手动填 `default_params.soutubot.cookies` / `user_agent`（`cf_clearance` 与 IP、UA 绑定）。
- 旧版配在 `default_params.soutubot.flaresolverr` 的仍然兼容（控制台提示迁移），建议改到顶层。

### 出错时更好排查

- Soutubot 失败时控制台输出 **WARNING**，包含 HTTP 状态码、content-type、响应长度、请求 URL、页面标题和内容片段（前 500 字），能区分限流、Cloudflare 拦截和网站改版。
- 聊天里的报错也会带上状态码与页面标题；空响应单独提示「返回了空响应（可能被限流）」。
- 请求阶段记录本次的 factor、图片大小和响应概况，方便对照排查。

---

## 1.1.9 — 两个 AI 检测可以同时跑了，还能各自开关

有人发现同一张图，AI or Not 给 15%、Illuminarty 给 82%，结论完全相反。所以把两个通道改成**可独立开关 + 两种协作方式**：

- **开关分开**：`aiornot.enabled`（+ API Key）和 `illuminarty.enabled` 各自控制，想用哪个开哪个，也可以只开一个。
- **新增 `ai_detect_mode`**：
  - `fallback`（默认）：优先 AI or Not，额度用完 / 报错 / 超时才用 Illuminarty——省请求，行为和上个版本一致；
  - `both`：**两个通道同时检测**，卡片和文本里分别列出两个结果（各自的判定、概率、疑似生成器），判断相反时可以直接对比。
- **出错会在控制台提醒**：任一通道不可用时输出 WARNING 日志，例如
  `AI 检测通道不可用：AI or Not 返回错误：HTTP 402：{"error":"QUOTA_EXCEEDED"...}`，
  通道名和错误内容都在里面，方便排查是额度、Key 还是网络问题。
- `ai` 引擎的卡片会按通道分段展示（失败的那段显示红色错误块），普通搜图的结果卡片则会为每个成功的通道各显示一枚徽章。

**配置位置**：`ai_detect_mode` 在插件配置顶层；开启 `both` 前请确认两个通道都填好了（AI or Not 需要 Key）。

---

## 1.1.8 — AI 检测额度不够用？加上免费备用

AI or Not 的免费额度只有 **20 张**，而且**不会按月重置**，用完后 AI 检测就失效了。这个版本接入了免费的 **Illuminarty** 作为备用：

- **自动切换**：配置了 AI or Not 时先走它；额度用完 / Key 失效 / 超时等任何失败，都会自动改用 Illuminarty 再检测一次，并标注「AI or Not 不可用，已自动切换备用」。
- **可以单独用**：完全不填 AI or Not Key、只开启 Illuminarty，也能使用 AI 检测和 `ai` 引擎（结果会标明来源是 Illuminarty）。
- **不需要装浏览器**：直接调用 `app.illuminarty.ai` 主页上传图片时用的那个接口（`POST /api/analysis/image`），返回 `AI Probability`。所以**不用安装 Playwright / Chromium**，普通服务器也能跑。
- **自动适配限制**：该接口只收 png/jpg/webp 且单张 ≤3MB，插件会自动压缩转换。
- 识别准确率略低于 AI or Not（这也是把它当备用的原因）；卡片与文本都会显示「检测来源」，两个来源的结果不会混淆。

**配置**：在插件配置里找到 `illuminarty`，把 `enabled` 打开即可（默认关闭）。

**注意**：这是该网站未公开的网页接口（不是官方付费 API），可能随时变更或被限流；失败时会在结果里提示原因，不影响正常搜图。

---

## 1.1.7 — 识图前先判断「这张图是不是 AI 画的」

接入 [AI or Not](https://www.aiornot.com/) 的官方接口，新增两类能力：

**1）识图前的 AI 检测（可选）**

- 在配置里打开 `aiornot.enabled`，并填入从 [AI or Not 控制台](https://www.aiornot.com/dashboard/api) 拿到的 API Key。
- 打开后，**每次识图都会先检测一次**，结果和搜索结果一起展示：
  - 卡片模式：卡片顶部出现徽章，例如「🤖 AI or Not：AI 生成，AI 生成概率 92%（疑似 Midjourney）」；
  - 纯文本模式：汇总消息里多一行同样的说明。
- 检测只发一次请求，且只跑「AI 生成」这一项（不会额外跑 deepfake / NSFW 检测，避免多余计费）。
- 检测失败（Key 写错、超时、额度用完）**不会影响正常搜图**，只会在结果里提示失败原因。

**2）新增「AI 检测」引擎（只检测，不反搜）**

- 在原来 5 个引擎之外新增 `ai`：发送「以图搜图 ai + 图片」即可只判断这张图是不是 AI 生成，**不会做任何反向搜索**，更快也更省。
- 卡片模式返回一张专门的 AI 检测卡片（判定结论 + AI 生成概率进度条 + 疑似生成器 + 原图）；纯文本模式返回一条检测结果。
- 这个引擎需要配置 AI or Not API Key 才会出现；没配置时使用会提示「请先在配置中开启 AI or Not 并填写 API Key」。

**注意**

- 开启 AI 检测后，图片会被发送到 AI or Not 的服务器，并按其规则计费；不想用时把 `aiornot.enabled` 关掉即可。
- 检测结果是概率判断，仅供参考，不保证 100% 准确。

---

## 1.1.6 — 结果图片的清晰度可以自己选了

以前每条结果附带的图片清晰度是固定的，现在可以在配置里选择三档（`result_image_size`）：

| 档位 | 适合场景 | 实际效果 |
|------|----------|----------|
| **超低清**（`low`） | 流量紧张、只想看个大概 | 直接用平台缩略图，一张约 4 KB |
| **标清**（`standard`，默认） | 日常使用 | 取原图并缩放到 640 像素，一张约 20 KB |
| **原图**（`original`） | 想看清细节、保存原图 | 原图不缩放（超大图会做保护性缩放） |

- 引擎没有提供原图时会自动回退缩略图，不会出现“没有图片”。
- AnimeTrace 的角色裁剪图也会跟随这个设置：超低清更省流量，原图保持清晰。
- 该设置只影响「纯文本输出」模式；卡片模式本身是固定尺寸的图片，不受影响。

---

## 1.1.5 — 一次搜索只发一条「聊天记录」

纯文本模式下，结果不再连续刷屏，而是合并成**一条合并转发（聊天记录）**：

- 打开后，机器人会发送一条聊天记录，里面依次是「汇总 → 每条结果（图片 + 文字）」。
- 需要平台支持合并转发（QQ 等）；其他平台或不支持时会自动改成逐条发送，结果不会丢失。
- 配置项：`text_merge`（默认开启）。不想合并时关掉即可。

---

## 1.1.4 — 每条结果单独一条消息，并带上图片

纯文本模式从“一大段文字”升级为“一条结果一条消息”：

- 先发一条汇总（用了哪个引擎、找到几条、是否 AI 生成、失败原因）。
- 之后每条结果单独一条，内容是该结果的**图片 + 文字**。
- 图片优先用 AnimeTrace 的识别框从原图裁出角色区域；其他引擎用结果缩略图。
- 各引擎的专属信息都保留：E-Hentai 的标签（中文翻译）、页数、类型；SauceNAO 的相似度、作者、相关链接；Google 的“精确匹配/相似结果”；Yandex 的图片尺寸。

---

## 1.1.3 — 修复四个引擎搜不到结果，并新增纯文本输出

### 修复

- **Google / Yandex 搜不到结果**：这两个引擎在搜本地图片时，需要先把图片上传到一个临时图床，再让引擎去抓取。原版使用的图床已经失效（链接打开是网页而不是图片），所以搜索必然为空。现在会换用多个可用图床，并且上传后逐个验证“链接确实是图片”，不通过就自动换下一个。
- **E-Hentai 结果全空**：原版读取页面标题的方式与网站当前的页面结构对不上，导致标题、链接、页数全部读成空，最后只剩空行或“没有结果”。已修复，并兼容旧版页面结构；页数也不会再误显示成上传者名字。
- **E-Hentai 被限流或拒绝时不再“装死”**：搜索太频繁、IP 被限制、需要登录 Cookie 等情况，现在会直接告诉你原因，而不是显示 0 条结果。
- **Yandex 没结果时会说明原因**：遇到人机验证（CAPTCHA）、页面异常、图片无法访问等情况，会提示具体原因和解决办法。
- **Google 的错误会显示出来**：SerpApi 返回的错误（例如额度用完、图片抓取不到）不再被吞掉。
- **AnimeTrace 额度用完时会明确提示**：以前会报错或显示空白，现在会显示服务端返回的提示（例如“已达到本次使用上限”）。
- **AnimeTrace 的“识别模型”设置终于生效**：原版配置的模型其实一直没有被发给服务端，现已修正。
- **使用代理（如 Clash TUN 模式）时图片下载失败**：这类代理会把所有域名解析到一个特殊地址段，原版的安全检查把它误判成内网地址而拒绝，导致缩略图和图片全部下载失败。现已放行该情况（直接写内网 IP 的地址仍然会被拦截）。

### 新增

- **纯文本输出**：新增 `output_mode` 配置，可选「卡片（默认）」或「纯文本」。
  - 纯文本模式不会生成图片卡片，直接发文字，更省流量、也方便复制链接；
  - 文字优先使用引擎自带的格式（E-Hentai 的中文标签、AnimeTrace 的 AI 检测等）。
- **AnimeTrace 结果显示角色图**：以前结果行里图片位置是空白的，现在会按识别框从你发的原图里裁出对应角色，作为该条结果的配图。

---

## 升级后建议检查

1. **输出方式**：插件配置里的 `output_mode`，想用纯文本就选 `text`。
2. **合并发送**：`text_merge` 默认开启；如果群里的机器人不支持合并转发，会自动逐条发送。
3. **图片清晰度**：`result_image_size` 默认「标清」；流量敏感选「超低清」，想看清细节选「原图」。
4. **E-Hentai**：如果提示“IP 被限制/需要 Cookie”，在 `default_params.ehentai.cookies` 里填入浏览器里的 Cookie（登录后按 F12 → 控制台输入 `document.cookie` 复制）。
5. **Yandex**：如果提示人机验证，可在 `default_params.yandex.cookies` 填入 Cookie，或更换代理出口。
6. **Google**：需要在 `default_params.google.serpapi_key` 配置 SerpApi Key。

## 已知限制

- **合并转发**只在支持该功能的平台（QQ / OneBot 类）生效，其他平台自动逐条发送。
- **“原图”档位**受数据源限制：有些结果本身只提供很小的缩略图，此时“原图”也只能拿到那张小图。
- **E-Hentai** 对访问频率和 IP 有严格限制：搜索太快会提示稍后再试；部分网络环境（如机房 IP）可能始终被拒绝，需要有效的 Cookie 或更换网络。
- **Google / Yandex 的本地图搜**需要把图片上传到第三方临时图床（可在配置中关闭，关闭后这两个引擎只能搜图片链接）。

---

## 历史版本（原版及以前）

<details>
<summary>点击展开原版 1.1.2 及更早版本的记录</summary>

### [1.1.2] - 2026-09-25

#### 修复

- **`search()` 的参数前置校验放行 `image_base64`**：此前 LLM 走 base64 搜图必然报「必须提供 file 或 url 参数」，而工具参数表已对外宣传该参数。
- **Google Lens 解析不再因单条畸形数据整批失败**：`knowledge_graph.header_images` 缺失、为空或为 null，KG 条目不是对象，`visual_matches`/`exact_matches` 混入非对象条目，Zenserp 的 `organic`/`pages_with_matching_images` 混入非对象条目，以及响应顶层不是对象时，都改为就地跳过或降级，已解析的 `ai_overview` 与正常条目保留。

#### Fixed

- **The upfront parameter validation of `search()` now lets `image_base64` through**: previously an LLM doing a base64 image search always got "must provide a file or url parameter", even though the tool parameter table already advertised that parameter.
- **Google Lens parsing no longer fails a whole batch because of a single malformed entry**: a missing, empty, or null `knowledge_graph.header_images`, a KG entry that is not an object, non-object entries mixed into `visual_matches`/`exact_matches`, non-object entries mixed into Zenserp's `organic`/`pages_with_matching_images`, and a top-level response that is not an object are all now skipped in place or degraded, while the already-parsed `ai_overview` and valid entries are kept.

### [1.1.1] - 2026-09-13

#### 变更

- 默认触发关键词新增英文 `image search`（`trigger_keywords` 默认值现为 `["以图搜图", "image search"]`）。

### [1.1.0] - 2026-09-13

#### 新增

- **WebUI 四语本地化**：新增 `zh-CN` / `en-US` / `ru-RU` / `ja-JP` 四份 i18n 文件（`.astrbot-plugin/i18n/`），插件名、简介与全部 66 条配置项文案在四种界面语言下均正确显示；中文文案与配置 schema 保持逐字镜像。默认触发词「以图搜图」等必须保留的中文字面量在各语言中维持原文。
- README 新增多语言版本（English / Русский / 日本語），顶部提供语言导航，并修正与代码不符的功能描述。

### [1.0.5] - 2026-09-07

#### 变更

- **下载链路 SSRF 加固**：`download()` 首跳不再依赖调用方自查，逐跳校验补齐；`search_and_draw` 的 URL 入口补安全校验（与 `search()` 对齐）。
- DNS 结果缓存增加 512 条上限保底；E-Hentai 标签翻译表改为按路径缓存（不再每次显示结果重读磁盘）；SerpApi 请求不再发送空的 `q=` 参数。
- 移除 `get_img_urls` 中不可达的组件 repr 扫描段（标准组件链与 raw_message 兜底保留，行为不变）。

### [1.0.4] - 2026-09-06

#### 修复

- **修复引用回复取图**：旧实现依赖当前框架不存在的 `event.raw_event` 属性，"回复一张图 → 搜图"实际取不到图。现改为遍历标准组件链中的 `Reply` 组件、从其 `chain` 提取图片（aiocqhttp 适配器自动填充被引用消息内容）。
- 修复 LLM 搜图工具"从消息上下文提图"读取不存在字段导致永远返回空的问题，改读真实组件链（含引用回复）。
- 搜索失败卡片现在显示具体原因（含 api_key 脱敏），不再只有笼统的"搜索失败"。

#### 变更

- 结果缩略图由串行下载改为并发下载。
- 移除已无调用的死代码（引擎注册表候补字段/意图辅助方法、消息状态冗余分支等约 200 行），三个相同的等待处理器合并为一个（行为不变）。

### [1.0.3] - 2026-09-01

#### 安全

- **修复重定向型 SSRF 绕过（Network 客户端）**：`Network` 的 httpx 客户端此前 `follow_redirects=True`，只校验初始 URL、未校验重定向目标。现改为 `download()` 手动逐跳跟随并对每一跳重新校验（`is_safe_image_url`，最多 3 跳），公网 URL 302 到内网（`169.254.169.254` 等）会被拦截
- **修复 HTML 注入**：搜索引擎返回的 `title/url/author/error_msg` 是第三方内容，此前直接拼进 HTML 模板再交给云端 t2i。现于渲染前用 `html.escape` 逐字段转义（云端渲染器是否转义不受控），防止被当作 HTML/脚本渲染

#### 变更

- **新增 `allow_third_party_image_host` 开关**（默认 `true`）：允许把本地图上传到第三方临时图床（`tmpfiles.org` / `uguu.se` / `litterbox.catbox.moe` / `tmp.ninja`）。关闭后 Google/Yandex 本地图搜不可用，需改用图片 URL
- README 新增「隐私披露」：明确说明本地图搜 Google/Yandex 时图片会先上传到上述临时图床、保留时长由第三方决定、如何关闭

### [1.0.2] - 2026-09-01

#### 修复

- **修复 GoogleLens 引擎代理/超时配置失效 + HTTP client 泄漏**：GoogleLens 编排器及其子引擎（SerpApi / Zenserp）在构造时丢弃了共享的 Network 连接，导致代理与超时配置对 Google 引擎不生效，且每次搜索会新建 3 个不关闭的 httpx client。现已正确转发共享连接
- **修复测试无法收集**：`tests/conftest.py` 缺 `sys.path` 注入、`test_security.py` 路径写错，导致 `pytest` 报 `No module named 'ReverseSearcher'`。已补齐（52 个用例现已可运行）

#### 变更

- 移除死代码：`BaseSearchModel.search_and_print`（含控制台 print）、`_prepare_engine_params` 的 `ascii2d` 空分支及其测试
- 清理 `yandex_req.py` / `google_lens_parser.py` 中过时的 "HandOver / requests" 注释与内联 `import`，统一提升到模块顶部
- 新增 `ruff.toml` 统一代码规范（与 MaiBot 版一致的豁免策略）
- **DNS 解析不再阻塞事件循环**：`is_safe_image_url` 的域名解析加入进程级缓存（TTL 5 分钟），并在所有异步调用点用 `asyncio.to_thread` 挪出事件循环线程，消除 SSRF 校验时的同步 DNS 阻塞

### [1.0.1] - 2026-08-16

#### 安全

- **修复任意本地文件读取漏洞**：图片本地路径仅允许 AstrBot 数据目录内（如 `data/temp/`），拒绝读取任意本地文件（消息内容 `path /xxx` 写法与 LLM `image_url` 参数均受限）
- **修复 SSRF（服务端请求伪造）漏洞**：图片 URL 仅允许公网 http/https，拒绝内网 / 环回 / 链路本地 / 云元数据 / 保留地址，并做 DNS 解析二次校验（防 DNS rebinding）
- **修复重定向型 SSRF**：图片下载改为手动逐跳校验重定向，公网 URL 跳转到内网地址时拦截
- **新增安全校验模块** `ReverseSearcher/utils/security.py`，统一所有图片引用入口（消息图片、文本 URL、LLM 工具参数、引擎 url）的安全校验

#### 新增

- 新增 22 个安全测试用例：内网 IP 判定矩阵、DNS rebinding 防护、本地路径目录白名单、`file://` 协议拒绝等

#### 变更

- 内网图片地址、任意本地路径、`file://` 协议将被拒绝并提示"仅支持公网图片 URL 或消息内图片"
- 正常使用不受影响：消息直接发图（QQ 官方预下载到 `data/temp/`）、公网图床 URL 均正常

</details>
