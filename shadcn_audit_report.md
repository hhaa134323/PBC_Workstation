# PBC 智能管理工作站 — shadcn strict 审计报告

> 审计日期：2026-07-22 13:00
> 基准：https://ui.shadcn.com/blocks + https://ui.shadcn.com/docs/components/card
> 目标文件：`app/static/index.html`（~100KB, 2048 行）

---

## 一、问题清单（按优先级排序）

### 1. Card 结构 ❌

**shadcn 规范：**
- Card = `rounded-xl bg-card ring-1 ring-foreground/10`（不是 border + shadow-sm）
- CardHeader = `gap-1 px-(--card-spacing)`，grid 布局
- CardTitle = 独立标题
- CardDescription = muted-foreground 描述
- CardAction = 右上角操作区
- CardContent = `px-(--card-spacing)`
- CardFooter = `border-t bg-muted/50 p-(--card-spacing)`
- --card-spacing 默认 16px（spacing(4)），sm=12px（spacing(3)）

**当前代码问题：**
- `.card` 用 `border:1px solid + box-shadow:shadow-sm` → 应改 `ring-1 ring-foreground/10`（无 shadow）
- `.card-pad` 用 `padding:24px` → 应改 `padding:16px`（--card-spacing 默认值）
- 没有 CardHeader/CardFooter 语义结构，用 `.card-h` + `.card-desc` 模拟
- `.card-h` margin-bottom:4px → 应 gap-1（4px gap，grid 布局）
- `.card-desc` margin-bottom:16px → 不应有，用 grid gap 控制
- 没有 CardAction（右上角操作区）模式

**修复方案：**
```css
.card{background:hsl(var(--card));border-radius:var(--r-xl);box-shadow:none;
  /* ring-1 ring-foreground/10 = 1px solid rgba(foreground,0.1) */
  box-shadow:inset 0 0 0 1px hsla(240 10% 3.9% / 0.1);}
.card-pad{padding:16px}  /* --card-spacing */
.card-h{margin-bottom:0}  /* 用 gap 替代 */
.card-desc{margin-bottom:0}
```

---

### 2. 间距 ❌

**shadcn 规范：**
- `--spacing` = 4px 基准
- 所有间距是 4 的倍数：4/8/12/16/20/24/32
- gap-4 = 16px（section 间）
- gap-1 = 4px（标题与描述间）
- p-4 = 16px（card padding）
- py-4 = 16px（section 垂直）

**当前代码问题：**
- `.nav-top` padding:12px 24px → 应 12px/16px（gap-4 基准）
- `.wrap` padding:24px 28px → 应 24px（p-6=24px），28px 非 4 倍数
- `.tab` padding:10px 16px → 10px 非 4 倍数，应 8px 或 12px
- `.tbl th` padding:12px 16px → 应 12px/16px（符合）
- `.tbl td` padding:14px 16px → 14px 非 4 倍数，应 12px 或 16px
- `.card-h` font-size:16px → shadcn CardTitle 是 text-lg(18px) 或保持 16px
- `.modal-b` padding:20px 24px → 应 24px（p-6）
- `.modal-h` padding:20px 24px → 应 24px
- `.gauge` padding:20px 24px → 应 24px

**修复方案：** 逐项修正到 4 的倍数。

---

### 3. 按钮命名与变体 ❌

**shadcn 规范（6 个标准变体）：**
| 变体 | class | 用途 |
|---|---|---|
| default | bg-primary text-primary-foreground | 主操作 |
| secondary | bg-secondary text-secondary-foreground | 次要 |
| destructive | bg-destructive text-destructive-foreground | 危险操作 |
| outline | border border-input bg-background | 次要操作 |
| ghost | hover:bg-accent | 透明 |
| link | text-primary underline | 链接 |

- 默认 height: 36px (h-9)
- padding: 8px 16px (px-4 py-2)
- border-radius: var(--radius) = 0.5rem = 8px
- font-size: 14px (text-sm)
- font-weight: 500 (font-medium)

**当前代码问题：**
- `.btn-pri` → 应叫 `.btn-default`
- `.btn-ghost` → 实际是 shadcn 的 `outline`（有 border），不是 `ghost`（无 border）
- `.btn-soft` → 应叫 `.btn-secondary`
- `.btn-green` → shadcn 无此变体，应归入 destructive 色系或自定义
- `.btn-red` → 应叫 `.btn-destructive`
- `.btn-xs` → shadcn 用 `size="sm"` 控制，不是独立 class
- height:36px → 符合 h-9
- padding:8px 14px → 应 8px 16px（px-4）
- border-radius:var(--r)=6px → 应 var(--r-lg)=8px（shadcn 默认 0.5rem）

**修复方案：** 重命名 + 调 padding/radius。

---

### 4. 颜色系统 ❌

