# PBC 工作站 v7 API 契约（给前端 Opus 4.8 对接用）

> 版本：v7  日期：2026-07-23  依据：AUD-SOP-PBC-01 V1.0
> 后端作者：GLM-5.2  前端对接：Opus 4.8

## 基础约定

- 基础 URL：`http://127.0.0.1:8000`
- 所有接口返回 JSON，`Content-Type: application/json`
- project_id 为 "demo" 时是示例项目，新项目用 slug
- 日期格式：ISO 8601（如 `2026-07-15`）
- 必填字段：Excel 模板用红色星标 `* ` 前缀标注

---

## 一、v7 新增/改动接口

### 1. PBC 清单模板（v7.2: 16 列表头）

**`GET /api/pbc/{project_id}/download-template`**

下载 PBC 导入模板 Excel。**16 列表头**（v7.2 重构前列顺序）。

返回：`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` 二进制流

模板列结构（v7.2）：
```
1  * 一级分类         category           必填，归档按此建一级文件夹
2  * 二级分类         item_id            必填，唯一编号（如 历-1），前缀对应一级分类
3    相关科目         subject            选填
4  * 资料名称         doc_name           必填，简短名称（如 股权架构图）
5  * 问题/需求描述     description        必填，详细需求说明
6  * 报告期间          required_period    必填，如 2023年度/2024年度/2025年度
7    格式             file_format        选填（PDF/Excel/扫描件）
8    优先级           priority           选填
9    提出时间         raised_at          选填
10 * 期望提供日期      expected_by        必填，超 5 工作日触发风险雷达
11   逾期天数         overdue_days       选填，自动算
12   资料提供情况      status_raw         选填，状态机自动管
13   备注             remark             选填
14 * 实体归属          entity             必填（公司级 vs 集团级）
15   置信度           confidence         选填，AI 自动回填
16   文件路径         file_path           选填，AI 归档后自动回填
```

**关键**：第 6 列「报告期间」是 AI 期间连续性检查的对照基准。归档路径两级：一级分类/二级分类_资料名称/文件。

---

### 1b. PBC 清单导出

**`GET /api/pbc/{project_id}/export`**

导出当前项目的 PBC 清单（含已回写的状态/文件路径/置信度）。直接返回项目的 01_PBC_List.xlsx 文件流。

返回：`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` 二进制流
文件名：`PBC_List_{项目名}_{日期}.xlsx`

### 2. PBC 导入（加必填校验）

**`POST /api/pbc/{project_id}/import`**

上传 Excel 替换该项目 PBC 清单。**v7 加必填字段校验**，缺字段返回 400 友好错误（不覆盖现有清单）。

请求：`multipart/form-data`，字段 `file`

成功响应：
```json
{
  "ok": true,
  "project_id": "demo",
  "imported_rows": 10,
  "sheet_name": "PBC清单",
  "message": "已导入 10 项 PBC 清单（必填校验通过）"
}
```

失败响应（缺必填列）：
```json
{
  "detail": "Excel 缺少必填列: 需求期间。请下载最新模板。"
}
```

失败响应（缺必填值）：
```json
{
  "detail": "必填校验失败（共 2 处）: 历-1 缺必填字段「需求期间」; 存-4 缺必填字段「期望提供日期」"
}
```

### 3. 文件流向 API（路径透明化）

**`GET /api/files/{project_id}/paths`**

返回客户文件夹路径 + 归档根目录 + 两边文件数。**前端"文件流向图"卡片用**。

响应：
```json
{
  "project_id": "demo",
  "client_folder": {
    "path": "D:/.../客户共享文件夹",
    "exists": true,
    "is_dir": true,
    "file_count": 10
  },
  "archive_root": {
    "path": "D:/.../archives",
    "exists": true,
    "is_dir": true,
    "category_count": 6,
    "file_count": 32
  },
  "flow_hint": "客户共享文件夹（未整理）→ AI 分类 → 归档目录（已整理，按一级分类）",
  "archive_naming_hint": "归档路径格式：归档根目录/一级分类/编号_描述_期间_版本.ext"
}
```

**前端展示**：左侧显示 client_folder（未整理），右侧显示 archive_root（已整理），中间箭头。

### 4. 归档目录树

**`GET /api/files/{project_id}/archive-tree`**

返回归档目录树（按一级分类分组）。**前端右侧"已归档树"用**。

