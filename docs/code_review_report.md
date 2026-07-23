# Code Review 报告

## 概要

- **Review 日期**：2026-07-21
- **Review 范围**：`app/` 目录下全部 Python 文件（13 个）+ `app/static/index.html` 前端
- **Review 依据**：安永 GC Information Security 通知《AI 全民编程时代，如何守住安全底线》+ 项目《思路.md》第二十章合规要求
- **代码总行数**：约 6,875 行（Python ~5,530 行 + HTML 1,345 行）
- **总体评估**：**31 项问题**（P0：6 项；P1：9 项；P2：16 项）

---

## P0 必修问题（安全 / 错误处理）

| # | 文件 | 行号 | 问题 | 建议修复 |
|---|---|---|---|---|
| P0-1 | config/api_config.json | 3 | **真实 API Key 明文写入仓库**：`sk-ec6089e9f57642288c07ac4e28069aa5` 直接硬编码在 `config/api_config.json`，且项目根没有 `.gitignore`。一旦推送到远端仓库（GitLab/GitHub/Gitee），密钥即对外暴露，可被百炼平台他人盗用产生费用。这是安永通知 20.3 第 2 条"数据红线"明确点名的风险。 | ① 立刻在百炼控制台吊销并重新生成 API Key；② 新 Key 不入库，改为从环境变量 `PBC_BAILIAN_API_KEY` 读取（`config.py` 已有 `os.environ.get` 模式但未用）；③ 在仓库根新增 `.gitignore`，至少包含 `config/api_config.json`、`data/`、`projects/`、`*.db`、`__pycache__/`；④ 对仓库历史做 secrets 扫描（git-secrets / truffleHog）确认未泄露 |
| P0-2 | app/utils/path_utils.py | 16-20 | **`safe_path` 未做路径穿越防护**：函数只是 `Path(p).resolve()`，**没有限制根目录**。用户传入 `../../etc/passwd` 或 `D:/Windows/System32/...` 时，`safe_path` 会原样解析为绝对路径，下游 `parse_file` / `archive_file` / `file_hash_sha256` 都会照单全收。在 `routes_files.scan-folder` 中 `folder` 参数（routes_files.py:289）直接走 `safe_path(folder)`，攻击者可扫描任意目录。 | `safe_path` 应增加"根目录白名单"参数，例如 `safe_path(p, allowed_roots=[PROJECT_ROOT, cfg.client_folder])`，若 resolve 后不在任一允许根下则抛 `ValueError`。同理 `routes_files.scan_folder_by_project` 不应允许任意指定 `folder`，应强制使用项目 `client_folder` |
| P0-3 | app/api/routes_files.py | 249-260 | **上传文件名未做路径穿越防护**：`safe_name = Path(name).name` 只取 basename，但 `name` 来自客户端 `UploadFile.filename`，若客户端构造恶意 `filename="../../something.xlsx"`，`Path(name).name` 行为依赖平台。且 `f"{uuid.uuid4().hex[:8]}_{safe_name}"` 仍把用户提供的字符串拼到文件名，未过滤 `..` / `/` / `\`。结合 P0-2，写入路径存在风险。 | 显式校验：`safe_name = re.sub(r"[^\w\u4e00-\u9fa5.\-]", "_", Path(name).name)`；并确保最终 `dest` 在 `upload_dir` 内（`dest.resolve().relative_to(upload_dir.resolve())` 不抛异常） |
| P0-4 | app/core/db.py | 141-146 | **SQLite 跨线程连接 `check_same_thread=False` + 无写锁**：`_get_conn()` 用 `threading.local` 存连接，但 `check_same_thread=False` 已经放开跨线程；多 watcher 线程 + asyncio.to_thread + uvicorn worker 并发写 `tasks` / `file_archive` / `ai_history` 时，SQLite 默认写锁粒度是整个数据库文件，会触发 `database is locked` 错误。当前所有写入都没有重试，一旦锁竞争立即 500。 | ① 启用 WAL 模式：`conn.execute("PRAGMA journal_mode=WAL")`；② 在 `get_conn()` 上下文中加全局写锁（`threading.Lock`）或用 `busy_timeout=5000`；③ 关键写入路径（`upsert_task` / `insert_archive`）加 1-2 次重试 |
| P0-5 | app/core/ai_client.py | 170-183 | **AI 调用失败也写入缓存，导致后续相同请求一直返回失败结果**：第 176 行注释"失败也缓存，避免反复打挂的接口"，但 LRU 缓存无 TTL，失败结果会持续 100 条 / 进程生命周期。如果 AI 临时超时，后续所有相同 prompt 都会被锁死在失败状态，无法自愈，违反思路 20.3 "AI 失败时优雅降级"。 | 仅缓存成功结果：`if result.get("ok"): _cache.put(cache_key, result)`。失败结果走 `knowledge_base` 兜底（已有），不进缓存 |
| P0-6 | app/main.py | 129-136 | **CORS 配置 allow_credentials=True 与 allow_origins=["http://127.0.0.1", "http://localhost"] 矛盾**：当 `allow_credentials=True` 时浏览器会拒绝通配符 origin，目前虽是显式列表看似安全，但 `allow_methods=["*"]` + `allow_headers=["*"]` 过于宽松，且 `http://localhost` 不含端口，浏览器实际发的是 `http://localhost:8000`，Origin 不匹配会被拒绝，导致前端 fetch 在某些场景失败。 | `allow_origins=["http://127.0.0.1:8000", "http://127.0.0.1:8001", ..., "http://localhost:8000", ..., "http://localhost:8005"]` 显式列出端口范围；或干脆 `allow_credentials=False`（前端不依赖 cookie） |

