"""视觉模型测试：用百炼 qwen3-vl-plus 读取本地截图"""
import base64, json, sys
from pathlib import Path

import httpx

cfg = json.loads(Path("D:/AgentProjects/IpoPBC/config/api_config.json").read_text(encoding="utf-8"))
api_key = cfg["bailian"]["api_key"]
base_url = cfg["bailian"]["base_url"]

img_path = "D:/AgentProjects/IpoPBC/screenshots/pending_archive_tab.png"
img_b64 = base64.b64encode(Path(img_path).read_bytes()).decode()

resp = httpx.post(
    f"{base_url}/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": "qwen3-vl-plus",
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "这张截图顶部有一条黄色左边框的横条。请逐字念出横条上的所有文字，从左到右。"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
            ]}
        ],
        "max_tokens": 200,
    },
    timeout=30,
)
data = resp.json()
if "error" in data:
    print("ERROR:", data["error"])
else:
    print("OK:", data["choices"][0]["message"]["content"])
