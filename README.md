# PBC 智能管理工作站

IPO 审计 PBC（Provided By Client）智能管理工作站 · 安永 AI 创新大赛参赛作品。

## 启动方式

- 开发期：双击 `scripts/start.bat`
- 或手动：`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- 启动后自动打开浏览器（http://127.0.0.1:8000）

## 目录结构

```
0/
├── app/                # FastAPI 源码
│   ├── main.py         # 入口
│   ├── config.py       # 配置加载
│   ├── api/            # 路由（pbc / files / risk）
│   ├── core/           # 业务逻辑（db / ai_client / excel_io / file_parser）
│   ├── static/         # 前端静态（HTML + Alpine.js CDN）
│   └── utils/         # path_utils / retry
├── config/            # api_config.json（百炼 Key）
├── data/              # 运行时 SQLite + logs + archives
├── mock_data/         # 锁定的模拟数据集
├── scripts/           # start.bat / build_exe.py
├── requirements.txt
└── README.md
```

## 模块进度

- [x] M1 项目骨架（FastAPI + SQLite + 静态占位）
- [ ] M2 Excel 读写层（PBC 清单）
- [ ] M3 AI 解析层（百炼 + PDF/Excel）
- [ ] M4 状态机 + 交付物校验
- [ ] M5 风险雷达可视化
- [ ] M6 审计底稿生成
- [ ] M7 打包发布（PyInstaller）

## 配置

- API Key：`config/api_config.json`（百炼 OpenAI 兼容模式）
- 数据库：`data/pbc_workstation.db`（SQLite，首次启动自动创建）
- 启动日志：`data/logs/startup.log`