响应：
```json
{
  "project_id": "demo",
  "archive_root": "D:/.../archives",
  "tree": [
    {
      "category": "历史沿革",
      "path": "D:/.../archives/历史沿革",
      "count": 3,
      "files": [
        {"name": "历-1_股权架构图_2024_v1.pdf", "path": "...", "size": 540, "mtime": 1784471717},
        ...
      ]
    },
    {"category": "财务报表", ...},
    ...
  ]
}
```

### 5. 归档目录可配置

**`POST /api/files/{project_id}/config/archive-root`**

配置归档根目录（用户可指定到桌面等可见位置）。

请求：
```json
{"archive_root": "D:/Desktop/PBC归档"}
```

成功响应：
```json
{"ok": true, "project_id": "demo", "archive_root": "D:/Desktop/PBC归档", "project": {...}}
```

失败响应：
```json
{"ok": false, "error": "folder_not_found", "path": "...", "suggestion": "归档目录必须存在且是文件夹。请先在文件管理器中创建该文件夹。"}
```

### 6. 打开任意路径（文件所在目录）

**`POST /api/files/{project_id}/open-folder-path`**

打开任意路径的资源管理器。**PBC list 文件路径列超链接用**。

请求：
```json
{"path": "D:/.../PBC归档/历史沿革/历-1_股权架构图_2024_v1.pdf"}
```

逻辑：path 是目录直接打开；path 是文件打开其父目录。

响应：`{"ok": true, "path": "D:/.../历史沿革"}`

### 7. 文件失联检测（v7 双锚机制）

**`GET /api/files/{project_id}/check-valid/{item_id}`**

检查某编号对应的归档文件是否仍存在。**PBC list 文件路径列失效时标红用**。

双锚机制：
- 编号锚定：item_id 不变，改名不影响归属
- sha256 双锚：换内容 = 新版本，删文件 = 标红

响应（文件存在）：
```json
{"valid": true, "archived_path": "...", "item_id": "历-1", "sha256": "..."}
```

响应（文件失联）：
```json
{"valid": false, "archived_path": "...", "reason": "file_missing", "item_id": "历-1", "sha256": "..."}
```

### 8. 重新定位失联文件

**`POST /api/files/{project_id}/relocate/{item_id}`**

文件失联后，用户指定新位置，后端按 sha256 重新绑定。

请求：
```json
{"new_path": "D:/.../新文件.pdf"}
```

响应：
```json
{
  "ok": true,
  "item_id": "历-1",
  "old_path": "...",
  "new_path": "...",
  "sha_changed": false,
  "old_sha": "...",
  "new_sha": "..."
}
```

### 9. AI 配置（真后端，非占位）

**`GET /api/config/ai`** — 获取当前 AI 配置（key 脱敏）

响应：
```json
{
  "ok": true,
  "config": {
    "api_key_masked": "sk-ec6***9aa5",
    "api_key_set": true,
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model_classification": "glm-5",
    "model_vision": "qwen3-vl-plus",
    "model_reasoning": "glm-5",
    "confidence_threshold": 0.7,
    "filename_match_enabled": true
  }
}
```

**`PUT /api/config/ai`** — 保存 AI 配置

请求：
```json
{
  "api_key": "sk-xxx",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "model_classification": "glm-5",
  "model_vision": "qwen3-vl-plus",
  "model_reasoning": "glm-5",
  "confidence_threshold": 0.7,
  "filename_match_enabled": true
}
```

注意：api_key 含 `***` 视为未改，保留原值。

- `confidence_threshold`：置信度阈值（0-1），低于此值标红需人工复核，默认 0.7
- `filename_match_enabled`：文件名直配开关，True=启用文件名优先匹配跳过 AI（默认 True）

响应：`{"ok": true, "changed": ["model_classification"], "saved_to": "...", "message": "..."}`

**`GET /api/config/ai/models`** — 推荐模型清单（前端下拉用）

响应：
```json
{
  "ok": true,
  "models": [
    {"id": "glm-5", "name": "GLM-5（智谱）", "use_case": "文件内容识别 + 分类", "note": "..."},
    {"id": "qwen-plus", "name": "Qwen3-Plus（通义千问）", "use_case": "...", "note": "..."},
    {"id": "qwen-max", "name": "Qwen3-Max（通义千问）", ...},
    {"id": "qwen3-vl-plus", "name": "Qwen3-VL-Plus（视觉）", ...},
    {"id": "deepseek-v4-pro", "name": "DeepSeek-V4 Pro", ...}
  ]
}
```

