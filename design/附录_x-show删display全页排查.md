# 附录：`x-show` + 内联 `display` 全页排查与治法

配套文档：《终结诊断_x-show删掉了display-flex.md》
日期：2026-07-27

---

## 一、先说清楚：144 个不等于 144 个 bug

上一轮我给的 Console 排查命令**误报率很高**，原因有两个：

### 误报源 1：Alpine 自己写的 `display:none` 也被匹配了

当一个 `x-show` 元素处于隐藏状态时，Alpine 会往它身上写入内联 `display:none`。我的正则 `/display\s*:/` 把这些全部当成了受害者。它们是正常的，不是 bug。

### 误报源 2：`x-for` 模板里的一处源码，运行时会重复几十次

你输出里 `'m.item_id', 'm.version', 'm.reason'` 这三个反复出现约 26 轮 → 它们是消息中心列表模板里的 **3 处源码**，被 26 条消息各渲染了一份。

**按去重后估算，真正需要看的源码位置大约在 20 处量级，而且其中一部分无害。**

### 反向盲区（更危险）

反过来，当前**正处于隐藏状态**的元素，它原本的 `display:flex` 已经被 Alpine 换成了 `display:none`，运行时根本看不出来。所有 modal / drawer 默认都是隐藏的，**恰好全在盲区里**。

结论：**运行时 Console 不是可靠的排查手段，必须扫源码。**

---

## 二、正确的排查方式：扫源码

在项目根目录执行（Windows PowerShell）：

```powershell
Select-String -Path app\static\index.html -Pattern 'x-show' |
  Where-Object { $_.Line -match 'display\s*:\s*(flex|grid|inline-flex|inline-grid|block|inline-block|table)' } |
  ForEach-Object {
    $t = $_.Line.Trim()
    if ($t.Length -gt 150) { $t = $t.Substring(0,150) + '...' }
    "$($_.LineNumber)`t$t"
  }
```

输出的每一行都是真实受害者，带行号。注意这个正则**排除了 `display:none`**（那是合法的初始隐藏写法，不受影响）。

若有 git bash / WSL：

```bash
grep -n 'x-show' app/static/index.html | grep -E 'display\s*:\s*(flex|grid|inline-flex|block)'
```

---

## 三、危害分级（按优先级修）

不是所有命中项都会出现可见故障。判断标准：**这个元素的子元素排列是否依赖 flex/grid？**

### P0 · 必修（丢了布局就明显错位）

凡是用 `display:flex` 做**居中遮罩层**或**横排容器**的：

| x-show 表达式 | 估计位置 | 失效后现象 |
|---|---|---|
| `messageCenter.show` | ~468 行 消息中心面板 | 面板内容堆叠/不居中 |
| `changePanel.show` | ~542 行 文件变更面板 | 同上 |
| `showOnboarding` | ~643 行 首启引导 | 遮罩层不居中 |
| `showProjectDrawer` | ~733 行 项目抽屉 | 抽屉布局退化 |
| `folderConfig.show` | ~792 行 文件夹配置 modal | 弹窗不居中 |
| `aiConfig.show` | ~836 行 AI 配置 modal | 同上 |
| 其余 modal 的 `*.show` | ~883/903/938/963/1080/1107/1128/1183 行 | 同上 |

> ❗ 这些默认隐藏，运行时扫不到。**必须靠源码 grep + 逐个手动打开验证。**

### P1 · 建议修

| x-show 表达式 | 位置 | 现象 |
|---|---|---|
| `scan.active` | ~1300 行 `.scan-hero` | 扫描提示排版挤 |
| `projectsLoadError` / `folderConfig.error` / `aiConfig.testResult` 等 | 各错误/结果提示条 | 图标与文字不对齐 |
| `projects.length===0` | 项目抽屉空态 | 空态提示不居中 |
| `folderConfig.info` / `archiveInfo` | 信息块 | 横排变竖排 |

### P2 · 可不改

| 情形 | 理由 |
|---|---|
| 内联只有 `display:none` | 那是初始隐藏写法，Alpine 删它正是预期行为 |
| `m.item_id` / `m.version` / `m.reason` | 如果内联是 `display:inline-block` 且子元素不依赖 flex，丢了也看不出差异 |
| `i < changePanel.items.length-1` | 分隔线元素，不依赖 flex |
| `projMenu.show===p.project_id` | 小菜单，往往是 `position:absolute` 而非 flex |

**判定方法**：看这个元素的 style 里除了 `display` 还有没有 `align-items` / `justify-content` / `gap` / `flex-direction`。有 → P0，必修。没有 → 往后放。

---

## 四、统一治法（三种，按情形选）

### 方案 A · 抽成语义 class（适用于细条、面板等唯一元素）

见《终结诊断》文档的 `.brief-bar` 写法。

### 方案 B · 复用通用工具类（适用于十几个 modal 批量改，最省事）

在 `index.html` 的 `<style>` 块末尾加三个工具类：

```css
/* x-show 安全布局工具类。
   Alpine x-show 显示元素时执行 removeProperty('display')，
   会把内联 display:flex 删掉。display 必须放在类里。 */
