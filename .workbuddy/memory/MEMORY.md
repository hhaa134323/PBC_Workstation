# PBC 智能管理工作站 — 项目记忆

## 设计规范
- 前端必须符合 shadcn/ui 设计模式（card + title + description muted text + button variants）
- 零 emoji：全部用 SVG Lucide icon（24x24 stroke 风格）
- 颜色系统：hsl(var(--background)) / hsl(var(--border)) / hsl(var(--muted-foreground))
- CSS 变量使用 hsl() 包装，不用硬编码颜色值

## 修改原则
- 大文件（>50KB HTML）用 Edit 工具最小侵入替换，不用 Write 重写
- 每次修改后立即在 127.0.0.1:8000 验证
- Bash heredoc 不能写含单引号的长字符串
- 打包时 PyInstaller 不能覆盖已有目录 → 每次换名（v2/v3/v4）

## 打包教训（2026-07-23 v7 踩坑复盘，重要！）

**永远不要随便改打包流程！v6 能打开 v7 打不开，根因是我"自作聪明"改了打包方式。**

### 走过的弯路（不要再走）
1. ❌ 第一次 v7 build：用 `python -m PyInstaller app/main.py ...` CLI 直接调 + 绝对路径 add-data
   - 用户双击"智能控件阻止"（不是 SmartScreen 不是 EY 政策，是 exe 本身异常被 Windows 拦）
   - 当时误以为是 build_exe.py 的 monkey-patch 损坏路径，实际不是
2. ❌ 误判为 SmartScreen，让用户去解除 Mark of the Web / 关 SmartScreen
   - 用户说"之前 v6 能直接打开"——这才是关键信号：是 v7 exe 问题，不是系统拦截策略
3. ❌ 误判为 EY 端点管控
   - 用户纠正"这是我自己的电脑不是安永的"——又一次没仔细听用户上下文

### 正确做法（v7-fixed 验证有效）
**直接复制上一版能用的 .spec 文件改名 + 增量改 hidden-import + spec 直接打包**：
```bash
# 1. 复制 v6 的 spec（v6 能打开 = spec 配置正确）
cp scripts/PBC-Agent-v6.spec scripts/PBC-Agent-v7-fixed.spec

# 2. spec 里 hiddenimports 加新增模块（v7 新增 routes_config/routes_projects/routes_briefing）
#    改 name='PBC-Agent-v7-fixed'

# 3. 用 spec 文件直接打包（跳过 build_exe.py 的 monkey-patch，避免路径解析不一致）
cd scripts && python -m PyInstaller PBC-Agent-v7-fixed.spec --noconfirm \
  --distpath=D:/AgentProjects/IpoPBC/0 --workpath=D:/AgentProjects/IpoPBC/0/build
```
- 71 秒完成，56.7MB，能正常打开

### 经验法则（不要再违反）
1. **打包流程和上一版一致**，只增量加 v7 新增的 hidden-import，不动其他配置
2. **新增 Python 模块必须加到 spec 的 hiddenimports**（routes_config.py 等 v7 新增文件）
3. **spec 文件用 `..\\app\\main.py` 相对路径**（spec 在 scripts/ 下，相对路径要对）
4. **不要用 CLI 直接调 PyInstaller app/main.py**——它会重新生成 spec，路径处理和 build_exe.py 流程不一致，容易出 exe 异常
5. **用户说"之前能打开现在不能"** → 100% 是新版 exe 有问题，**绝对不是**系统拦截策略（SmartScreen/EY/杀软）——别浪费时间让用户去关防护
6. **听用户上下文**——"这是我自己电脑"已经排除了 EY 政策的可能性，不要继续猜测

## 架构
- 前端：单文件 Alpine.js SPA（index.html 110KB+）
- 后端：FastAPI + SQLite（WAL 模式）
- 多项目支持：projects 表 + 所有表含 project_id 字段
- 文件处理：本地路径直接读取，零上传
- AI 分类：百炼 API（文件名优先匹配 → AI 内容分类 → 未识别归档到未分类/）

## 关键用户反馈
1. 审计员说"主题是提高效率，解放双手"——风险信号卡是锦上添花
2. 路径/分类/文件对应必须透明可见
3. 创建项目流程应该是 3 步向导引导
4. 产品定位：本地单机版，数据存在本地电脑

