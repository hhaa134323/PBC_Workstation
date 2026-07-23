# PBC 智能管理工作站

> IPO 审计 PBC（Provided by Client，客户提供资料）智能管理工作站
> 依据：AUD-SOP-PBC-01 V1.0 + 安永中国 AI 创新大赛

## 简介

按 SOP §5.5 实现 PBC 资料的接收、AI 智能分类、完整性检查、状态追踪及归档的全流程自动化。

**核心能力**：
- 客户文件夹监听 → AI 自动分类 → 按 SOP §5.5 标准归档（`归档根目录/一级分类/编号_描述_期间_版本.ext`）
- PBC 清单 Excel 自动回写状态 + 文件路径超链接
- 编号 + sha256 双锚定（改名不影响归属，内容变算新版本，删除标红）
- 三角色协作工作台（Staff / Senior / Manager）
- 缺料风险雷达（超 5 工作日触发 + AI 替代程序建议）

## 技术栈

- 后端：FastAPI + SQLite（WAL 模式）
- 前端：单文件 Alpine.js SPA（shadcn/ui 设计系统 + EY 品牌色）
- AI：百炼平台（GLM-5 / Qwen3-Plus / Qwen3-VL-Plus）
- 打包：PyInstaller onedir

## 部署

### 开发模式（推荐）

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 创建运行时目录 + 配置
mkdir -p projects data config
# 手动创建 config/api_config.json 填百炼 API Key：
# {
#   "bailian": {"api_key": "sk-xxx", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
#   "ai_models": {"model_classification": "glm-5", "model_vision": "qwen3-vl-plus", "model_reasoning": "glm-5"}
# }

# 3. 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. 浏览器打开 http://127.0.0.1:8000
```

### 打包 exe

```bash
# 用 v6 的 spec 复制改名（v6 能打开的 spec 是好的）
cp scripts/PBC-Agent-v6.spec scripts/PBC-Agent-v7-fixed.spec
# spec 里 hiddenimports 加 v7 新增：app.api.routes_config / routes_projects / routes_briefing
# spec 里 name 改 PBC-Agent-v7-fixed

cd scripts && python -m PyInstaller PBC-Agent-v7-fixed.spec --noconfirm \
  --distpath=D:/AgentProjects/IpoPBC/0 --workpath=D:/AgentProjects/IpoPBC/0/build
```

**打包教训**：不要用 `python -m PyInstaller app/main.py` CLI 直接打包（会重新生成 spec，路径处理不一致，exe 异常被 Windows 拦）。**永远复制上一版能用的 spec 改名 + 增量改 hidden-import**。

## 项目结构

```
.
├── app/
│   ├── api/           # FastAPI 路由
│   │   ├── routes_pbc.py        # PBC 清单 + 模板下载 + 导入校验
│   │   ├── routes_files.py     # 文件扫描 + 归档 + 路径透明化 6 个 API
│   │   ├── routes_config.py    # AI 配置（GET/PUT/models/test + 测试数据包）
│   │   ├── routes_projects.py  # 项目管理
│   │   ├── routes_risk.py      # 风险雷达
│   │   └── routes_briefing.py  # 一键汇报
│   ├── core/          # 业务逻辑
│   │   ├── archive.py          # §5.5 归档（编号_描述_期间_版本命名 + 整目录归档）
│   │   ├── ai_client.py        # 百炼封装 + classify_file + 期间检查
│   │   ├── db.py               # SQLite + 多项目 + file_archive 双锚
│   │   ├── excel_io.py        # PBC 清单 15 列读写 + 状态机
│   │   └── watcher.py          # watchdog 文件监听
│   ├── static/index.html      # 单文件前端（Alpine.js SPA）
│   └── main.py
├── scripts/
│   ├── build_exe.py            # 打包脚本（含 monkey-patch，参考用）
│   ├── generate_test_data.py   # 测试数据生成
│   └── regression_v7.py        # v7 回归测试（16 项）
├── 文档/
│   └── API契约_v7.md           # 给前端对接的接口契约
├── interaction_test_v2.py      # Playwright 交互测试（70 项）
├── requirements.txt
└── .gitignore
```

## v7 新增接口（10 个）

1. `GET /api/pbc/{pid}/download-template` — 15 列模板下载
2. `POST /api/pbc/{pid}/import` — 加必填校验
3. `GET /api/files/{pid}/paths` — 文件流向（客户文件夹 + 归档目录）
4. `GET /api/files/{pid}/archive-tree` — 归档目录树（按一级分类）
5. `POST /api/files/{pid}/config/archive-root` — 归档目录可配置
6. `POST /api/files/{pid}/open-folder-path` — 打开任意路径
7. `GET /api/files/{pid}/check-valid/{item_id}` — 文件失联检测（双锚）
8. `POST /api/files/{pid}/relocate/{item_id}` — 重新定位失联文件
9. `GET/PUT /api/config/ai` + `GET /models` + `POST /test` — AI 配置真后端
10. `GET /api/config/test-data-package` — 测试数据包下载

## 测试

```bash
# 回归测试（16 项）
python scripts/regression_v7.py

# 交互测试（70 项，需 Playwright + Chromium）
python interaction_test_v2.py
```

## 安全

- `config/api_config.json` 含 API Key，**已在 .gitignore 排除，不会上传**
- `projects/`、`data/`、`demo_kit/` 运行时数据也排除
- 所有打包产物（PBC-Agent-*/）排除

## 协作

```bash
# 拉取最新
git pull

# 改完后提交
git add .
git commit -m "改动说明"
git push
```