---

## P1 重要问题（业务逻辑）

| # | 文件 | 行号 | 问题 | 建议修复 |
|---|---|---|---|---|
| P1-1 | app/core/excel_io.py | 60-66 | **状态机允许 `已提供 → 不适用` 但不允许 `已提供 → 已提供，审核中`，与思路 6.2 不符**：思路 6.2 明确"审核中 → 已提供 / 未提供"以及"任何 → 不适用"，未定义 `已提供` 回退路径。但前端 `index.html:1005-1010` `statusOptions` 又允许 `已提供 → 已提供，审核中`（"复核通过"反向流转）。前端 UI 与后端校验不一致，用户点击会被 400 拒绝，体验断裂。 | 二选一：① 后端 `_TRANSITIONS` 增加 `STATUS_PROVIDED: {STATUS_REVIEWING, STATUS_NA}`（与前端一致，允许撤销复核）；② 前端删除 `已提供` 的回退选项。建议选①，更符合实际审计流程（Senior 误判可撤销） |
| P1-2 | app/core/excel_io.py | 290-326 | **`write_pbc_list` 用 `load_workbook` + `ws.save()`，条件格式 / 数据验证可能丢失**：openpyxl 在加载+保存时对部分 Excel 元素（图表、数据透视表、VBA 宏、某些条件格式规则）的保留不完整。mock_data 的 `01_PBC_List.xlsx` 如有数据验证下拉框（思路 6.1 "限制状态列只能输入这四个选项"），多次写入后可能丢失，导致 Excel 不再强制四状态约束。 | ① 测试：在 `01_PBC_List.xlsx` 加数据验证 → 跑 `write_pbc_list` → 检查验证是否还在；② 若丢失，改用 `openpyxl.worksheet.datavalidation.DataValidation` 在每次写入后重新附加；或改用 `xlwings`（保留更好但需 Excel） |
| P1-3 | app/api/routes_files.py | 580-591 | **OCR 视觉兜底未做敏感信息脱敏**：当 `needs_ocr=True` 时直接把扫描件图片 base64 发给 `qwen3-vl-plus`，扫描件常含印章 / 签字 / 银行账号 / 身份证号。安永通知 20.3 第 2 条"最小必要信息"红线明确点名"扫描件含印章/签字/账户号"。当前演示用 mock_data 合规，但生产用前必须加脱敏。思路 20.6 已列为待办，但代码层完全没占位。 | 在 `extract_text_with_vision` 入口加 `redact_pii(image_bytes)` 函数（占位也可），对图片做 OCR 后把账号 / 身份证号区域打码再发给 vision 模型；或加配置开关 `ai.vision_redact=true`，默认关，生产环境开 |
| P1-4 | app/api/routes_files.py | 533-731 | **`_process_one_file_sync` 200 行单函数，违反"函数不超过 100 行"代码质量规范**：该函数承担 hash 去重 / 解析 / OCR / 读 PBC / AI 分类 / 回填 history / 期间检查 / 归档 / Excel 回写 / 状态更新 / insert_archive 共 10 个职责，任意一步异常都会影响后续步骤。例如 AI 分类失败时 `item_id=None`，导致 Excel 不写、状态不更新，但 archive 仍执行（entity="未分类"），文件归档但 PBC 清单不更新，造成数据不一致。 | 拆分为 10 个子函数（`_step1_dedup` / `_step2_parse` / ...），每个独立 try/except，失败只跳过该步并继续。或至少把"AI 失败但文件仍归档"分支补上：归档时若 `item_id is None`，应在 Excel 备注"AI 未识别，待人工指派" |
| P1-5 | app/api/routes_files.py | 86-96 | **全局单例 `_ai_client` 无线程锁**：多 watcher 线程 + asyncio.to_thread 并发调用 `_get_ai_client()` 时，首次初始化可能 race condition，创建多个 client（虽无害但浪费）。更严重的是 `AIClient` 内部 `_LRUCache` 是线程安全的，但 `_cache` 是模块级单例，缓存 key 含 `messages` 全文 hash，若两个线程并发写同一 key 没问题但读到的可能是部分构造的 value。 | 加 `threading.Lock` 双重检查：`with _ai_client_lock: if _ai_client is None: _ai_client = AIClient()` |
| P1-6 | app/core/watcher.py | 165-181 | **启动时扫描 `rglob("*")` 一次性派发 N 个后台线程，无并发限制**：mock_data 有 24 个文件，会瞬间派发 24 个线程并发调 AI（每个走 `httpx.Client`），可能触发百炼 QPS 限制或本地资源耗尽。`db.py` 注释里也提到"24 个并发会拖垮服务器"（db.py:409），但只是避免了启动时自动复制 mock 文件夹，没避免 watcher 启动扫描的并发。 | 用 `concurrent.futures.ThreadPoolExecutor(max_workers=3)` 限制并发；或用队列 + 单工作线程串行处理 |
| P1-7 | app/static/index.html | 342 | **Toast 用 `x-html="t.text"` 直接渲染用户内容，存在 XSS 风险**：`pushToast` 调用处多处把后端返回的 `n`（advisory_note message）直接当 HTML 注入（index.html:1176 `this.pushToast('mid', 'AI 提示', this.esc(n))`），这一处做了 esc 没问题；但 `scan.liveText`（index.html:616 `x-html="scan.liveText"`）拼了 `<b>` 标签，且 `liveText` 来自 `doing.name`（文件名），文件名未做 escape，恶意文件名 `<script>alert(1)</script>.pdf` 会被注入执行。 | 所有 `x-html` 改为 `x-text`，或对所有动态拼接的内容先调 `this.esc()`。`scan.liveText` 改为：`'正在'+stepMap[step]+'：<b>'+this.esc(cur)+'</b>'` 已经 escape 了 cur，但 stepMap 是常量不用 escape，这里实际安全；真正风险在 `_openInfoModal`（index.html:1283）`el.innerHTML = ...` 拼了未 escape 的 `title` / `sub`，应改为 `textContent` 或全 escape |
| P1-8 | app/static/index.html | 1283-1288 | **`_openInfoModal` 用 `innerHTML` 拼接用户输入**：`viewDetail` 把 `it.item_id` / `it.entity` / `it.category` 等 PBC 字段直接拼进 `innerHTML`，虽然这些字段来自 Excel 而非用户直接输入，但 PBC 清单可由审计员编辑，恶意审计员可在 `entity` 字段写 `<img src=x onerror=alert(1)>`，被前端渲染执行。 | 把 `kv(k, v)` 内的 `v` 改为 `this.esc(v)`，title/sub 也走 `textContent` |
| P1-9 | app/api/routes_risk.py | 369-373 | **`_resolve_cache` LRU 淘汰策略错误**：`if len(_resolve_cache) > 100: for k in list(_resolve_cache.keys())[:10]: _resolve_cache.pop(k, None)` —— `list(dict.keys())[:10]` 取的是**最早插入的 10 个 key**，但 dict 在 Python 3.7+ 保序，这相当于 FIFO 而非 LRU。淘汰的可能是刚被访问的热点项。 | 用 `collections.OrderedDict` + `move_to_end`，或直接复用 `ai_client._LRUCache` 类 |

