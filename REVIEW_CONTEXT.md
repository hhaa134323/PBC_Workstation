# PBC 智能管理工作站 — 前端视觉优化求助

## 背景

这是一个 IPO 审计 PBC（客户提供资料）智能管理工作站的前端。
单文件 Alpine.js SPA + 手写 CSS（不用 Tailwind，但遵循 shadcn/ui 设计系统约定）。

## 当前状态

已完成 shadcn strict 6 个维度重构 + EY 品牌色替换：
- ✅ 颜色系统：EY 7 色品牌（黑底黄字主按钮）
- ✅ 间距：全部 4px grid
- ✅ Card：ring-1 内边框替代 border+shadow
- ✅ 按钮变体：padding 16px、font 14px
- ✅ Typography：font-size 统一到 12/14/16/20/30/36
- ✅ Modal：去 blur、纯黑 80% 遮罩

规格都对，但"还是觉得不够美观"。

## 5 个视觉层次问题（需改进）

### 问题 1：页面缺少呼吸感（间距太均匀）
所有 margin-bottom 都是 16px，没有"大间距分隔 section，小间距分隔元素"的层次。
shadcn dashboard 用 section 间 py-4(16) + 内部 gap-2(8)，拉开对比。

### 问题 2：gauge 卡片视觉权重太重
`.gauge .v` font-size:30px 太大，4 个并排时数字抢走所有注意力。
shadcn SectionCards 用 text-2xl(24px) + 更淡的 label 颜色。

### 问题 3：Card 缺少 header 结构
card-h 和 card-desc 直接堆在 card-pad 里，没有 CardHeader 独立区域。
shadcn card 有 header/content/footer 三段结构，header 有独立 padding。

### 问题 4：表格太密，行高压抑
10+ 列塞满宽度，每列很窄。shadcn DataTable 用更少列 + 行高 16px + 列宽自适应。

### 问题 5：配色缺少层次感
全页灰白黑，唯一彩色是状态 badge。
shadcn dashboard 在 icon 背景、进度条用 muted/50 半透明做"浅色色块"增加层次。

## EY 品牌色板（已应用）

| 色名 | Hex | HSL | CSS 变量映射 |
|---|---|---|---|
| EY Yellow | #FFE600 | 54 100% 50% | --primary-foreground, --ring, tab 下划线, 进度条 |
| EY Off White | #F6F6FA | 240 29% 97% | --background |
| EY Gray 02 | #C4C4CD | 240 8% 79% | --border |
| EY Gray 01 | #747480 | 240 5% 48% | --muted-foreground |
| EY Off Black | #2E2E38 | 240 10% 20% | --primary（主按钮背景）|
| EY Confident Black | #1A1A24 | 240 16% 12% | --foreground |

主按钮 = 黑底(EY Off Black) + 黄字(EY Yellow) = EY 经典配色

## 设计约束

1. **单文件 SPA**：所有 CSS + JS 在一个 HTML 文件里，不能用 Tailwind CDN（已用 cdn.tailwindcss.com 但只是兜底，主样式是手写）
2. **Alpine.js**：x-data/x-show/x-for/x-text 指令，不能改框架
3. **保留审计状态色**：中国审计习惯（红=未提供，绿=已提供），不能动
4. **零 emoji**：全部用 SVG Lucide icon
5. **最小侵入**：用 Edit 改 CSS 值和 class 名，不重写 HTML 结构

## 需要你帮忙

基于以上 5 个问题，给出具体的 CSS 修改建议（不要泛泛而谈，要能直接 Edit 的代码）。
目标是让页面"从规格正确"变成"视觉舒适"。

参考：https://ui.shadcn.com/blocks/dashboard-01