**shadcn 规范：**
- 全部 HSL 变量，无硬编码
- `--ring: 240 10% 3.9%`（focus ring）
- `--radius: 0.5rem`（8px）
- 无 `--shadow-sm/md/lg` 变量（用 Tailwind 的 shadow-sm 等）
- destructive 用 `0 84.2% 60.2%`

**当前代码问题：**
- `--green: #16A34A` → 硬编码 hex，应改 HSL 变量
- `--orange: #D97706` → 硬编码
- `--red: #DC2626` → 硬编码
- `--purple: #7C3AED` → 硬编码
- 审计状态色 `--st-none-bg:#FFC7CE` 等 → 全硬编码 hex
- `--shadow` 等变量不是 shadcn 标准
- `--r: 0.375rem` (6px) → shadcn 标准是 `--radius: 0.5rem` (8px)
- hover 状态用 `hsl(240 5.9% 16%)` 硬编码 → 应用 `hsl(var(--primary))` + opacity

**修复方案：** 把 hex 色转 HSL 变量，统一用 `hsl(var(--xxx))` 引用。

---

### 5. Typography ❌

**shadcn 规范：**
| class | size | weight | 用途 |
|---|---|---|---|
| text-xs | 12px | 400 | 辅助文字 |
| text-sm | 14px | 400 | 正文/按钮 |
| text-base | 16px | 400 | 标题 |
| text-lg | 18px | 500 | section 标题 |
| text-xl | 20px | 500 | page 标题 |
| text-2xl | 24px | 600 | hero 标题 |

- font-weight: 500 (medium) 为标题默认
- muted-foreground 用于辅助文字
- letter-spacing: -0.2px (tracking-tight) 用于大标题

**当前代码问题：**
- `.page-head h1` font-size:20px → 符合 text-xl，但 font-weight:600 → 应 500
- `.card-h` font-size:16px → 应 text-lg(18px) 或保持
- `.brand .name` font-size:15px → 15px 非 Tailwind 标准
- `.tab` font-size:14px → 符合 text-sm
- `.btn` font-size:13px → 应 14px (text-sm)
- `.tbl` font-size:13px → 应 14px
- `.gauge .v` font-size:30px → 不是标准值，应 text-3xl(30px) ✓
- 多处 font-size:11px/11.5px → 应统一 12px (text-xs)
- `.sidebar-h .brand-sub` font-size:11px → 应 12px

**修复方案：** 统一到 Tailwind 标准 scale：12/14/16/18/20/24/30。

---

### 6. Modal 结构 ❌

**shadcn 规范：**
- Overlay: `fixed inset-0 z-50 bg-black/80` (不是 blur)
- Content: `bg-background p-6 rounded-lg` (max-w-lg, sm:max-w-lg)
- Header: `flex flex-col gap-1.5 text-center sm:text-left`
- Footer: `flex flex-col-reverse sm:flex-row sm:justify-end gap-2`
- Close button: absolute top-4 right-4
- 无 border 在 header/footer（用 gap 分隔）

**当前代码问题：**
- `.overlay` background:rgba(15,15,15,0.5) + backdrop-filter:blur(4px) → 应 bg-black/80 无 blur
- `.modal` border-radius:var(--r-xl)=12px → shadcn 用 rounded-lg(8px)
- `.modal-h` border-bottom:1px solid → shadcn 不用 border，用 gap
- `.modal-b` padding:20px 24px → 应 24px (p-6)
- 没有 modal footer 结构
- `.modal` max-width:640px → shadcn 标准 max-w-lg(512px) 或 max-w-md(448px)
- close 按钮用 `.x` class → 应 absolute 定位

**修复方案：** 去 blur，改 padding，去 header border。

---

## 二、符合标准的维度 ✅

### 7. CSS 动画 ✅
- `@keyframes slideIn`, `fade`, `pop`, `slideL`, `slideR` 均为标准 CSS 动画
- transition 时长 0.15s-0.22s 合理

### 8. 条件渲染 ✅
- Alpine.js `x-show`, `x-if`, `x-cloak` 使用正确
- 无 JS 手动 DOM 操作

---

## 三、修复优先级排序

| # | 维度 | 影响 | 工作量 |
|---|---|---|---|
| 1 | 间距修正 | 视觉一致性 | 中（20+ 处） |
| 2 | 颜色系统去 hex | 可维护性 | 中（10+ 处） |
| 3 | Card 结构 | 核心组件 | 小（5 处） |
| 4 | 按钮命名 | 语义化 | 中（重命名+全局替换） |
| 5 | Typography | 视觉层次 | 小（10 处 font-size） |
| 6 | Modal 结构 | 弹窗体验 | 小（5 处） |

---

## 四、修复原则

1. **最小侵入**：用 Edit 工具替换 CSS 值，不重写 HTML 结构
2. **增量验证**：每修完一个维度，在浏览器刷新确认
3. **不改功能**：只改 CSS 值和 class 名，不改 JS 逻辑
4. **保留审计状态色**：中国审计红绿习惯不动，只改变量引用方式