---

## P2 建议改进（性能 / 质量）

| # | 文件 | 行号 | 问题 | 建议修复 |
|---|---|---|---|---|
| P2-1 | app/core/ai_client.py | 99-183 | **`chat()` 同步阻塞调用阻塞 event loop**：`@retry` 是同步装饰器，`httpx.Client` 也是同步，但 `routes_files._process_one_file` 已用 `asyncio.to_thread` 包装，所以实际不阻塞主 loop。但 `routes_risk._resolve_impl` 直接 `await`-free 调用 `client.analyze_impact(item)`，是同步阻塞，会卡住 uvicorn worker。 | `routes_risk` 的 `_resolve_impl` 把 `client.analyze_impact(item)` 包成 `await asyncio.to_thread(client.analyze_impact, item)`；或把 `AIClient.chat` 改成 `async def` 用 `httpx.AsyncClient` |
| P2-2 | app/api/routes_files.py | 482 | **`_process_paths` 注释说"顺序避免 SQLite 锁竞争"但实际是 for 循环 await，单任务串行**：多个文件依次处理，AI 调用每次 30s 超时，20 个文件最坏 10 分钟。前端轮询 800ms 一次，体验差。 | 改为 `asyncio.gather` 并发处理（限制并发 3-5），SQLite 写入仍串行（用 `asyncio.Lock`） |
| P2-3 | app/core/excel_io.py | 242-266 | **`read_pbc_list` 每次都重新打开 Excel 文件**：`routes_pbc.list_items` / `routes_risk.dashboard` / `routes_risk.resolve` / `routes_files._process_one_file_sync` 每处理一个文件就 read 一次 PBC 清单，N 个文件 = N+1 次磁盘 IO。mock_data 24 个文件 = 25 次读 Excel。 | 在 `_process_paths` 入口读一次 `pbc_items` 缓存进局部变量，传给每个 `_process_one_file_sync`；或模块级缓存 + 文件 mtime 失效 |
| P2-4 | app/api/routes_files.py | 117-131 | **`_set_task` 每次 upsert 都 SELECT 再 INSERT OR REPLACE**：`upsert_task` 内部先查再插，N 个文件 N*2 次 SQL。 | 改为纯 `INSERT OR REPLACE` 不查 existing，或用 `INSERT ... ON CONFLICT DO UPDATE` |
| P2-5 | app/static/index.html | 1157-1204 | **前端轮询固定 800ms，无指数退避**：扫描任务跑 10 分钟 = 750 次轮询，每次都打 `/api/files/{pid}/task/{tid}`，浪费带宽。 | `pollTask` 用指数退避：首次 600ms → 1200 → 2000 → 5000ms 封顶；任务 status=done 立即停 |
| P2-6 | app/static/index.html | 791-799 | **`loadProjects` 为每个项目并发请求 dashboard，N 个项目 = N 次 AI 调用**：dashboard 接口虽不直接调 AI，但每个项目读一次 Excel + 算所有 item 的 overdue。10 个项目 = 10 次读 Excel，慢。 | 加 `?summary=true` 简化接口只返回进度数；或后端做项目级缓存 5 分钟 |
| P2-7 | app/main.py | 56-118 | **`lifespan` 函数 60 行，承担 5 个启动步骤**：DB 初始化 / 默认项目 / API Key 校验 / watcher 启动 / 日志，混在一起。任何一个失败影响后续。 | 拆成 5 个独立函数 `_init_db()` / `_init_default_project()` / `_validate_api_key()` / `_start_watcher()` / `_write_log()`，lifespan 只编排 |
| P2-8 | app/core/db.py | 165-190 | **`slugify` 依赖 `pypinyin` 但未声明依赖**：`requirements.txt` 没列 pypinyin，用户装环境时不会装，中文项目名 slug 会 fallback 到原字符（含中文），导致 `projects/{中文slug}/` 目录名含中文，Windows 路径在某些场景（如 PyInstaller 打包后）出问题。 | `requirements.txt` 加 `pypinyin`；或改用 `unicodedata.normalize` + 手写拼音映射 |
| P2-9 | app/api/routes_pbc.py / routes_files.py / routes_risk.py | 多处 | **`_DEFAULT_PROJECT = "demo"` 在三个文件各自定义，违反 DRY**：每个 routes 文件都硬编码 `"demo"`，如果默认项目改名要改三处。 | 提取到 `app/config.py` 的 `DEFAULT_PROJECT_ID = "demo"` 常量 |
| P2-10 | app/core/ai_client.py | 188-263 | **`classify_file` 的 `advisory_notes` 生成规则只有英文 trigger 字段，message 是中文，前端显示混搭**：`{"level": "high", "trigger": "confidence_low", "message": "这份文件..."}`，level/trigger 英文，message 中文。前端 toast 显示时 level 映射到中文（index.html:338 `{high:'高',mid:'中',low:'低'}`），但 trigger 字段未映射，调试日志可读性差。 | 统一为中文：`"level": "高"` / `"trigger": "置信度偏低"`；或全英文 message |
| P2-11 | app/api/routes_files.py | 715-729 | **`insert_archive` 在 `archive_file` 内部已写过一次，外部又显式写一次，重复**：注释说"保证记录存在"，但 `archive_file` 已经 `INSERT OR IGNORE`，重复调用只是产生第二条记录（不同 item_id 视角）。若同 item_id 同 sha256，会产生重复行。 | 删除外层 `insert_archive` 调用，或加 `UNIQUE(item_id, sha256)` 约束 |
| P2-12 | app/core/knowledge_base.py | 43-366 | **知识库 `_KB` 字典 18 类只覆盖 10 类**：思路 16.2 提到 18 类一级分类，但 KB 只覆盖 10 类关键类。剩余 8 类（业务及财务概览 / 成本 / 营业外收支 / 政府补助 / 费用 / 短期借款 / 期后 / 其他）走 `_GENERIC_FALLBACK`，AI 失败时降级质量打折。 | 补齐 8 类知识库条目，至少每类 2 条替代程序 |
| P2-13 | app/utils/retry.py | 19-47 | **`retry` 装饰器 `timeout` 参数是"信号化参数"但实际未实现**：注释说"由被装饰函数自身超时机制实现"，但 `httpx.Client(timeout=self.timeout)` 已在 `AIClient` 内部处理，`retry` 的 `timeout` 参数实际未用，容易误导。 | 删除 `timeout` 参数，或改成 `retry(times=3, delay=1.0)` 简化 |
| P2-14 | app/static/index.html | 691-714 | **`API` 对象无统一错误处理**：`get/post/put` 各自 `if(!r.ok) throw new Error(...)`，错误信息只有状态码，无 response body。后端 400 / 500 时返回的 `detail` 字段丢失。 | `const err = await r.json().catch(()=>({})); throw new Error(err.detail || r.status)` |
| P2-15 | app/static/index.html | 7-11 | **CDN 依赖无 fallback**：`cdn.tailwindcss.com` 和 `cdn.jsdelivr.net/npm/alpinejs` 任一不可用，整个前端白屏。安永内网可能屏蔽 jsdelivr。 | 加本地 fallback：`<script>window.tailwind || document.write('<script src="/static/tailwind.min.js"><\/script>')</script>`；把 tailwind / alpine 预下载到 `app/static/vendor/` |
| P2-16 | app/static/index.html | 772, 806, 851 | **localStorage 存了 `pbc_onboarded` / `pbc_last_project`，无敏感信息但无过期**：用户切换电脑后旧 `pbc_last_project` 指向已删除项目，init 时 `find` 找不到，fallback 到 `projects[0]`，无提示。 | `localStorage.setItem('pbc_last_project', pid)` 加时间戳，超过 30 天清空 |

