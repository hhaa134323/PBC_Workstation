"""生成 PBC 工作站说明材料 v2（打包版 base64 内嵌图片）
按审计员 9 条反馈修改：
1. 无AI可用说明
2. EY品牌配色
3. 风险分析降级为后续拓展
4. 色彩区分度提升
5. 去IPO化
6. 痛点文案替换
7. 待归档加auto_confirm截图
8. 使用前后留位（等Opus5生成图）
9. 推广不强调IPO
"""
import base64, os

IMG_DIR = os.path.join(os.path.dirname(__file__), '..', '文档', '说明材料截图')

def b64img(path):
    full = os.path.join(IMG_DIR, path)
    with open(full, 'rb') as f:
        data = f.read()
    ext = path.rsplit('.', 1)[-1]
    return f'data:image/{ext};base64,{base64.b64encode(data).decode()}'

IMGS = {
    '待归档': b64img('img1.png'),
    '风险分析': b64img('img2.png'),
    '变更记录': b64img('img3.png'),
    '待初检': b64img('img4.png'),
    '项目总览': b64img('img5.png'),
    'auto_confirm': b64img('img6_auto_confirm.png'),
    '使用前后': b64img('使用前后对比.png'),
}

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PBC 智能管理工作站 — 作品说明</title>
<style>
:root{
  --ey-yellow:#FFE600;
  --ey-off-white:#F6F6FA;
  --ey-white:#FFFFFF;
  --ey-gray-02:#C4C4CD;
  --ey-gray-01:#747480;
  --ey-off-black:#2E2E38;
  --ey-confident-black:#1A1A24;
  --bg:var(--ey-off-white);
  --card:var(--ey-white);
  --border:var(--ey-gray-02);
  --text:var(--ey-confident-black);
  --text2:#3f3f46;
  --text3:#71717a;
  --primary:var(--ey-off-black);
  --accent:var(--ey-yellow);
  --soft:#f4f4f5;
  --green:#16a34a;
  --red:#dc2626;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);line-height:1.75;font-size:15px}
.wrap{max-width:960px;margin:0 auto;padding:40px 24px 80px}
h1{font-size:30px;font-weight:800;letter-spacing:-0.5px;margin-bottom:6px;color:var(--text)}
h2{font-size:22px;font-weight:700;margin:44px 0 14px;padding:8px 0 8px 14px;border-left:4px solid var(--ey-yellow);background:linear-gradient(90deg,var(--ey-yellow) 0%,transparent 8%);color:var(--text)}
h3{font-size:17px;font-weight:600;margin:24px 0 10px;color:var(--ey-off-black)}
.sub{color:var(--text2);font-size:14px;margin-bottom:24px}
p{margin-bottom:14px;color:var(--text2)}
.lead{font-size:17px;color:var(--text);line-height:1.85;margin:20px 0 28px;padding:20px 22px;background:var(--card);border-left:4px solid var(--ey-yellow);border-radius:0 8px 8px 0;box-shadow:0 1px 3px rgba(0,0,0,0.06)}
.lead-note{font-size:14px;color:var(--text2);line-height:1.75;margin:-8px 0 28px;padding:14px 18px;background:var(--ey-off-white);border:1px dashed var(--border);border-radius:8px}
.tag{display:inline-block;font-size:12px;padding:2px 10px;border-radius:99px;background:var(--soft);color:var(--text2);margin-right:6px;margin-bottom:4px}
.meta-grid{display:grid;grid-template-columns:130px 1fr;gap:8px 16px;margin:20px 0;padding:20px 22px;background:var(--card);border:1px solid var(--border);border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}
.meta-grid dt{color:var(--text3);font-size:13px;font-weight:600}
.meta-grid dd{color:var(--text);font-size:14px}
.compare{width:100%;border-collapse:collapse;margin:18px 0;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--card)}
.compare th{padding:12px 14px;text-align:left;font-size:14px;font-weight:700;color:var(--card);background:var(--ey-confident-black)}
.compare td{padding:12px 14px;text-align:left;font-size:14px;border-bottom:1px solid var(--border)}
.compare td:first-child{width:42%;color:var(--text2);background:var(--ey-off-white)}
.compare td:last-child{color:var(--text)}
.compare tr:last-child td{border-bottom:none}
.shot{margin:18px 0;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--card);box-shadow:0 1px 4px rgba(0,0,0,0.05)}
.shot img{display:block;width:100%;height:auto}
.shot .cap{padding:10px 14px;font-size:13px;color:var(--text2);background:var(--ey-off-white);border-top:1px solid var(--border)}
.flow{display:flex;align-items:stretch;gap:0;margin:20px 0;flex-wrap:wrap}
.flow-step{flex:1;min-width:120px;padding:14px 12px;background:var(--card);border:1px solid var(--border);border-radius:8px;text-align:center;position:relative}
.flow-step .n{font-size:13px;font-weight:700;color:var(--ey-off-black);margin-bottom:4px}
.flow-step .t{font-size:13px;color:var(--text2)}
.flow-arrow{display:flex;align-items:center;padding:0 4px;color:var(--text3);font-size:18px}
@media(max-width:640px){.flow{flex-direction:column}.flow-arrow{transform:rotate(90deg);padding:4px 0}}
.value-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}
.value-card{padding:20px;background:var(--card);border:1px solid var(--border);border-radius:10px;border-top:3px solid var(--ey-yellow)}
.value-card .vt{font-size:15px;font-weight:700;color:var(--ey-off-black);margin-bottom:8px}
.value-card .vd{font-size:13px;color:var(--text2);line-height:1.65}
@media(max-width:640px){.value-grid{grid-template-columns:1fr}}
.future-card{padding:20px 22px;background:var(--ey-off-white);border:1px dashed var(--border);border-radius:10px;margin:18px 0}
.future-card h3{margin-top:0}
.future-card .badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:99px;background:var(--ey-yellow);color:var(--ey-confident-black);font-weight:600;margin-left:8px}
.placeholder-box{margin:18px 0;padding:40px 20px;background:var(--ey-off-white);border:2px dashed var(--border);border-radius:10px;text-align:center;color:var(--text3);font-size:14px}
.foot{margin-top:48px;padding-top:20px;border-top:1px solid var(--border);font-size:12px;color:var(--text3);text-align:center}
</style>
</head>
<body>
<div class="wrap">

