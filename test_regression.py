# PBC 智能管理工作站 — 回归测试清单

## 使用方法
每次代码改动后，逐项执行验证。标记 ✓ / ✗。

## v4 回归测试结果（2026-07-22 12:52，exe 验证通过）
## v4+shadcn+EY 回归测试结果（2026-07-22 14:30，shadcn strict 6 维度 + EY 品牌色重构后）

---

## 一、后端 API 层（curl 验证）

### 1.1 基础接口
- [✓] `GET /health` → 200 `{"status":"ok","version":"0.1.0"}`
- [✓] `GET /` → 200 返回 HTML（含 `<svg` 标签）
- [✓] HTML 中 0 个 emoji（`ord(ch) > 0x1F000`）
- [✓] HTML 中 SVG icon 数 = 28（≥27）

### 1.2 项目管理
- [✓] `GET /api/projects/list` → 返回 2 个项目（demo + 07-22-11-34）
- [✓] `POST /api/projects/create` → 创建成功，返回 project_id="regtest"
- [✓] `PUT /api/projects/{id}` body `{"name":"regtest_renamed"}` → ok:true
- [✓] `DELETE /api/projects/{id}?soft=true` → ok:true, soft_deleted:true
- [✓] `DELETE /api/projects/demo` → 400（demo 不可删）

### 1.3 PBC 清单
- [✓] `GET /api/pbc/demo/list` → 6 items
- [✓] 每个 item 有 item_id, status_normalized, confidence, file_path 字段
- [✓] `PUT /api/pbc/demo/{item_id}/status` → 状态更新成功（需 changed_by 字段）

### 1.4 风险信号
- [✓] `GET /api/risk/demo/dashboard` → 有 overall_progress + overdue_items
- [✓] `GET /api/risk/demo/heatmap` → 4 entities + 5 categories + 1 cell
- [✓] `GET /api/risk/demo/resolve/关-1` → 有 risk_signal 字段（dict）
- [✓] `GET /api/risk/demo/escalation` → 有 report_text（568 字）

### 1.5 文件处理
- [✓] `GET /api/files/demo/config/folder` → current.path + current.file_count=6
- [✓] `POST /api/files/demo/scan-folder` → 返回 task_id
- [✓] `GET /api/files/demo/recent-tasks` → 14 tasks
- [✓] `GET /api/files/demo/archive-detail/借-1` → 1 archive（含 original_path, archived_path, file_size, sha256）
- [✓] `POST /api/open-folder/demo` → ok:true（os.startfile 打开文件管理器）

### 1.6 简报
- [✓] `GET /api/briefing/demo` → summary.total_events=1
- [✓] `GET /api/files/briefing-events?since=0` → events 数组（0 events，因 since=0 时间戳早于所有事件）

---

## 二、前端 UI 层（静态分析验证，2026-07-22 12:53）

### 2.1~2.10 功能存在性检查
- [✓] 首启引导代码存在（onboarding/firstRun 出现 7 次）
- [✓] 3 步向导代码存在（createWizardStep/wizard 出现 48 次）
- [✓] 项目抽屉存在（drawerOpen/projMenu 出现 13 次）
- [✓] 扫描卡片存在（scan-card/currentFolderInfo 出现 15 次）
- [✓] 打开文件夹存在（openExplorer 出现 4 次）
- [✓] 文件详情 modal 存在（fileDetail/archive-detail/viewDetail 出现 31 次）
- [✓] 重命名功能存在（doRenameProject/renameProjectModal 出现 13 次）
- [✓] 删除项目存在（doDeleteProject/deleteProjectModal 出现 14 次）
- [✓] 本地说明文案存在（"此应用运行在本地，数据存在你的电脑"）
- [✓] 查看测试资料按钮存在
- [✓] Promise.all 并行加载（2 处）
- [✓] JS 语法通过 node -e 校验（30 functions found, syntax OK）

### 注：交互级验证（点击/弹窗/动画）需在浏览器手动操作
### 静态分析已确认所有功能代码存在且语法正确

---

## 三、性能验证（2026-07-22 12:53，v4 exe）

- [✓] 切换项目 < 2 秒完成（6 API 并行，实测 PBC list 0.159s）
- [✓] dashboard 秒回（0.145s）
- [✓] briefing 秒回（0.151s）
- [✓] heatmap 秒回（0.148s）
- [✓] archive-detail 秒回（0.126s）
- [✓] recent-tasks 秒回（0.127s）
- [✓] folder-config 秒回（0.127s）
- [✓] 页面首屏 < 1 秒（HTML 静态文件直出）
- [✓] SVG icon 数稳定（28 个，不丢失）
- [✓] 重命名项目 < 200ms（本地更新，不重新加载 — 代码确认）

---

## 四、shadcn 规范检查（2026-07-22 14:30，shadcn strict 重构后）

- [✓] 0 个 emoji
- [✓] SVG icon = 28（≥27）
- [✓] CSS 变量用 hsl() 包装（215 处 hsl(var(--...))）
- [✓] 无 var(--pri) 等不存在的变量（0 处）
- [✓] JS 语法通过 node -e 校验（OK）
- [✓] spinner 全部是 SVG Loader2（7 处）
- [✓] 刷新按钮是 RotateCw SVG（1 处）
- [✓] Toast 用 x-text（0 处 x-html="t.text"）
- [✓] item_id 转义（4 处 this.esc(it.item_id)）
- [✓] `:root` 外零硬编码 hex（CSS 规则中 0 处）
- [✓] font-size 全部标准值：12/14/16/20/30/36

## 四-B、EY 品牌色检查（2026-07-22 14:30）

- [✓] EY Yellow 定义：--ey-yellow: 54 100% 50%
- [✓] --primary = EY Off Black（黑底主按钮）
- [✓] --primary-foreground = EY Yellow（黄字按钮文字）
- [✓] --background = EY Off White
- [✓] --border = EY Gray 02
- [✓] --muted-foreground = EY Gray 01
- [✓] --ring = EY Yellow（focus ring）
- [✓] EY Yellow 点缀：tab 下划线、进度条、logo（4 处）

## 四-C、性能验证（2026-07-22 14:30）

- [✓] /health: 0.006s
- [✓] /api/projects/list: 0.005s
- [✓] /api/pbc/demo/list: 0.015s
- [✓] /api/risk/demo/dashboard: 0.012s
- [✓] /api/risk/demo/heatmap: 0.015s
- [✓] /api/briefing/demo: 0.024s
- [✓] /api/files/demo/config/folder: 0.006s

---

## 五、打包验证（2026-07-22 12:47）

- [✓] exe 文件存在（16MB PBC-Agent-v4.exe）
- [✓] exe 总大小 112MB（含 _internal/）
- [✓] 双击 exe → 浏览器自动打开
- [✓] health 接口正常（{"status":"ok"}）
- [✓] 前端页面正常加载（HTML 含 28 SVG, 0 emoji）
- [✓] briefing 接口秒回（0.151s）
- [✓] zip 文件生成（110MB PBC-Agent-v4.zip）
- [✓] 数据文件全部包含（app/static, mock_data, config, projects）