---

## 安全合规对照（安永通知要求）

| 通知要求 | 产品实现 | 评估 |
|---|---|---|
| **1. 警惕"黑盒代码"**：AI 生成代码不能直接部署到生产环境或客户系统，必须人工 Code Review + 隔离测试 | M1-M6 全部子 agent 生成，本报告为首次正式 Code Review | ⚠️ **本次 Review 即为满足此要求**。Review 发现 6 项 P0 + 9 项 P1，**未通过发布门槛**，需修复后复审 |
| **2. 严守"数据红线"**：只用安永授权 AI 工具；仅向 AI 提供完成任务所需的最小必要信息 | 思路 12 AI 工具可选配置（可切换授权工具）；mock_data 全虚构；但 OCR 视觉兜底未做脱敏（P1-3）；文件文本截断到 3000 字 | ✅ 演示用合规；⚠️ 生产用前必须加脱敏模块（P1-3） |
| **3. 建立"人机协作"新规范**：人是最终防线；发现 AI 异常立即停止并上报 | 思路 10.1 "AI 不替代人判断"；前端所有 AI 输出都有"AI 生成/知识库兜底"标签 + "采纳"按钮（人工确认）；状态机校验拒绝非法流转 | ✅ 设计层面合规 |
| **API Key 本地保存**（思路 12.3） | `config/api_config.json` 本地保存 | ⚠️ 但未加 `.gitignore`，存在误推送泄露风险（P0-1） |
| **不上传真实客户数据**（思路 9 + 16.2） | 双击即用本地应用；mock_data 全虚构 ABC 集团 | ✅ 演示用合规 |
| **AI 工具可选配置**（思路 12） | `config.py` 支持切换 base_url / api_key / 模型 | ✅ 合规 |
| **mock_data 全是虚构**（思路 16.2） | `_real_items.json` + 客户共享文件夹全是 ABC 集团/ABC科技/ABC制造/ABC商贸 | ✅ 已抽样核验，无真实客户数据 |
| **Code Review 完成后做正式 Review**（思路 20.6） | 本报告即为正式 Review | ✅ 本次完成 |