**`POST /api/config/ai/test`** — 测试 AI 连接（真发一条 chat 请求）

请求：
```json
{"api_key": "sk-xxx", "base_url": "...", "model": "glm-5"}
```

成功响应：
```json
{"ok": true, "status_code": 200, "model": "glm-5", "response_preview": "OK", "message": "连接成功，模型 glm-5 响应正常"}
```

失败响应：
```json
{"ok": false, "status_code": 401, "error": "Invalid API key", "hint": "HTTP 401，请检查 API Key 或 model id 是否正确"}
```

### 10. 测试数据包下载

**`GET /api/config/test-data-package`**

下载测试数据包（zip）。**审计员反馈 #8：拿来创建项目测试用**。

如果 `data/test_data_package` 不存在，自动调 `scripts/generate_test_data.py` 生成，然后打成 zip 给前端下载。

返回：`application/zip` 二进制流，文件名 `PBC_测试数据包.zip`

zip 内结构：
```
test_data_package/
├── 01_PBC_List_测试.xlsx        # 10 项 PBC 清单
├── 客户共享文件夹/               # 10 文件 + 1 穿行测试文件夹（3 文件）
└── README_测试数据说明.txt
```

用户用法：下载 zip 解压 → 创建项目 → 向导第 2 步上传清单 → 第 3 步客户文件夹指向解压目录 → 扫描看 AI 自动分类归档。

---

## 二、改动接口（v7 增强）

### `POST /api/files/{project_id}/scan-folder` — 加整目录归档

v7 增强：扫描时识别一级子目录作为整目录归档单元（穿行测试资料，SOP §5.5 Tips）。

响应新增字段：
```json
{
  "task_id": "...",
  "project_id": "demo",
  "status": "processing",
  "folder": "...",
  "files": [...],          // 散文件
  "directories": [          // v7 新增：一级子目录
    {"path": "穿行测试_销售收款控制", "abs_path": "...", "name": "...", "file_count": 3, "size": ...}
  ],
  "count": 13,
  "to_process": 10,          // 散文件数（已过滤掉子目录内的）
  "directories_count": 1     // 子目录数
}
```

### `archive_file`（后端内部，无 API） — 按 SOP §5.5 重构

归档路径从 `{archive_root}/{entity}/{item_id}_{文件名}` 改为：

```
{archive_root}/{一级分类}/{编号}_{描述}_{期间}_{版本}.ext
```

示例：
```
PBC归档/历史沿革/历-1_股权架构图_2024_v1.pdf
PBC归档/财务报表/财-1_三年一期合并资产负债表_2023年度_v1.xlsx
```

### `archive_directory`（后端内部） — 整目录归档

穿行测试文件夹整目录归档到：
```
{archive_root}/{一级分类}/{编号}_{文件夹名}/
```

file_archive 表记一条 `is_directory=1` 的索引。

---

## 三、3 个对齐口径（重要！）

### ① 编号 + sha256 双锚（不是只靠编号）

Opus 4.8 说"以编号为锚"——对，但要更稳：**file_archive 表的 item_id（编号）+ sha256（文件指纹）双锚**。

- 改文件名 → 不影响（编号不变）
- 换文件内容 → sha256 变 → 标记为"新版本"（用 `version` 字段递增）
- 文件被删 → sha256 找不到 → 标红「文件已移动或删除」（调 `check-valid` 接口）

### ② 「需求期间」列必须加到模板

Opus 4.8 漏了。审计员明确要求"三年一期要根据项目来定，可以在 PBC 清单加一列写需求期间"。

- **模板第 15 列「需求期间」**（必填，红色星标）
- AI 期间连续性检查读这列作为对照基准
- 归档命名加期间段（从文件内容提取，对照需求期间验证）

### ③ AI 配置不是纯前端占位

Opus 4.8 写"纯前端占位"——不对。真后端已实现：
- `GET/PUT /api/config/ai` 真读写 `config/api_config.json`
- `POST /api/config/ai/test` 真发一条 chat 请求验证连通

直接对接这三个接口，不要做纯占位。

---

## 四、测试数据包

`scripts/generate_test_data.py` 生成测试数据包到 `data/test_data_package/`：

