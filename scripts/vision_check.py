"""
视觉诊断助手：用百炼 qwen3-vl-plus 读取本地截图并回答问题。
用法：
  python scripts/vision_check.py <截图路径> "你的问题"
  python scripts/vision_check.py screenshots/pending_archive_tab.png "这个列表用的是表格还是卡片？有什么布局问题？"
"""
import base64, json, sys
from pathlib import Path
import httpx

def ask_vision(image_path: str, question: str, max_tokens: int = 500) -> str:
    cfg = json.loads(Path("D:/AgentProjects/IpoPBC/config/api_config.json").read_text(encoding="utf-8"))
    api_key = cfg["bailian"]["api_key"]
    base_url = cfg["bailian"]["base_url"]
    model = cfg.get("ai_models", {}).get("model_vision", "qwen3-vl-plus")

    img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]}],
            "max_tokens": max_tokens,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        return f"ERROR: {data['error']}"
    return data["choices"][0]["message"]["content"]

def screenshot_and_ask(page_url: str, question: str, output_path: str = "screenshots/_vision_tmp.png") -> str:
    """puppeteer 截图 + 视觉模型分析，一步到位"""
    import subprocess, os
    env = os.environ.copy()
    env["NODE_PATH"] = "C:/Users/EDY/.workbuddy/binaries/node/workspace/node_modules"
    node = "C:/Users/EDY/.workbuddy/binaries/node/versions/22.12.0/node.exe"
    script = f"""
const puppeteer = require('puppeteer-core');
(async () => {{
  const browser = await puppeteer.launch({{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:'new',args:['--no-sandbox','--disable-gpu']}});
  const page = await browser.newPage();
  await page.setViewport({{width:1440,height:900}});
  await page.goto('{page_url}',{{waitUntil:'networkidle2',timeout:30000}});
  await page.evaluate(() => {{ localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo'); }});
  await page.reload({{waitUntil:'networkidle2',timeout:30000}});
  await new Promise(r => setTimeout(r, 4000));
  await page.screenshot({{path:'{output_path.replace(chr(92),'/')}'}});
  await browser.close();
}})();
"""
    result = subprocess.run([node, "-e", script], env=env, capture_output=True, text=True, timeout=45)
    if not Path(output_path).exists():
        return f"截图失败: {result.stderr}"
    return ask_vision(output_path, question)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python scripts/vision_check.py <截图路径> <问题>")
        sys.exit(1)
    answer = ask_vision(sys.argv[1], sys.argv[2])
    print(answer)