---

## 总体评价

| 维度 | 评分 | 说明 |
|---|---|---|
| **安全性** | **5/10** | P0-1 API Key 明文入库 + 无 .gitignore 是严重问题；P0-2 路径穿越防护不足；P0-3 上传文件名未严格过滤；CORS 配置有瑕疵。设计层面（双击即用、本地运行、mock_data 虚构）合规，但工程实现层面有漏洞 |
| **错误处理** | **6/10** | 主要路径有 try/except，AI 失败有 knowledge_base 兜底；但 P0-4 SQLite 锁竞争未处理、P0-5 AI 失败结果被缓存导致无法自愈、P1-4 单函数 200 行任意一步异常影响后续 |
| **业务逻辑** | **7/10** | 状态机基本符合思路 6.1，但 P1-1 前后端流转定义不一致；P1-2 条件格式可能丢失；多项目隔离设计正确（project_id 全链路传递）；SHA-256 去重按 project_id 隔离正确 |
| **性能** | **6/10** | AI 调用有 LRU 缓存（100 条）；但有失败也缓存的反模式（P0-5）；Excel 反复读无缓存（P2-3）；前端轮询无指数退避（P2-5）；watcher 启动扫描无并发限制（P1-6） |
| **代码质量** | **6/10** | 模块拆分清晰（config/core/api/utils 分层）；命名规范；但 `_process_one_file_sync` 200 行过长（P1-4）；`_DEFAULT_PROJECT` 三处重复（P2-9）；知识库只覆盖 10/18 类（P2-12） |
| **前端安全** | **5/10** | 有 `esc()` 函数处理 XSS，但 `x-html` 多处直接渲染（P1-7）；`_openInfoModal` 用 innerHTML 拼接（P1-8）；CDN 无 fallback（P2-15）；localStorage 无敏感信息但无过期（P2-16） |
| **综合** | **5.8/10** | **未达发布门槛**（需 ≥7/10）。设计思路合规、架构清晰，但工程实现有 6 项 P0 必修问题。修复 P0 后可达 7.5/10，可发布审计员测试用 |