## 待实施需求（2026-07-22 Opus 4.8 新增，等用户发完整方案）
- **列设置功能**：表格默认 7 列（编号/一级分类/资料描述/实体归属/状态/逾期/操作），隐藏 4 列（相关科目/修改状态/置信度/文件路径），固定 2 列（编号/操作不可取消），右上角「列设置」勾选弹窗，per-tab 记忆列配置
- 后端需支持 per-tab 列配置持久化

## v7.5 数据迁移教训（2026-07-24，重要！）

**改契约时数据必须同步迁移，否则就是新的"改偏了不知道"。**

### 踩过的坑
v7.5 改了 PBC 模板从 15 列 → 16 列，item_id 从第 1 列挪到第 2 列（二级分类字段）。
但 mock_data + demo PBC 清单没同步迁移，导致：
- `_find_item_row` 在第 2 列找"历-1"，但第 2 列实际是"历史沿革"→ 找不到
- 状态机接口全 400 "未找到资料项"
- 回归 2 FAIL + 交互 13 FAIL

### 正确做法
**改 PBC 模板/接口结构时，必须同步迁移 mock_data + demo PBC 清单 + 测试期望值**。
写一个 `scripts/migrate_pbc_v7_to_v75.py` 这样的迁移脚本，每次改结构都跑一遍。

### 单一可信源的另一面
之前说"代码必须对齐 SPEC"——但反过来也成立：
**SPEC/契约改了，所有依赖契约的数据（mock_data + demo PBC + 测试期望）必须同步迁移**。
否则代码是新的，数据是旧的，测试全 fail 但代码逻辑是对的——花了 30 分钟才发现是数据问题。

### SPEC.md §6 协作纪律新增第 7 条
7. 改 PBC 模板/接口结构时，必须同步迁移 mock_data + demo PBC 清单 + 测试期望值

## 验收测试（2026-07-26 新增，每次修改后必跑）

**测试脚本**：`scripts/test_accept_scan.py`（8个场景）+ `scripts/run_acceptance.sh`（一键跑全套）

**跑法**：`bash scripts/run_acceptance.sh`

**8个验收场景**：
1. 首次扫描出待归档
2. 首次确认归档全部成功
3. 无变化再扫描不重复
4. 加1个新文件扫出1个
5. 删已归档文件触发file_missing
6. 目录内文件不单独出现
7. 归档数匹配（磁盘=客户）
8. 重复扫描不产生重复归档

**必须 8/8 全 PASS 才算改完。**
有任何 FAIL 不准 push，先修到全 PASS。

**已修的关键 bug 清单**（不要再犯）：
- reloadAll 没加载 pending-confirm + archive-tree
- pbc-confirm.js 跟 Alpine 冲突
- switchProject 不调 loadFileZone
- archive_directory 先 mkdir 再检查 exists 导致 _v2
- copytree dirs_exist_ok 同名文件覆盖
- sha256 去重误判同内容不同文件为重复
- manifest mtime 格式不一致（ISO vs 浮点数）导致永远"变了"
- 目录归档 manifest key 不统一（目录名 vs 目录名/文件名）
- 扫描扫出已归档文件（mtime 格式 + 目录 key 不匹配）
- 重复扫描导致 pending_confirm 重复插入
- watchdog 启动时自动跑 AI（应该只标 pending）
- pending_count 数 manifest pending 而非 pending_confirm（误导用户）
- file_missing 误报（detect_missing 检查清单有但没提供的）
- briefing-events 全局不分项目

## 前端分块提醒（2026-07-26 新增，重要！）

**每次改前端必须检查 3 个文件：**
1. `app/static/index.html` — 主页面 HTML + Alpine.js（我写的）
2. `app/static/pbc-enhance.js` — Opus 5 写的运行时增强，会接管按钮/重排顶栏/重做文件变更面板
3. `app/static/pbc-enhance.css` — 增强模块样式

**pbc-enhance.js 用 vanilla JS 运行时注入 DOM，会：**
- 接管顶栏"文件变更"按钮，用 .pbcg-vh 面板重新渲染（覆盖原 changePanel）
- 重排顶栏按钮顺序（tidy 函数）
- 接管今日简报卡片收起/展开

**教训：在 index.html 加按钮/UI 不一定生效，pbc-enhance.js 可能接管覆盖。**
改前端前先 grep pbc-enhance.js 看有没有接管相关元素。
