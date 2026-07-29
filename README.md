# PBC 智能管理工作站

> 审计项目 PBC（Provided by Client，客户提供资料）智能管理工作站
> 依据：AUD-SOP-PBC-01 V1.0

## 简介

把 PBC 资料管理从手工台账变成自动流水线。客户照常往共享文件夹放文件，系统自动扫描匹配 PBC 清单项，给出归档建议，审计员确认后归档。缺料提前标红，归档命名按 SOP 规范，变更记录可追溯。

**匹配逻辑（四层逐级降级）**：
1. 文件名含 PBC 编号直接命中（如"历-1_股权架构图.pdf"→历-1）
2. 打分模型按文件夹名/文件名/内容/期间四字段加权打分，高分自动匹配，中分给建议
3. 低分项调 AI（百炼 LLM）兜底做语义匹配
4. 以上结果都进待确认队列，审计员确认/改分类/跳过

关掉 AI，前三层照样跑，大部分文件仍能自动匹配。

**其他能力**：
- 编号 + sha256 双锚定（改名不影响归属，内容变算新版本，删除标红）
- 整目录归档按资料名称合并（如 货-1_银行流水/2023年度/ + 2024年度/）
- 变更记录时间线（文件变更 + 操作日志）
- 缺料风险雷达（超期标红 + 影响分析）
- 多项目隔离

## 技术栈

- 后端：FastAPI + SQLite（WAL 模式）
- 前端：单文件 Alpine.js SPA（shadcn/ui 设计系统 + EY 品牌色）
- AI：阿里云百炼（Qwen3-Plus / GLM-5）
- 打包：PyInstaller onedir（双击即用，数据存本地）

## 部署

### 开发模式

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 配置 config/api_config.json
# {
#   "bailian": {"api_key": "sk-xxx", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
#   "ai_flags": {"confidence_threshold": 0.7, "filename_match_enabled": true, "auto_confirm_enabled": false, "hitl_mode": true}
# }

# 3. 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. 浏览器打开 http://127.0.0.1:8000
```

### 打包 exe

```bash
# 复制上一版能用的 spec 改名（不要用 CLI 直接打包）
cp scripts/PBC-Agent-v10.spec scripts/PBC-Agent-v11.spec
# spec 里 name 改 PBC-Agent-v11，hiddenimports 加新增模块

cd scripts && python -m PyInstaller PBC-Agent-v11.spec --noconfirm \
  --distpath=../dist_v11 --workpath=../build_v11

# PyInstaller COLLECT 阶段可能漏包，手动补齐：
# cp -r venv/Lib/site-packages/{uvicorn,fastapi,...} dist_v11/PBC-Agent-v11/_internal/
```

**打包教训**：
- spec 的 datas 用相对路径（`..\\config`），不要写死绝对路径指向暂存目录
- 打包前验证 venv 有全部依赖：`python -c "import uvicorn, fastapi, openpyxl, pdfplumber, watchdog, httpx"`
- 打包后验证产物包目录非空：`ls dist/PBC-Agent-v11/_internal/uvicorn/`
- 前端 CDN 依赖（Alpine.js）要有本地 fallback

## 项目结构

```
.
├── app/
│   ├── api/               # FastAPI 路由
│   │   ├── routes_pbc.py          # PBC 清单 + 模板 + 导入校验
│   │   ├── routes_files.py       # 文件扫描 + 归档 + HITL 确认 + 变更日志
│   │   ├── routes_config.py      # AI 配置 + 测试连接
│   │   ├── routes_projects.py    # 项目管理
│   │   ├── routes_risk.py        # 风险雷达
│   │   └── routes_briefing.py    # 一键汇报
│   ├── core/              # 业务逻辑
│   │   ├── archive.py            # 归档（SOP 命名 + 整目录 + 三级树）
│   │   ├── ai_client.py         # 百炼封装 + classify_file
│   │   ├── matcher.py           # 4 字段加权打分 + 三档决策
│   │   ├── db.py                # SQLite + 多项目 + 双锚
│   │   ├── excel_io.py          # PBC 清单读写 + 状态机
│   │   ├── manifest.py          # 文件指纹 + pending/processed 状态机
│   │   ├── briefing.py          # 简报引擎
│   │   └── watcher.py           # watchdog 文件监听
│   ├── static/
│   │   ├── index.html           # 单文件前端（Alpine.js SPA）
│   │   ├── pbc-enhance.js       # 运行时增强（顶栏 + 变更面板）
│   │   └── js/alpine.min.js     # Alpine.js 本地 fallback
│   └── main.py
├── scripts/
│   ├── PBC-Agent-v10.spec       # 打包 spec（相对路径 datas）
│   ├── test_accept_scan.py      # 验收测试（8 场景）
│   └── test_ui_v10.py           # Playwright UI 测试
├── config/
│   └── api_config.json          # 百炼配置 + AI 开关
├── 文档/
│   └── PBC工作站说明材料_v2_preview.html  # 作品说明
├── requirements.txt
└── SPEC.md                      # 单一可信源
```

## 测试

```bash
# 验收测试（8 场景：扫描→确认→重复→新增→删除→目录→匹配→去重）
bash scripts/run_acceptance.sh

# UI 测试（Playwright + 系统 Chrome）
python scripts/test_ui_v10.py
```

## 安全

- `config/api_config.json` 含 API Key，已在 .gitignore 排除
- `projects/`、`data/` 运行时数据排除
- 所有打包产物（dist_*/、PBC-Agent-*/）排除