```
data/test_data_package/
├── 01_PBC_List_测试.xlsx        # 10 项 PBC 清单（5 个一级分类、3 个实体）
├── 客户共享文件夹/
│   ├── 历-1_股权架构图.pdf      # 文件名带编号前缀，验证 filename-match 快路径
│   ├── 财-1_合并资产负债表.xlsx
│   ├── ... (共 10 个散文件)
│   └── 穿行测试_销售收款控制/    # v7 整目录归档测试
│       ├── B0206_系统截图.pdf
│       ├── B0207_纸质签字.pdf
│       └── B0208_银行回单.pdf
└── README_测试数据说明.txt
```

**用户用法**：下载这个包解压 → 创建项目 → 向导第 2 步上传清单 → 第 3 步客户文件夹指向解压目录 → 扫描看 AI 自动分类归档。

---

## 五、未改动接口（沿用 v6）

- `GET /api/projects/list` — 项目列表
- `POST /api/projects/create` — 创建项目
- `POST /api/projects/create-with-demo-data` — 创建项目 + 灌示例数据
- `GET /api/projects/{pid}` — 查单个项目
- `PUT /api/projects/{pid}` — 更新项目（含 archive_root 字段）
- `DELETE /api/projects/{pid}?soft=true` — 软删项目
- `GET /api/pbc/{pid}/list` — PBC 清单（v7 返回多 `required_period` 字段）
- `PUT /api/pbc/{pid}/{item_id}/status` — 状态更新
- `GET /api/files/{pid}/recent-tasks` — 任务列表
- `GET /api/files/{pid}/archive-detail/{item_id}` — 归档详情
- `GET /api/risk/dashboard` — 风险仪表盘
- `POST /api/open-folder/{pid}` — 打开客户共享文件夹（保留）
- `GET /api/pbc/{pid}/export` — 导出 PBC 清单（含已回写状态，v7.2 新增）

---

## 五b. 文件匹配打分模型（v7.4 新增）

### 设计原理

借鉴银行对账三档匹配 + Fellegi-Sunter 概率匹配模型（多字段加权）。

### 4 个字段加权打分

| 字段 | 比较 | 权重 | 说明 |
|------|------|------|------|
| F1 | 文件夹名 vs category（一级分类） | 0.25 | 形态2/4 的强信号 |
| F2 | 文件名 vs doc_name（资料名称） | 0.40 | 最可靠信号，N-gram Jaccard |
| F3 | 文件名+内容头200字 vs description | 0.20 | N-gram Jaccard，不依赖 jieba |
| F4 | 文件夹名/文件名 vs required_period | 0.15 | 年份交集比例 |

总分 = F1×0.25 + F2×0.40 + F3×0.20 + F4×0.15 (0.0-1.0)

### 三档决策

| 总分 | 决策 | 行为 |
|------|------|------|
| > 0.75 | auto | 自动匹配，直接归档，不调 LLM |
| 0.4-0.75 | suggest | 建议匹配，toast 推审计员确认 |
| < 0.4 | llm | LLM 兜底，调百炼 GLM-5 |

### 穿行测试前置检测

打分前先检测：文件夹名含"穿行/截图/签字/回单/控制" → 走整目录归档，不逐文件打分。

### 处理流程

```
文件到达
  → L1: filename-match（文件名含编号前缀？）→ 命中：直接归类
  → 穿行测试前置检测 → 命中：整目录归档
  → 打分（F1+F2+F3+F4 加权）
    → > 0.75：自动匹配
    → 0.4-0.75：建议匹配（toast 确认）
    → < 0.4：LLM 兜底
```

### 可解释性

每个文件处理结果包含 `score_breakdown`：
```json
{
  "score_breakdown": {
    "F1_folder_vs_category": 0.25,
    "F2_filename_vs_doc_name": 0.32,
    "F3_content_vs_description": 0.14,
    "F4_folder_vs_period": 0,
    "total": 0.71
  }
}
```

### 相关文件

- `app/core/matcher.py` — 打分模块主逻辑
- `app/api/routes_files.py` — `_process_one_file_sync()` 调用链
- `app/core/manifest.py` — 轻量指纹去重（size+mtime 快路径）

---

## 六、前端 Opus 4.8 需要做的事

对照收敛清单 7 条 + 3 个对齐口径：

