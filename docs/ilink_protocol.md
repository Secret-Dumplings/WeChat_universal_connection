# 微信 iLink Bot 协议文档

> 参考官方 `@tencent-weixin/openclaw-weixin` v2.4.3 源码实现
> 源码路径：npm 包 `@tencent-weixin/openclaw-weixin` 内 `src/` 目录
> 文档版本：2026-05-12

---

## 目录

- [概述](#概述)
- [认证与会话](#认证与会话)
- [扫码登录](#扫码登录)
- [会话管理](#会话管理)
- [消息接收（长轮询）](#消息接收长轮询)
- [消息发送](#消息发送)
- [媒体文件 CDN 上传](#媒体文件-cdn-上传)
- [错误处理](#错误处理)
- [完整示例](#完整示例)

---

## 概述

### 架构

```
┌──────────────┐      ┌────────────────────────┐      ┌────────────────────┐
│   Bot 应用    │◄────►│  iLink API            │◄────►│  微信 CDN          │
│  (本项目)    │      │  ilinkai.weixin.qq.com │      │ novac2c.cdn...     │
└──────────────┘      └────────────────────────┘      └────────────────────┘
                                                    │
┌──────────────┐      ┌────────────────────────┐      │
│  微信客户端   │◄────►│  iLink Long Poll      │──────┘
│  (扫码登录)  │      │                        │
└──────────────┘      └────────────────────────┘
```

### 端点总览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/ilink/bot/get_bot_qrcode` | POST | 获取扫码登录二维码 |
| `/ilink/bot/get_qrcode_status` | GET | 轮询扫码状态 |
| `/ilink/bot/msg/notifystart` | POST | 通知服务器客户端启动 |
| `/ilink/bot/msg/notifystop` | POST | 通知服务器客户端停止 |
| `/ilink/bot/getupdates` | POST | 长轮询获取消息 |
| `/ilink/bot/sendmessage` | POST | 发送消息 |
| `/ilink/bot/getuploadurl` | POST | 获取 CDN 上传预签名 URL |

### 常量定义

```python
BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
CHANNEL_VERSION = "1.0.2"
ILINK_APP_ID = "bot"
BOT_AGENT = "OpenClaw"
TIMEOUT = 40  # 服务器长轮询约 35 秒
```

---

## 认证与会话

### Token 格式

登录成功后服务器返回的 Token 格式为：

```
ilink_bot_id:token
例如：a195ce9526a9@im.bot:06000077b8...
```

**保存时必须原样保存整个字符串（包含 ilink_bot_id: 前缀），不要拆分。**

后续所有请求的 `Authorization` 头使用完整格式：

```
Authorization: Bearer a195ce9526a9@im.bot:06000077b8...
```

**常见错误**：`Authorization` 只传 token 部分（冒号后）会导致 `errcode=-14 session timeout`。

### HTTP 请求头

所有带认证的请求必须包含以下头部：

```http
Content-Type: application/json
AuthorizationType: ilink_bot_token
Authorization: Bearer <完整token>
iLink-App-Id: bot
X-WECHAT-UIN: <base64_random_uint32>
```

`X-WECHAT-UIN` 生成方式：随机 uint32 → 十进制字符串 → base64 编码

```python
import secrets, base64

def random_uin() -> str:
    val = secrets.randbelow(2**32)
    return base64.b64encode(str(val).encode()).decode()
```

### base_info

所有 POST 请求 body 中必须包含 `base_info` 字段：

```json
{
  "base_info": {
    "channel_version": "1.0.2",
    "bot_agent": "OpenClaw"
  }
}
```

---

## 扫码登录

### 获取二维码

**必须是 POST 请求，body 必须包含 `local_token_list`。**

```http
POST https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3
Content-Type: application/json

{
  "local_token_list": []
}
```

`local_token_list` 传入已有 token 列表，服务器据此判断是否已绑定。
若该设备已绑定同一账号，返回的 `qrcode_img_content` 会不同（无需重复绑定）。

请求头中**不需要**认证头。

返回：
- `qrcode`：二维码 UUID（短字符串）
- `qrcode_img_content`：完整的扫码 URL，**作为二维码内容**（不是 `qrcode` 本身）

### 轮询扫码状态

```http
GET https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status?qrcode=<qrcode_uuid>
```

**状态码是字符串，不是整数！**

| status | 含义 |
|--------|------|
| `"wait"` | 等待扫码 |
| `"scaned"` | 已扫码，等待手机确认 |
| `"confirmed"` | 登录成功，返回 bot_token |
| `"expired"` | 二维码过期，需重新获取 |
| `"need_verifycode"` | 需要验证码 |
| `"binded_redirect"` | 已连接过此实例，无需重复连接 |

`confirmed` 时的返回：

```json
{
  "ret": 0,
  "status": "confirmed",
  "bot_token": "a195ce9526a9@im.bot:06000077b8...",
  "ilink_bot_id": "a195ce9526a9@im.bot",
  "ilink_user_id": "xxx@im.wechat",
  "baseurl": "https://ilinkai.weixin.qq.com"
}
```

服务器可能返回新的 `baseurl`，应优先更新 `base_url`。

---

## 会话管理

### notify_start

**必须**在每次启动监听前调用，通知服务器客户端上线。

```http
POST https://ilinkai.weixin.qq.com/ilink/bot/msg/notifystart
Content-Type: application/json
Authorization: Bearer <token>
iLink-App-Id: bot

{
  "base_info": {"channel_version": "1.0.2", "bot_agent": "OpenClaw"}
}
```

### notify_stop

客户端退出时调用，通知服务器客户端下线。

```http
POST https://ilinkai.weixin.qq.com/ilink/bot/msg/notifystop
```

### 会话超时与错误码 -14

调用 `get_updates` 时若返回 `errcode=-14`，表示会话已过期：

1. **立即停止长轮询**，不要继续重试
2. 显示"会话过期，请重新登录"提示
3. 等待用户重新扫码
4. 登录成功后重新调用 `notify_start`

---

## 消息接收（长轮询）

### get_updates 请求

```http
POST https://ilinkai.weixin.qq.com/ilink/bot/getupdates
Content-Type: application/json
Authorization: Bearer <token>
iLink-App-Id: bot
X-WECHAT-UIN: <base64_random_uint32>

{
  "get_updates_buf": "",
  "base_info": {"channel_version": "1.0.2", "bot_agent": "OpenClaw"}
}
```

- `get_updates_buf`：初始为空字符串 `""`，后续必须原样回传服务器返回的值
- 超时由服务器控制，约 35 秒，无消息时返回空响应
- 请求超时时间建议设 40-50 秒

### 消息结构

```json
{
  "ret": 0,
  "get_updates_buf": "opaque_binary_or_empty_string",
  "msgs": [
    {
      "msg_id": "xxx",
      "from_user_id": "xxx@im.wechat",
      "to_user_id": "xxx@im.bot",
      "message_type": 1,
      "message_state": 2,
      "context_token": "xxx",
      "create_time_ms": 1747036800000,
      "item_list": [
        {"type": 1, "text_item": {"text": "消息内容"}}
      ]
    }
  ]
}
```

**注意**：
- 消息数组字段名是 `msgs`，不是 `messages`
- 文本内容在 `item_list[].text_item.text`，不是 `text_item.content`
- `get_updates_buf` 是 opaque 字符串，**当成 blob 使用，不要解析**

### MessageItem 类型

| type | 内容类型 | 数据字段 |
|------|----------|----------|
| 1 | 文本 | `text_item.text` |
| 2 | 图片 | `image_item.media` |
| 3 | 语音 | `voice_item.media` + `voice_item.text`（转文字） |
| 4 | 文件 | `file_item` |
| 5 | 视频 | `video_item` |

### 断点续传

```python
cursor = None
while True:
    msgs, cursor = client.get_updates(cursor)
    for msg in msgs:
        process(msg)
    # cursor 必须原样保存，程序重启后仍可用
```

---

## 消息发送

### 发送文本

```http
POST https://ilinkai.weixin.qq.com/ilink/bot/sendmessage

{
  "msg": {
    "from_user_id": "",
    "to_user_id": "用户ID@im.wechat",
    "client_id": "py-<uuid>",
    "message_type": 2,
    "message_state": 2,
    "context_token": "<从入站消息获取>",
    "item_list": [{"type": 1, "text_item": {"text": "你好"}}]
  },
  "base_info": {"channel_version": "1.0.2", "bot_agent": "OpenClaw"}
}
```

| 字段 | 值 | 说明 |
|------|----|------|
| `message_type` | 2 | 2=BOT发送, 1=用户发送 |
| `message_state` | 2 | 0=NEW, 1=GENERATING, 2=FINISH |
| `client_id` | `py-<uuid>` | 客户端生成的唯一ID，用于去重 |
| `context_token` | string | **必须**从入站消息中获取并原样带回 |

### 发送图片

流程：获取上传地址 → AES加密 → CDN上传 → sendmessage引用。

发送图片时 `item_list` 结构：

```json
{
  "type": 2,
  "image_item": {
    "media": {
      "encrypt_query_param": "<CDN返回的下载参数>",
      "aes_key": "<hex字符串的base64>",
      "encrypt_type": 1,
      "mid_size": <加密后大小>
    },
    "thumb_media": {
      "encrypt_query_param": "<缩略图CDN返回的下载参数>",
      "aes_key": "<缩略图hex的base64>",
      "encrypt_type": 1
    }
  }
}
```

### 发送文件/语音

media_type 映射：

| 扩展名 | media_type |
|--------|-------------|
| .mp3 .wav .ogg .aac | 4（语音） |
| .jpg .png .gif | 1（图片） |
| .mp4 .avi .mov | 2（视频） |
| 其他 | 4（文件） |

发送文件时 `item_list` 结构：

```json
{
  "type": 4,
  "file_item": {
    "media": {
      "encrypt_query_param": "<CDN返回的下载参数>",
      "aes_key": "<hex字符串的base64>",
      "encrypt_type": 1
    },
    "file_name": "文档.pdf",
    "len": "<原始文件大小（字符串）>"
  }
}
```

### 快捷回复

```python
def reply_to_message(self, msg, text: str) -> dict:
    return self.send_text(msg["from_user_id"], text, msg["context_token"])
```

---

## 媒体文件 CDN 上传

### 获取上传地址

```http
POST https://ilinkai.weixin.qq.com/ilink/bot/getuploadurl

{
  "filekey": "img_abc123def456",
  "media_type": 1,
  "to_user_id": "xxx@im.wechat",
  "rawsize": 12345,
  "rawfilemd5": "md5_of_raw_file",
  "filesize": 12368,
  "aeskey": "<hex字符串，32字符>",
  "thumb_rawsize": 4567,
  "thumb_rawfilemd5": "md5_of_thumb",
  "thumb_filesize": 4576,
  "no_need_thumb": false,
  "base_info": {"channel_version": "1.0.2", "bot_agent": "OpenClaw"}
}
```

**参数名是 `aeskey`（hex字符串），不是 `aeskey_hex`！**

返回：
```json
{
  "ret": 0,
  "upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?...",
  "upload_param": "encrypted_param_string",
  "thumb_upload_full_url": "https://.../upload?..._thumb",
  "thumb_upload_param": "encrypted_thumb_param_string"
}
```

**优先使用 `upload_full_url`**（完整URL），如果未返回再用 `upload_param` 拼接。

拼接公式（兜底）：
```
https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param=<upload_param>&filekey=<filekey>
```

### AES 加密

算法：AES-128-ECB + PKCS7 填充

```python
from Crypto.Cipher import AES

def aes_encrypt(data: bytes, key: bytes) -> bytes:
    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len] * pad_len)
    return AES.new(key, AES.MODE_ECB).encrypt(padded)

def aes_padded_size(plaintext_size: int) -> int:
    return ((plaintext_size // 16) + 1) * 16
```

生成 AES 密钥：
```python
aes_key = os.urandom(16)
aeskey_hex = aes_key.hex()  # 32字符hex字符串
```

**图片发送时 aes_key 的 base64 编码方式**：
```
hex字符串 → UTF-8编码 → base64编码
例如: base64.b64encode("0123abcd...".encode("utf-8"))
```

### 上传到 CDN

```python
def upload_cdn(upload_url: str, encrypted_data: bytes) -> Optional[str]:
    r = subprocess.run(
        ["curl", "-s", "-i", "-X", "POST",
         "-H", "Content-Type: application/octet-stream",
         "--max-time", "60",
         "-d", "@-", upload_url],
        input=encrypted_data, capture_output=True,
        start_new_session=True,
    )
    raw = r.stdout.decode("utf-8", errors="replace")
    # HTTP响应格式: HTTP/1.1 200 OK\r\nheaders\r\n\r\nbody
    idx = raw.find("\r\n\r\n")
    if idx == -1:
        return None
    header_section = raw[:idx]
    for line in header_section.splitlines():
        if line.lower().startswith("x-encrypted-param:"):
            return line.split(":", 1)[1].strip()
    return None
```

- 请求方法：**POST**，不是 PUT
- 上传后服务器在 HTTP 响应头 `x-encrypted-param` 中返回下载参数
- 如上传失败，最多重试 3 次

---

## 错误处理

### 常见错误码

| ret | errcode | 说明 | 处理 |
|-----|---------|------|------|
| 0 | 0 | 成功 | - |
| ≠0 | - | 请求级错误 | 检查 errmsg |
| - | -14 | 会话过期 | 重新登录 |
| - | -1 | 参数错误 | 检查请求参数 |
| - | -2 | Token无效 | 重新登录 |

### get_updates 错误处理

```python
def get_updates(self, cursor=None):
    ...
    ret = data.get("ret", 0) if data else 0
    errcode = data.get("errcode", 0) if data else 0
    if ret != 0 or errcode != 0:
        errmsg = data.get("errmsg", "")
        if errcode == -14 or ret == -14:
            raise SessionExpiredError("会话过期，请重新登录！")
```

---

## 完整示例

### Python ILinkClient 最小实现

```python
import json, time, uuid, base64, hashlib, secrets, subprocess
from pathlib import Path

BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
CHANNEL_VERSION = "1.0.2"
ILINK_APP_ID = "bot"
BOT_AGENT = "OpenClaw"
TIMEOUT = 40

def random_uin() -> str:
    val = secrets.randbelow(2**32)
    return base64.b64encode(str(val).encode()).decode()

def _curl(url, method="GET", headers=None, body=None, timeout=30) -> dict:
    h_args = []
    for k, v in (headers or {}).items():
        h_args += ["-H", f"{k}: {v}"]
    cmd = ["curl", "-s", "--max-time", str(timeout)]
    if method != "GET":
        cmd += ["-X", method]
    cmd += [url] + h_args
    try:
        r = subprocess.run(cmd, input=body, capture_output=True, start_new_session=True)
    except Exception:
        return {}
    raw = r.stdout
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

class ILinkClient:
    def __init__(self, bot_token=None):
        self.base_url = BASE_URL
        self._data_dir = Path.home() / ".wechat_mcp"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._token_file = self._data_dir / "bot_token.txt"
        self.bot_token = bot_token or self._load_token()

    def _load_token(self):
        if self._token_file.exists():
            return self._token_file.read_text().strip()
        return None

    def _save_token(self, token: str):
        self._token_file.write_text(token)
        self.bot_token = token

    def _headers(self, need_auth=True) -> dict:
        h = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "iLink-App-Id": ILINK_APP_ID,
            "X-WECHAT-UIN": random_uin(),
        }
        if need_auth and self.bot_token:
            h["Authorization"] = f"Bearer {self.bot_token}"
        return h

    def _build_base_info(self) -> dict:
        return {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}

    def notify_start(self) -> dict:
        url = f"{self.base_url}/ilink/bot/msg/notifystart"
        payload = {"base_info": self._build_base_info()}
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=10)

    def notify_stop(self) -> dict:
        url = f"{self.base_url}/ilink/bot/msg/notifystop"
        payload = {"base_info": self._build_base_info()}
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=10)

    def get_updates(self, cursor=None):
        url = f"{self.base_url}/ilink/bot/getupdates"
        payload = {"get_updates_buf": cursor or "", "base_info": self._build_base_info()}
        body = json.dumps(payload, ensure_ascii=False).encode()
        data = _curl(url, "POST", self._headers(), body, timeout=TIMEOUT + 15)
        msgs = []
        for msg in data.get("msgs", []):
            msgs.append({
                "from_user_id": msg.get("from_user_id", ""),
                "to_user_id": msg.get("to_user_id", ""),
                "context_token": msg.get("context_token", ""),
                "msg_id": str(msg.get("msg_id", "")),
                "msg_type": msg.get("message_type", 0),
                "items": msg.get("item_list", []),
            })
        return msgs, data.get("get_updates_buf") or None

    def send_text(self, to_user_id: str, text: str, context_token: str) -> dict:
        url = f"{self.base_url}/ilink/bot/sendmessage"
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"py-{uuid.uuid4()}",
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
            "base_info": self._build_base_info(),
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=30)

    def reply_to_message(self, msg, text: str) -> dict:
        return self.send_text(msg["from_user_id"], text, msg["context_token"])
```

### 消息监听循环

```python
client = ILinkClient()
client.ensure_logged_in()
client.notify_start()  # 重要：启动前必须调用

cursor = None
while True:
    try:
        msgs, cursor = client.get_updates(cursor)
        for msg in msgs:
            print(f"收到: {msg['from_user_id']}: {msg['items']}")
            # 提取文本
            for item in msg["items"]:
                if item.get("type") == 1:
                    text = item.get("text_item", {}).get("text", "")
                    client.reply_to_message(msg, f"收到: {text}")
    except KeyboardInterrupt:
        client.notify_stop()
        break
    except Exception as e:
        print(f"错误: {e}")
        time.sleep(3)
```

---

## 参考资料

| 资源 | 说明 |
|------|------|
| 官方 OpenClaw 插件 | `@tencent-weixin/openclaw-weixin` (npm) |
| OpenClaw 官方文档 | https://docs.openclaw.ai/install |
| 本项目实现 | `wechat_mcp/ilink_client.py` |