<h1>PBC 智能管理工作站</h1>
<div class="sub">审计员的精力该花在判断和结论上，不是花在找文件和催文件上</div>

<p class="lead">一个本地运行的单机工作站，把 PBC 资料管理从手工台账变成自动流水线。客户照常往共享文件夹放文件，系统自动扫描并匹配 PBC 清单项，给出归档建议，审计员确认后归档。缺料提前标红，归档命名按 SOP 规范，变更记录可追溯。</p>

<p class="lead-note">AI 负责自动匹配文件和生成影响分析。关掉 AI，审计员仍可手动分类归档。扫描监听、归档命名、变更记录、状态追踪、缺料检测都不依赖 AI，照常运行。</p>

<div class="meta-grid">
  <dt>作品名称</dt><dd>PBC 智能管理工作站</dd>
  <dt>适用场景</dt><dd>审计项目 PBC 资料接收、整理、归档与缺料追踪</dd>
  <dt>主要功能</dt><dd>客户文件夹自动扫描、AI 分类归档、待归档人工确认、变更记录时间线、缺料汇报生成</dd>
  <dt>使用工具</dt><dd>基于 coding agent（AI 编程助手）+ 阿里云百炼大模型开发</dd>
  <dt>数据来源</dt><dd>客户共享文件夹（本地路径）+ PBC 清单 Excel</dd>
  <dt>运行环境</dt><dd>Windows 单机，双击即用，数据存本地</dd>
</div>

<h2>现状痛点</h2>

<p>客户对 client portal 接受度低，资料全靠手工整理加登记。整理过程极易出现遗漏与重复，回头找客户补料，专业性受质疑。归档命名缺乏统一标准，底稿复核时修改轨迹难以追溯。面对动辄几十甚至几百项的 PBC 清单，每项均需精准跟踪状态、版本与齐漏情况，传统的 Excel 模式根本无法支撑如此复杂的管理需求。</p>

<table class="compare">
<tr><th>现状（手工）</th><th>工作站</th></tr>
<tr><td>客户不愿用 client portal，资料散在邮件和网盘</td><td>客户照常往一个共享文件夹放文件，不用学新工具</td></tr>
<tr><td>人工核对清单，遗漏重复，回头找客户补</td><td>自动扫描加清单匹配，缺什么直接显示</td></tr>
<tr><td>归档命名各人一套，底稿复核难追溯</td><td>按 SOP 规范命名，变更全程留痕</td></tr>
<tr><td>缺料要临到报告期才发现，临时催</td><td>超期未提供提前标红，带影响分析</td></tr>
</table>

<h2>核心功能</h2>

<h3>一、AI 自动分类归档</h3>
<p>客户往共享文件夹放文件，watchdog 实时监听。新文件进来，AI 拿文件名、路径、内容跟 PBC 清单逐项匹配，给出归档建议和置信度。整目录归档的（比如穿行测试一整套截图）按目录整体匹配。匹配不上的标未分类，留给人工。</p>

<div class="shot">
  <img src="__IMG_待归档__" alt="待归档">
  <div class="cap">待归档：AI 给出归档建议路径和置信度，低置信度标红置顶，审计员点确认才真正归档</div>
</div>

<h3>二、待归档人工确认（HITL）</h3>
<p>AI 给建议，人拍板。每条归档建议都进待确认队列，审计员可以预览原文件、改分类、确认归档或跳过。auto_confirm 默认关闭，每条都走人工确认。AI 干匹配的活，人干判断的活。</p>

