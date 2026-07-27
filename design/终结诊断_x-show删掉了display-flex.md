# 终结诊断：今日简报细条不是样式问题，是 `x-show` 删掉了 `display:flex`

日期：2026-07-27
文件：`app/static/index.html`
优先级：高（同类 bug 可能在全页存在多处）

---

## 一、真因（运行时取证，非推测）

在浏览器 Console 里打印细条容器的实际内联样式：

```js
document.querySelector('[x-text*="briefHasDelta"]').parentElement.getAttribute('style')
```

返回：

```
align-items: center; gap: 10px; padding: 10px 16px; margin-bottom: 16px; background: hsl(var(--card)); ... border-left: 3px solid hsl(var(--ey-yellow)); border-radius: 10px; cursor: pointer; ...
```

**`display: flex` 不存在。** 而源码第一个属性就是 `display:flex`。

### 后果

容器退化成普通块级元素，于是：

| 声明 | 在块布局下的实际效果 |
|---|---|
| `gap:10px` | 完全无效（gap 仅对 flex/grid 生效）|
| `align-items:center` | 完全无效 |
| 子元素 `flex:1;min-width:0` | 完全无效 |
| 子元素 `margin-left:auto` | 完全无效 |
| 子元素 `flex-shrink:0` | 完全无效 |

五个 `<span>` 作为行内元素横排，间隔只来自源码换行产生的空白字符。

**这就是“文字全挤在一起”的根本原因。之前所有调 flex 参数的尝试全部无效，因为它从未是 flex 容器。**

---

## 二、为何 `display:flex` 会消失

Alpine v3 `x-show` 的实现：

```js
// 隐藏
el.style.display = 'none'

// 显示
el.style.removeProperty('display')   // ← 连作者写的 display:flex 一起删掉
```

显示时它不是“恢复原值”，而是**直接移除 `display` 属性**。

### 触发时机（每次加载必发）

`x-show="!loading && pbcList.length > 0 && briefFolded"`

1. 页面初始 `loading = true` → 条件为 false → Alpine 写入 `display:none`
2. 数据加载完 `loading = false` → 条件为 true → Alpine 执行 `removeProperty('display')`
3. 作者写的 `display:flex` 随之消失，永不回来

**结论：`x-show` 与内联 `display` 不能共存。**

---

## 三、修法

原理：`x-show` 只能删除**内联**的 `display`，删不掉 CSS 类里的。

- 隐藏时：Alpine 写入内联 `display:none`，优先级高于类，能正常隐藏 ✅
- 显示时：内联 `display` 被清空，类里的 `display:flex` 自动接管 ✅

### 步骤 1：在 `<style>` 块里新增规则

位置：`index.html` 已有的 `<style>` 块末尾（约第 460 行，`</style>` 之前）。
**不要写进 `pbc-enhance.css`** —— 那个文件顶部已注明“模块一样式已删除（今日简报折叠改为 Alpine 原生控制）”，再往里加会重现“两套状态打架”。

```css
/* 今日简报收起态细条：display 必须放在类里，
   因为 Alpine x-show 显示时会执行 removeProperty('display')，
   会把内联的 display:flex 一起删掉。切勿改回内联。 */
.brief-bar{
  display:flex;
  align-items:center;
  gap:0;
  height:50px;
  padding:0 14px 0 16px;
  margin-bottom:16px;
  background:hsl(var(--card));
  border:1px solid hsl(var(--border));
  border-left:3px solid hsl(var(--ey-yellow));
  border-radius:10px;
  cursor:pointer;
  transition:background .15s, box-shadow .15s;
  box-shadow:0 1px 2px rgba(26,26,36,.06);
}
.brief-bar:hover{
  background:hsl(54 100% 98%);
  box-shadow:0 2px 6px rgba(26,26,36,.09);
}
/* 绿点 / 琥珀点 */
.brief-bar .bb-dot{width:8px;height:8px;border-radius:99px;flex-shrink:0;margin-right:10px}
/* 标题 */
.brief-bar .bb-title{font-size:13px;font-weight:700;flex-shrink:0;letter-spacing:-.1px}
/* 发丝分隔竖线 */
.brief-bar .bb-div{width:1px;height:15px;background:hsl(var(--border));flex-shrink:0;margin:0 16px}
/* 结论句：flex:1 是关键，让右侧元素靠右端 */
.brief-bar .bb-msg{flex:1;min-width:0;font-size:13px;color:hsl(var(--foreground));overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* 上次查看 */
.brief-bar .bb-seen{flex-shrink:0;font-size:12px;color:hsl(var(--muted-foreground));white-space:nowrap}
/* 展开胶囊 */
.brief-bar .bb-more{display:inline-flex;align-items:center;gap:5px;flex-shrink:0;height:28px;padding:0 10px;margin-left:14px;border-radius:6px;background:hsl(var(--muted));font-size:12.5px;font-weight:600;color:hsl(var(--foreground));white-space:nowrap}
.brief-bar:hover .bb-more{background:hsl(240 12% 90%)}
```