---

## 建议下一步

1. **【立即】修复 P0-1**：吊销并重新生成百炼 API Key，加 `.gitignore`，改从环境变量读取。这是安永通知 20.3 第 2 条"数据红线"直接点名风险，必须先修。
2. **【发布前】修复 P0-2 / P0-3 / P0-4 / P0-5 / P0-6**：路径穿越防护、上传文件名过滤、SQLite WAL+锁、AI 缓存只缓存成功、CORS 端口显式化。这 5 项修完才能发布给审计员测试。
3. **【发布前】修复 P1-1 / P1-7 / P1-8**：前后端状态机对齐、前端 XSS 全 escape。这两类是审计员实操时直接踩坑的点。
4. **【测试阶段】修复 P1-2**：在 `01_PBC_List.xlsx` 加数据验证 → 跑 `write_pbc_list` → 验证条件格式 / 数据验证是否保留。若丢失，改用 `xlwings` 或每次重新附加 `DataValidation`。
5. **【生产前】修复 P1-3**：加文件内容脱敏模块（账户号 / 印章 / 签字打码后再发 vision 模型）。这是生产部署的硬门槛。
6. **【迭代优化】修复 P2 项**：P2-1 async 改造、P2-3 Excel 缓存、P2-5 轮询指数退避、P2-12 补齐知识库 8 类、P2-15 CDN 本地 fallback。这些不阻塞发布，但影响体验。
7. **【复审】**：P0 修复完成后，需由另一位具备资质的审计员 / 开发同事做一次复审（仅看 P0 修复 diff），确认无回归后再发布测试。

---

## 是否可以发布（审计员测试用）

**结论：暂不可发布。**

需先修复以下 6 项 P0 问题：

1. API Key 明文入库 + 无 .gitignore（P0-1）
2. 路径穿越防护缺失（P0-2）
3. 上传文件名未过滤（P0-3）
4. SQLite 并发锁竞争（P0-4）
5. AI 失败结果被缓存导致无法自愈（P0-5）
6. CORS 配置与端口不匹配（P0-6）

修复 P0 后，建议再修复 P1-1（状态机前后端不一致）+ P1-7/P1-8（XSS），即可发布给审计员做内部测试。

**当前状态仅适合**：开发自测 + Demo 视频录制（用 mock_data，不接触真实数据）。

---

*报告由 CodeBuddy Code 生成，Review 依据为安永 GC Information Security 通知及项目《思路.md》第二十章。本报告只读不改，未修改任何代码。*
