# v7.7 前端需求说明

> 写给 Opus 5：后端 v7.7 HITL 流程已就绪，本文梳理前端需求。

---

## 背景

旧流程：AI 扫描 → 直接归档 → 状态推进到「审核中」→ 人复核
新流程：**AI 扫描 → 只建议不归档 → 人确认 → 才归档**

核心变化：归档动作从"AI 先斩后奏"变成"人确认后才执行"。

---

## 需求 1：「待复核」tab 改成「待归档」

现在 review tab 显示的是 `pbcList` 里 status="已提供，审核中" 的行（AI 已经归档完了）。

改成显示**还没归档的文件列表**——AI 预分析完、建议了 item_id + 置信度，等人决定要不要归档。

数据来源：`GET /api/files/{pid}/pending-confirm`

每条记录包含：
- 文件名
- AI 建议的 item_id（suggested_item_id）
- 置信度（0-1）
- 决策类型（auto/suggest/llm）
- 编号矛盾信号（有则高亮提示）
- 创建时间

---

## 需求 2：每条文件 3 个操作

| 操作 | 含义 | 接口 |
|------|------|------|
| 确认归档 | 按 AI 建议归档 | `POST /confirm/{id}` |
| 改分类 | 改 item_id 后再归档 | `POST /reclassify-confirm/{id}` 改完再调 confirm |
| 跳过 | 不归档，文件留在客户文件夹 | `POST /skip-confirm/{id}` |

确认归档后：文件拷贝到 archives/，PBC 状态推进，manifest 标 processed。

---

## 需求 3：批量归档

列表顶部一个「全部归档」按钮，一次请求批量归档所有待归档文件。

接口：`POST /batch-confirm`，body 传 confirm_ids 列表。

---

## 需求 4：编号矛盾高亮

如果某条记录有 `conflict_signal`（文件名含编号但描述不匹配），高亮显示提示文案。

这类文件即使置信度很高（auto 档）也不会被自动跳过，必须人确认。

---

## 需求 5：auto 自动归档开关

AI 配置面板加一个开关：**自动归档高置信度文件**。

- 开了：auto 档（>0.70）的文件跳过待归档，直接归档
- 没开（默认）：所有文件都进待归档，人逐条或批量确认

有编号矛盾的文件即使 auto 档也强制进待归档。

配置字段：`auto_confirm_enabled`，通过 `GET/PUT /api/config/ai` 读写。

---

## 不变的部分

- 待初检 tab（triage）—— 不变
- 已完成 tab（done）—— 不变
- 文件变更面板（changePanel）—— 已完成
- 改分类弹窗（reclassifyModal）—— UI 不变，只是改成调 reclassify-confirm 接口

---

## 接口一览

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/files/{pid}/pending-confirm` | GET | 待归档列表 |
| `/api/files/{pid}/confirm/{id}` | POST | 确认归档 |
| `/api/files/{pid}/batch-confirm` | POST | 批量归档 |
| `/api/files/{pid}/skip-confirm/{id}` | POST | 跳过 |
| `/api/files/{pid}/reclassify-confirm/{id}` | POST | 归档前改分类 |

完整接口文档见 `文档/API契约_v7.md` v7.7 段。

---

## 验证方式

开启 HITL 模式启动：`PBC_HITL_MODE=1 PBC_SKIP_AI_INIT=1 python -m uvicorn app.main:app --port 8111`

扫描文件后，review tab 应该有待归档列表。点确认/改分类/跳过/全部归档，看结果对不对。