1. **文件区视图**：调 `GET /paths` + `GET /archive-tree`，左客户文件夹右已归档树
2. **归档目录配置**：调 `POST /config/archive-root`，设置里加"归档根目录"输入框
3. **路径列超链接**：调 `POST /open-folder-path`，PBC list 文件路径列点击打开；调 `GET /check-valid/{item_id}` 失效标红 + 弹「重新定位」按钮调 `POST /relocate/{item_id}`
4. **导入模板按钮**：调 `GET /download-template`，导入区一个按钮（不做两栏）
5. **新增列**：网页主表加「文件名称」+「格式」（进列设置）；PBC list 加 `required_period` 字段展示
6. **AI 配置面板**：设置里加 tab，调 `GET/PUT /api/config/ai` + `POST /test` + `GET /models`，**真后端非占位**
7. **测试数据**：前端展示测试数据包路径 + 下载入口

**约束**：保持单文件 Alpine.js SPA，用 Edit 工具最小侵入替换（文件 >50KB 不要 Write 重写）。

---

## v7.6 新增接口（2026-07-24）

### 1. 改分类 `POST /api/files/{project_id}/reclassify/{item_id}`

Senior 复核发现 AI 分错时直接指定新 item_id，不让 AI 重跑。

**请求**：
```json
{
  "new_item_id": "财-1",        // Senior 指定的正确 item_id
  "changed_by": "manual",
  "reason": "这是利润表不是股权架构图"  // 可选
}
```

**响应**：
```json
{
  "ok": true,
  "project_id": "demo",
  "old_item_id": "历-1",
  "new_item_id": "财-1",
  "reclassified_count": 1,
  "results": [{"old_archived_path": "...", "new_archived_path": "...", "sha256": "...", "version": "v1"}],
  "errors": []
}
```

**流程**：删旧归档副本 → 删 archive 记录 → 用新 item_id 重新归档（archive_file）→ 改 PBC file_path → 状态推进审核中

**前端**：review tab 行操作列加「改分类」按钮 → 弹窗搜索下拉选新 item_id → 确认

### 2. 变更日志 `GET /api/files/{project_id}/change-log`

持久化操作记录（类似 git log），审计留痕，永久保留。

**参数**：
- `change_type`（可选）：added/archived/reclassified/approved/deleted/missing
- `limit`（可选，默认 100，最大 500）

**响应**：
```json
{
  "project_id": "demo",
  "count": 3,
  "logs": [
    {
      "id": 1,
      "project_id": "demo",
      "file_name": "历-1_股权架构图.pdf",
      "sha256": "abc123...",
      "change_type": "archived",
      "item_id": "历-1",
      "changed_by": "ai-auto",
      "changed_at": "2026-07-24T23:05:00",
      "detail": "归档到 历史沿革/历-1 v1"
    }
  ]
}
```

**changed_by 取值**：`watchdog`（文件监听）/ `ai-auto`（AI 扫描）/ `manual`（人工操作）

**5 处写入**：
| 操作 | change_type | changed_by |
|------|-------------|-----------|
| watchdog mark_pending | added/modified | watchdog |
| archive_file 成功 | archived | ai-auto |
| reclassify 接口 | reclassified | manual |
| update_item_status→已提供 | approved | manual |
| detect_missing_files | deleted | watchdog |

**前端**：替换或重做消息中心，调此接口显示变更历史（布局待定）

### 3. 编号矛盾信号（matcher.score_file 返回字段，非独立接口）

F2 打分时检测文件名含编号但描述不匹配。

**score_file 返回新增字段**：
```json
{
  "conflict_signal": {
    "type": "id_description_conflict",
    "detected_item_id": "历-1",      // 文件名里含的编号
    "matched_item_id": "财-2",       // 实际匹配到的
    "f2_score": 0.0,
    "hint": "文件名含编号'历-1'但描述跟 PBC 清单不符，系统按描述匹配到'财-2'。可能客户命名错误，建议人工确认。"
  }
}
```

`conflict_signal` 为 `null` 表示无矛盾。

**触发条件**：文件名含某 item_id + 该 item_id 的 F2 分 < 0.3 + 实际匹配到别的 item

**routes_files 传递**：conflict_signal → advisory_notes（level=high）+ result.conflict_signal

**前端**：advisory_notes 里 level=high 的项高亮显示，提示"编号矛盾"
