# PBC 智能管理工作站 · SPEC（单一可信源）

> **本文件是项目唯一权威规格**。改任何代码/接口/功能前，先看本文件；
> 改完同步更新本文件的「当前状态」段。代码必须对齐 SPEC，不是反过来。
>
> 最后更新：2026-07-23 v7-fixed

---

## 1. 任务定义

**一句话**：让初级审计员从手工 PBC 资料分拣中解放出来。

**SOP 依据**：AUD-SOP-PBC-01 V1.0（`文档/IPO_PBC_SOP_Final.doc`）

**赛事**：安永中国 AI 创新大赛，截止 2026-07-31

---

## 2. SOP 条款对照（每条都引用 SOP + 实现位置）

| SOP 条款 | SOP 原文摘要 | 实现位置 | 当前状态 |
|---------|------------|---------|---------|
| §3 三角色 | Staff 接收/初检；Senior 复核；Manager 监督 | `app/static/index.html` 三角色统一界面 | ✅ 已实现 |
| §4.1 两个 Excel | 长表（基础资料）+ 宽表（穿行测试） | `app/core/excel_io.py` `_COLUMN_MAP` 15 列 | ✅ 已实现（长表） |
| §4.2 四状态 | 未提供/已提供审核中/已提供/不适用 | `app/core/excel_io.py` `is_valid_transition` + `state_changes` 表 | ✅ 已实现 |
| §5.1 接收预处理 | 区分基础资料 vs 穿行测试证据 | `app/core/ai_client.py` `classify_file` 返回 `doc_type` | ✅ 已实现 |
| §5.2 完整性检查 | 清单覆盖率 + 期间连续性 | `app/core/ai_client.py` `check_period_completeness` 读 `required_period` 列 | ✅ 已实现 |
| §5.3 状态回写 | Staff 在 Excel 更新状态 + 建立超链接 | `app/core/excel_io.py` `update_item_status` + `write_pbc_list`；前端文件路径列可点击调 `open-folder-path` | ✅ 已实现 |
| §5.4 Senior 复核 | 复核 4 维度 + 通过改「已提供」 | `app/static/index.html` 三角色工作台 + `update_item_status` | ✅ 已实现 |
| §5.5 文件归档 | 按一级分类建文件夹 + 编号_描述_期间_版本命名 | `app/core/archive.py` `archive_file` + `_build_archive_name` | ✅ 已实现（v7 重构） |
| §5.5 Tips 穿行测试 | 穿行测试资料放在一个文件夹单独提供 | `app/core/archive.py` `archive_directory` + `_process_one_directory` | ✅ 已实现 |
| §6 异常处理 | 关键 PBC 超 5 工作日 → Senior 汇报 + 替代程序 | `app/core/risk_signal.py` + `app/api/routes_risk.py` + 替代程序建议 | ✅ 已实现 |

---

## 3. v7 接口契约（10 个新增/改动接口）

> 详细字段见 `文档/API契约_v7.md`
> 交互式 API 文档：启动后访问 http://127.0.0.1:8000/docs（FastAPI Swagger UI）

| # | 接口 | SOP 对应 | 文件位置 |
|---|------|---------|---------|
| 1 | `GET /api/pbc/{pid}/download-template` | §4.1 | `routes_pbc.py` |
| 2 | `POST /api/pbc/{pid}/import`（加必填校验） | §4.1 | `routes_pbc.py` |
| 3 | `GET /api/files/{pid}/paths` | §5.5 | `routes_files.py` |
| 4 | `GET /api/files/{pid}/archive-tree` | §5.5 | `routes_files.py` |
| 5 | `POST /api/files/{pid}/config/archive-root` | §5.5 | `routes_files.py` |
| 6 | `POST /api/files/{pid}/open-folder-path` | §5.3 | `routes_files.py` |
| 7 | `GET /api/files/{pid}/check-valid/{item_id}` | §5.5 双锚 | `routes_files.py` |
| 8 | `POST /api/files/{pid}/relocate/{item_id}` | §5.5 双锚 | `routes_files.py` |
| 9 | `GET/PUT /api/config/ai` + `models` + `test` | §12 | `routes_config.py` |
| 10 | `GET /api/config/test-data-package` | 赛事要求 | `routes_config.py` |

### 3 个对齐口径（重要！）

1. **编号 + sha256 双锚**：file_archive 表 `item_id`（编号）+ `sha256`（内容指纹）双锚。
   改文件名不影响归属；换内容 = 新版本（`version` 递增）；删除 = 标红（`check-valid`）。

2. **「需求期间」列必填**：PBC 模板第 15 列 `* 需求期间`，红色星标。
   AI 期间检查读这列作为对照基准。归档命名加期间段。

3. **AI 配置真后端**：`GET/PUT /api/config/ai` + `POST /test` 真读写 `config/api_config.json`，
   不是前端占位。含 `confidence_threshold`（默认 0.7）+ `filename_match_enabled`（默认 True）。

---

## 4. 项目结构

```
app/
├── api/                  # FastAPI 路由
│   ├── routes_pbc.py        # PBC 清单 + 模板 + 导入校验
│   ├── routes_files.py     # 文件扫描 + 归档 + 路径透明化
│   ├── routes_config.py    # AI 配置 + 测试数据包
│   ├── routes_projects.py  # 项目管理
│   ├── routes_risk.py      # 风险雷达
│   └── routes_briefing.py  # 一键汇报
├── core/                 # 业务逻辑
│   ├── archive.py          # §5.5 归档（命名 + 整目录）
│   ├── ai_client.py        # 百炼封装 + classify_file + 期间检查
│   ├── db.py               # SQLite + 多项目 + file_archive 双锚
│   ├── excel_io.py        # PBC 清单 15 列读写 + 状态机
│   └── watcher.py          # watchdog 文件监听
├── static/index.html     # 单文件前端（Alpine.js SPA）
└── main.py
scripts/
├── build_exe.py            # 打包（含 monkey-patch，参考用）
├── generate_test_data.py   # 测试数据生成
├── regression_v7.py       # v7 回归测试（16 项）
└── PBC-Agent-v7-fixed.spec  # 打包 spec（v6 spec 复制改名）
文档/
├── IPO_PBC_SOP_Final.doc   # SOP 原文（只读）
├── API契约_v7.md           # 给前端对接的详细字段
└── IPO_PBC智能工作站_方案_飞书版.md  # 产品方案 v0.3
interaction_test_v2.py      # Playwright 交互测试（70 项）
```

---

## 5. 当前状态

- **后端**：v7 完成（10 个新接口 + §5.5 归档重构 + 双锚 + 整目录归档）
- **前端**：Opus 4.8 对接完成（`app/static/index.html` 2624 行）
- **打包**：`PBC-Agent-v7-fixed.exe`（56.7MB zip，用 v6 spec 复制改名打包）
- **测试**：回归 16/16 全通过；交互 59/70（11 个 FAIL 是 demo 数据问题不是 bug）
- **GitHub**：https://github.com/hhaa134323/IpoPBC（私有）
- **未完成**：审计员还没有用 v7 测试过；Demo 视频未拍

---

## 6. 协作纪律

1. 改任何代码前，先看本文件 §2 SOP 条款对照，确认改动跟 SOP 一致
2. 改完代码后，更新本文件 §5 当前状态 + 对应 §2 行的「当前状态」列
3. 接口变更必须同步 `文档/API契约_v7.md` + 本文件 §3
4. push 前 CI 自动跑 `regression_v7.py`，失败不许 merge
5. 打包永远用「复制上一版 spec 改名」流程，不要改 build_exe.py 的 monkey-patch