.d-flex{display:flex}
.d-iflex{display:inline-flex}
.d-grid{display:grid}
```

然后每个受害元素只改两处：

```html
<!-- 改前 -->
<div x-show="aiConfig.show" style="display:flex;align-items:center;justify-content:center;...">

<!-- 改后：删掉 display:flex;，加 class -->
<div class="d-flex" x-show="aiConfig.show" style="align-items:center;justify-content:center;...">
```

**其余内联属性一律不动。** 这是改动量最小、风险最低的方案，适合批量处理。

> 已有 `class` 属性的元素，追加而不是覆盖：`class="modal d-flex"`。

### 方案 C · 存量 CSS 类已有 display（最简）

若该元素已有 `class="modal"` 且 `.modal` 规则里已经包含 `display:flex`，则**只需删掉内联的 `display:flex;`**，不用加任何东西。

先查 `.modal` / `.drawer` / `.rblock` 等现有规则（~130-400 行）里有没有 `display`。有就走方案 C。

---

## 五、推荐执行顺序（四天截止，控住范围）

1. **先只改今日简报细条**（方案 A）。改完验收通过，证明诊断成立。
2. **跑源码 grep**，拿到带行号的真实清单。
3. **先目视体检，再改代码**：把 P0 里每个 modal / 面板 / 抽屉**手动点开一遍**，看哪个真的错位。看起来正常的先不动。
   > 很可能部分 modal 本来就依赖 `.modal` 类的 `display`，一直好好的。
4. 真错位的那几个，用方案 B 或 C 批量修。
5. 把约束写进 `docs/前端开发指南.md`（下一节）。

**不要一口气改 144 处。** 大部分是假阳性，改了只增加回归风险，而你只剩 4 天。

---

## 六、写进开发指南的硬约束

请把下面这段追加到 `docs/前端开发指南.md`：

```markdown
## 约束：`x-show` 与内联 `display` 不能共存

Alpine v3 的 `x-show` 显示元素时执行：

    el.style.removeProperty('display')

它不是“恢复原值”，而是 **直接移除 display 属性**。
作者写在内联 style 里的 `display:flex` / `display:grid` 会被一起删掉，
元素退化为块级，同时导致以下声明全部失效：
gap / align-items / justify-content / flex / flex-shrink / margin-left:auto

**硬规矩：带 `x-show` 的元素，内联 `style` 里绝不允许写 `display`。**

- 布局类型（flex / grid / inline-flex）必须放在 CSS 类里
- 内联只允许保留非 display 属性
- 例外：内联 `display:none` 作初始隐藏是安全的

### 反例
    <div x-show="modal.show" style="display:flex;align-items:center">

### 正例
    <div class="d-flex" x-show="modal.show" style="align-items:center">

### 自查（提交前跑）
    Select-String -Path app\static\index.html -Pattern 'x-show' |
      Where-Object { $_.Line -match 'display\s*:\s*(flex|grid|inline-flex)' }

有输出就不能提交。

### 历史事故
2026-07-27：今日简报收起态细条“文字全挤在一起”。
表面看是排版问题，实际是容器从未成为 flex 容器。
前后三轮调整 gap / flex:1 / margin-left:auto 全部无效，
直到在 Console 打印 getAttribute('style') 发现 display 不存在。
教训：排版异常先查 computed display，再调 flex 参数。
```

---

## 七、下次遇到类似问题的诊断顺序

排版看起来不对时，**先跑这三句，再动任何样式**：

```js
const el = /* 目标容器 */;
getComputedStyle(el).display        // 是不是你以为的那个？
el.getAttribute('style')            // 内联实际剩下什么？
el.className                        // 类里有没有被覆盖？
```

第一句就能排除掉一大类“改了没反应”的情况。
