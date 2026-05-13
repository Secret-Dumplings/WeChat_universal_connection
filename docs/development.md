# 二次开发指南

> 如何基于本项目扩展定制微信 Bot 功能

---

## 目录

- [添加新消息处理器](#添加新消息处理器)
- [添加新发送类型](#添加新发送类型)
- [扩展 MCP 工具](#扩展-mcp-工具)
- [持久化联系人缓存](#持久化联系人缓存)
- [多 Bot 管理](#多-bot-管理)
- [调试技巧](#调试技巧)

---

## 添加新消息处理器

在 `main.py` 的 `cmd_listen` 中添加自定义逻辑：

```python
def cmd_listen(args):
    from wechat_mcp.ilink_client import ILinkClient
    client = ILinkClient()
    client.ensure_logged_in()
    client.notify_start()
    cursor = None

    HANDLERS = {
        # msg_type: handler function
        1: handle_text,       # 文本
        2: handle_image,      # 图片
        3: handle_voice,      # 语音
    }

    try:
        while True:
            msgs, cursor = client.get_updates(cursor)
            for m in msgs:
                handler = HANDLERS.get(m.msg_type)
                if handler:
                    handler(client, m)
                else:
                    print(f"未知类型: {m.msg_type}")
            if args.once:
                break
    except KeyboardInterrupt:
        client.notify_stop()

def handle_text(client, msg):
    text = msg.text or ""
    if "help" in text.lower():
        client.reply_to_message(msg, "可用命令: help / ping / ...")
    elif "ping" in text.lower():
        client.reply_to_message(msg, "pong")
    else:
        # AI 处理（接入 LLM）
        ai_response = call_llm(text)
        client.reply_to_message(msg, ai_response)

def handle_image(client, msg):
    print(f"收到图片 from {msg.from_user_id}")
    # 下载并处理图片
    # media_url = extract_image_url(msg)
    # image_data = download(media_url)
    # result = call_vision_model(image_data)

def handle_voice(client, msg):
    print(f"收到语音 from {msg.from_user_id}")
    # 语音已在 msg.text 中提供转文字内容
    text = msg.text or ""
    # 调用语音识别结果
```

---

## 添加新发送类型

### 发送视频

在 `ilink_client.py` 中添加方法：

```python
def send_video(self, to_user_id: str, context_token: str, video_path: str) -> dict:
    """
    发送视频：本地读取 → AES-128-ECB 加密 → CDN 上传 → 引用发送
    media_type=2
    """
    import os, base64

    with open(video_path, "rb") as f:
        raw_data = f.read()

    raw_size = len(raw_data)
    raw_md5 = self._file_md5(raw_data)

    aes_key = os.urandom(16)
    aeskey_hex = aes_key.hex()
    enc_data = self._aes_encrypt(raw_data, aes_key)
    enc_size = len(enc_data)

    # 视频不使用缩略图
    filekey = f"vid_{uuid.uuid4().hex[:12]}"
    result = self._get_upload_url(
        filekey=filekey, media_type=2, to_user_id=to_user_id,
        raw_size=raw_size, raw_md5=raw_md5, enc_size=enc_size,
        aeskey=aeskey_hex,
    )

    cdn_url = result.get("upload_full_url") or ""
    if not cdn_url:
        up = result.get("upload_param", "")
        cdn_url = f"{CDN_BASE_URL}/upload?encrypted_query_param={up}&filekey={filekey}"
    enc_param = self._upload_cdn(cdn_url, enc_data)
    if not enc_param:
        raise Exception("CDN 视频上传失败")

    aes_key_base64 = base64.b64encode(aeskey_hex.encode("utf-8")).decode("utf-8")

    url = f"{self.base_url}/ilink/bot/sendmessage"
    payload = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": f"py-{uuid.uuid4()}",
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{
                "type": 5,
                "video_item": {
                    "media": {
                        "encrypt_query_param": enc_param,
                        "aes_key": aes_key_base64,
                        "encrypt_type": 1,
                    },
                    "file_name": os.path.basename(video_path),
                    "len": str(raw_size),
                },
            }],
        },
        "base_info": self._build_base_info(),
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    return _curl(url, "POST", self._headers(), body, timeout=60)  # 视频较大，超时 60s
```

---

## 扩展 MCP 工具

在 `mcp_server.py` 中添加新工具：

### Step 1：在 TOOLS 列表中添加定义

```python
TOOLS = [
    # ... 现有工具 ...
    {
        "name": "wechat_send_video",
        "description": "向指定用户发送视频（支持 mp4/avi/mov）",
        "inputSchema": {
            "type": "object",
            "required": ["to_user_id", "context_token", "video_path"],
            "properties": {
                "to_user_id": {
                    "type": "string",
                    "description": "目标用户 ID",
                },
                "context_token": {
                    "type": "string",
                    "description": "上下文 Token",
                },
                "video_path": {
                    "type": "string",
                    "description": "视频路径（本地路径或 HTTP URL）",
                },
            },
        },
    },
]
```

### Step 2：添加处理器

```python
def _handle_send_video(params: dict) -> dict:
    client = get_client()
    to_user = params["to_user_id"]
    token = params["context_token"]
    path = params["video_path"]
    try:
        if path.startswith("http://") or path.startswith("https://"):
            import requests, tempfile
            r = requests.get(path, timeout=60)
            r.raise_for_status()
            ext = path.split("?")[0].split(".")[-1]
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                f.write(r.content)
                path = f.name
        result = client.send_video(to_user, token, path)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### Step 3：注册到 TOOL_HANDLERS

```python
TOOL_HANDLERS = {
    # ... 现有处理器 ...
    "wechat_send_video": _handle_send_video,
}
```

---

## 持久化联系人缓存

在消息处理中缓存联系人信息，避免每次都依赖 `context_token`：

```python
# contacts.py
from pathlib import Path
import json

CONTACTS_FILE = Path.home() / ".wechat_mcp" / "contacts.json"

def load_contacts() -> dict:
    if CONTACTS_FILE.exists():
        return json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    return {}

def save_contact(user_id: str, context_token: str, last_text: str = ""):
    contacts = load_contacts()
    contacts[user_id] = {
        "context_token": context_token,
        "last_text": last_text,
        "last_updated": str(Path(__file__).stat().st_mtime),
    }
    CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(contacts, ensure_ascii=False, indent=2), encoding="utf-8")

def get_contact(user_id: str) -> dict | None:
    return load_contacts().get(user_id)
```

使用：

```python
def handle_text(client, msg):
    # 缓存联系人
    save_contact(msg.from_user_id, msg.context_token, msg.text or "")

    # 如果之前有缓存的 context_token（即使 msg 已处理过也可使用）
    contact = get_contact(msg.from_user_id)
    if contact:
        ctx = contact["context_token"]
        # 回复
```

---

## 多 Bot 管理

支持同时管理多个微信账号（多个 Bot Token）：

```python
# multi_bot.py
from pathlib import Path
from wechat_mcp.ilink_client import ILinkClient
import json

BOT_DIR = Path.home() / ".wechat_mcp" / "bots"
BOT_DIR.mkdir(parents=True, exist_ok=True)

class MultiBotManager:
    def __init__(self):
        self.bots = {}
        self._load_index()

    def _load_index(self):
        idx_file = BOT_DIR / "index.json"
        if idx_file.exists():
            index = json.loads(idx_file.read_text())
        else:
            index = {}
        for bot_id, info in index.items():
            token_file = BOT_DIR / f"{bot_id}.token"
            if token_file.exists():
                token = token_file.read_text().strip()
                self.bots[bot_id] = ILinkClient(bot_token=token)

    def add_bot(self, name: str, bot_token: str = None) -> ILinkClient:
        client = ILinkClient(bot_token=bot_token)
        self._save_bot(name, client.bot_token)
        self.bots[name] = client
        return client

    def _save_bot(self, name: str, token: str):
        BOT_DIR.mkdir(parents=True, exist_ok=True)
        (BOT_DIR / f"{name}.token").write_text(token)
        index = self._load_index()
        index[name] = {"token_file": f"{name}.token"}
        (BOT_DIR / "index.json").write_text(json.dumps(index))

    def get_bot(self, name: str) -> ILinkClient | None:
        return self.bots.get(name)

    def list_bots(self) -> list[str]:
        return list(self.bots.keys())
```

---

## 调试技巧

### 查看完整 HTTP 请求/响应

```python
import logging
logging.getLogger("wechat_mcp").setLevel(logging.DEBUG)
```

### 打印 Token 信息

```python
from wechat_mcp.ilink_client import ILinkClient
client = ILinkClient()
print(f"Token: {client.bot_token}")
print(f"Token 长度: {len(client.bot_token) if client.bot_token else 0}")
```

### 模拟发送消息

```python
# 直接调用 send_text，跳过消息接收
from wechat_mcp.ilink_client import ILinkClient
client = ILinkClient()
client.ensure_logged_in()

# 从 contacts.json 读取联系人
import json
contacts = json.loads(Path.home().joinpath(".wechat_mcp/contacts.json").read_text())
for user_id, info in contacts.items():
    ctx = info["context_token"]
    client.send_text(user_id, "测试广播消息", ctx)
```

### 导出协议流量

```python
import subprocess, json

# 打印 curl 命令，方便用命令行调试
def debug_headers(client):
    h = client._headers()
    for k, v in h.items():
        print(f'-H "{k}: {v}"')

client = ILinkClient()
debug_headers(client)
# 输出：
# -H "Content-Type: application/json"
# -H "AuthorizationType: ilink_bot_token"
# -H "iLink-App-Id: bot"
# -H "X-WECHAT-UIN: ..."
# -H "Authorization: Bearer ..."
```

### 绕过 iLink 直接测试 CDN 上传

```bash
# 用 curl 验证 CDN URL 是否有效
curl -v -X POST \
  -H "Content-Type: application/octet-stream" \
  -d "@encrypted.bin" \
  "https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param=xxx&filekey=xxx"
```

---

## 添加依赖

新功能需要额外依赖时，更新 `pyproject.toml`：

```toml
[project]
dependencies = [
    # ... 现有依赖 ...
    "openai>=1.0.0",    # AI 处理
    "pillow>=10.0.0",   # 图片处理
]
```

安装：
```bash
uv pip install -e ".[dev]"
```