### 步骤 2：替换细条 HTML

定位：注释 `<!-- 收起时：细条 -->` 下面那个 `div` 整块。

**关键：新的 `div` 上一个 `style` 属性都不允许有。**

```html
<div class="brief-bar" x-show="!loading && pbcList.length > 0 && briefFolded" @click="toggleBriefFold()">
  <span class="bb-dot" :style="'background:'+(briefHasDelta?'hsl(38 92% 50%)':'hsl(142 71% 45%)')"></span>
  <span class="bb-title">今日简报</span>
  <span class="bb-div"></span>
  <span class="bb-msg" x-text="briefHasDelta ? '文件夹 '+(briefingDelta.delta_count||0)+' 处变动待分析' : '无新变化。'+(briefingDelta.stock_total||0)+' 项已超期待催收，详情看下方表格'"></span>
  <span class="bb-div" style="margin-left:auto;margin-right:16px"></span>
  <span class="bb-seen" x-show="briefSeenStr" x-text="'上次查看 '+briefSeenStr"></span>
  <span class="bb-more">展开<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>
</div>
```

> 注 1：第二道 `bb-div` 上的内联 `margin-left:auto` 是安全网——即使 `bb-msg` 的 `flex:1` 因任何原因失效，右侧仍会靠右。它不是 `display`，不会被 `x-show` 删。
>
> 注 2：`bb-seen` 带 `x-show`，但它的 `display:inline` 是浏览器默认值而非内联值，不受本 bug 影响。
>
> 注 3：若本地 `x-text` 文案与上面不同，保留本地的，只改 `class` 和删 `style`。

---

## 四、验收

硬刷新 `Ctrl+Shift+R`，在 Console 依次跑：

```js
const bar = document.querySelector('.brief-bar');
getComputedStyle(bar).display                    // 必须是 "flex"
getComputedStyle(bar).height                     // 必须是 "50px"
getComputedStyle(bar.querySelector('.bb-msg')).flexGrow   // 必须是 "1"
bar.getAttribute('style')                        // 必须是 null（或不含 display）
```

四项全对才算改完。

目视：

1. “上次查看 XX” + “展开” 贴在细条**右端**
2. 两道 1px 竖线可见
3. 窗口 1920 → 1280，中间句子不提前变省略号
4. 鼠标悬停整条变浅黄底，光标为手型
5. 点一下能展开，再点收起能回来（**重点：反复展开/收起 5 次，细条布局不能退化**）

---

## 五、同类 bug 全页排查（强烈建议）

这个坑不只影响细条。任何**同时带 `x-show` 与内联 `display:`** 的元素都有同样问题。

排查方法（在 Console 里跑，不用改代码）：

```js
[...document.querySelectorAll('[x-show]')]
  .filter(el => /display\s*:/.test(el.getAttribute('style') || ''))
  .map(el => el.getAttribute('x-show'));
```

返回的每一条 `x-show` 表达式，对应的元素都是潜在受害者。典型嫌疑位置：

- 消息中心面板（~468 行）
- 文件变更面板（~542 行）
- Toast 区（~628 行）
- 首启引导 3 步（~643 行）
- 各类 modal / drawer
- 空清单提示、`.scan-hero`

统一治法同上：把 `display` 搬进 class，内联只留非 display 属性。

建议把这条写进 `docs/前端开发指南.md` 作为硬约束：

> **带 `x-show` 的元素，绝不允许在内联 `style` 里写 `display`。**
> Alpine 显示元素时会 `removeProperty('display')`，会把你写的 `display:flex` / `display:grid` 一起删掉。
> 布局类型必须放在 CSS 类里。

---

## 六、不要做的事

- 不要把 `display:flex` 写回内联 style（会立刻重现本 bug）
- 不要用 `x-cloak` / `x-if` 替换 `x-show` 来绕（`x-if` 会重建 DOM，影响折叠动画与事件绑定）
- 不要把新增 CSS 写进 `pbc-enhance.css`
- 不要动 `briefFolded` / `toggleBriefFold()` / `briefHasDelta` / `briefSeenStr`
- 不要动展开态大卡片
- 不要删任何废弃文件