<div class="shot">
  <img src="__IMG_auto_confirm__" alt="auto_confirm 默认关闭">
  <div class="cap">auto_confirm 默认关闭，确保每条归档建议都经人工确认</div>
</div>

<h3>三、变更记录时间线</h3>
<p>客户新交了什么、AI 归了哪些档、谁改了分类、谁确认了归档，都按时间记在变更记录里。点开左侧面板一条时间线往下翻，底稿复核不用翻聊天记录。</p>

<div class="shot">
  <img src="__IMG_变更记录__" alt="变更记录">
  <div class="cap">变更记录：文件变更和操作日志按时间排列，可按类型筛选</div>
</div>

<h3>四、五个页签一条流水线</h3>
<p>待初检装的是清单里还没交的项，超期的也在里头。待归档是客户交了、AI 预分析完、等确认的。已完成是归好档的。风险分析单独把超期的挑出来。文件区左右对照看原始文件夹和归档目录两边的实际文件。从左到右走一遍，整个项目状态心里有数。</p>

<div class="shot">
  <img src="__IMG_待初检__" alt="待初检">
  <div class="cap">待初检：清单项按状态分组，超期的标红</div>
</div>

<h3>五、多项目隔离</h3>
<p>一个工作站管多个项目，每个项目有自己的 PBC 清单、客户文件夹、归档目录。切换项目数据不串，同时跟几个项目也不乱。</p>

<div class="shot">
  <img src="__IMG_项目总览__" alt="项目总览">
  <div class="cap">项目总览：多项目切换，每个项目独立隔离</div>
</div>

<h2>使用前后</h2>

<p>用之前，一个项目 PBC 清单两百多项，每项跟踪状态和文件靠 Excel 加邮件。客户交来的文件散在邮箱附件和网盘链接里，要手动下载、重命名、归档。缺什么得翻清单逐项对，经常临到报告期才发现漏了关键资料，临时催客户。</p>

<p>用之后，客户照常往共享文件夹放文件，不用学新工具。系统自动扫描匹配，归档建议出在待归档队列里，审计员逐条确认。缺料提前标红带影响分析。归档按 SOP 命名，变更记录可追溯。资料整理时间下降六到八成，省下的时间还给做判断。</p>

<div class="shot">
  <img src="__IMG_使用前后__" alt="使用前后对比">
  <div class="cap">使用前后对比：左侧手工整理，右侧工作站自动归档</div>
</div>

<h2>预期价值</h2>

<div class="value-grid">
  <div class="value-card">
    <div class="vt">效率</div>
    <div class="vd">PBC 资料整理从人均几小时一天降到自动扫描加确认几分钟。资料整理时间下降六到八成。</div>
  </div>
  <div class="value-card">
    <div class="vt">风险</div>
    <div class="vd">缺料提前发现，不再临到报告期才催。超期项带影响分析，缺什么影响什么写得清楚。</div>
  </div>
  <div class="value-card">
    <div class="vt">专业性</div>
    <div class="vd">归档命名按 SOP 规范，变更记录可追溯。底稿经得起复核。</div>
  </div>
</div>

<h2>后续拓展方向</h2>

<div class="future-card">
  <h3>风险信号卡 <span class="badge">探索中</span></h3>
  <p>清单里超期未提供的项，按一级分类聚合到风险分析页签。每张风险卡写清楚缺哪个编号、超期几天、影响哪个科目结论。这一功能目前处于初步探索阶段，影响分析内容仅供参考，不作为正式审计结论依据。后续会请审计专家校准准则引用和分析逻辑。</p>
  <div class="shot">
    <img src="__IMG_风险分析__" alt="风险分析">
    <div class="cap">风险分析：热力图按科目和实体展示最长逾期，超期项带影响分析（探索阶段，仅供参考）</div>
  </div>
  <p style="font-size:13px;color:var(--text3);margin-top:8px">注：当前版本中风险卡引用的审计准则条款尚在核实中，正式版会请审计专家校准。</p>
</div>

<h2>推广可能</h2>

<p>工作站支持多项目隔离，同部门其他审计项目直接复用，不用重新部署。本地单机版，没有 IT 部署门槛，审计员自带电脑双击就能用。PBC 清单按 SOP 列结构，换个模板能推广到年审、尽调等其他审计类型。本质上是一套资料收集整理工具，不限于特定审计场景。</p>

<div class="foot">基于 coding agent（AI 编程助手）+ 阿里云百炼大模型开发　·　本地运行　·　数据存本地</div>

</div>
</body>
</html>
"""

# 替换图片占位符
for name, b64 in IMGS.items():
    HTML = HTML.replace(f'__IMG_{name}__', b64)

out_path = os.path.join(os.path.dirname(__file__), '..', '文档', 'PBC工作站说明材料_v2.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(HTML)

size_mb = os.path.getsize(out_path) / 1024 / 1024
print(f'Done: {out_path} ({size_mb:.1f} MB)')
