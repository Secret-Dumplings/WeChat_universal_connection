# API 参考

> Python API 完整参考手册，基于 `wechat_mcp.ilink_client.ILinkClient`

---

## 目录

- [ILinkClient](#ilinkclient)
  - [构造函数](#ilinkclient__init__)
  - [登录相关](#登录相关)
  - [消息接收](#消息接收)
  - [消息发送](#消息发送)
  - [会话管理](#会话管理)
- [ReceivedMessage](#receivedmessage)
- [常量定义](#常量定义)

---

## ILinkClient

```python
from wechat_mcp.ilink_client import ILinkClient, ReceivedMessage

client = ILinkClient()                    # 自动加载本地 token
client = ILinkClient(bot_token="...")    # 指定 token
```

### `ILinkClient.__init__`

```python
def __init__(
    self,
    bot_token: Optional[str] = None,
    data_dir: Optional[Path] = None,
) -> None
```

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bot_token` | `str` | `None` | 指定 Bot Token，为 `None` 时自动从 `~/.wechat_mcp/bot_token.txt` 加载 |
| `data_dir` | `Path` | `~/.wechat_mcp` | 数据目录，存放 token 和二维码图片 |

**属性**

| 属性 | 类型 | 说明 |
|------|------|------|
| `bot_token` | `str \| None` | 当前加载的 Bot Token |
| `base_url` | `str` | 当前使用的 API 基础 URL |

---

### 登录相关

#### `ILinkClient.get_qrcode`

```python
def get_qrcode(self, bot_type: int = 3) -> tuple[str, str]
```

获取登录二维码。

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bot_type` | `int` | `3` | Bot 类型，固定传 `3` |

**返回** `(qrcode_uuid: str, qrcode_url: str)`
- `qrcode`：二维码 UUID（短字符串）
- `qrcode_url`：完整的扫码 URL，**作为二维码内容渲染**（不是 `qrcode`）

```python
qr_uuid, qr_url = client.get_qrcode()
print(f"扫码链接: {qr_url}")
```

---

#### `ILinkClient.show_qrcode`

```python
def show_qrcode(self, qrcode_token: str, qrcode_url: str) -> None
```

在终端展示 ASCII 二维码，并保存 PNG 到数据目录。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `qrcode_token` | `str` | 二维码 UUID |
| `qrcode_url` | `str` | 扫码 URL（作为二维码内容） |

---

#### `ILinkClient.poll_qrcode_status`

```python
def poll_qrcode_status(self, qrcode_token: str) -> Optional[str]
```

轮询扫码状态，**阻塞**，直到扫码完成或异常。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `qrcode_token` | `str` | 二维码 UUID |

**返回**
- 成功：`bot_token` 字符串（如 `"a195ce9526a9@im.bot:060000..."`）
- 失败：`None`（已绑定 / 二维码过期等）

**状态码**

| status | 含义 |
|--------|------|
| `"wait"` | 等待扫码 |
| `"scaned"` | 已扫码，等待手机确认 |
| `"confirmed"` | 登录成功，返回 token |
| `"expired"` | 二维码过期，自动重新获取并继续轮询 |
| `"binded_redirect"` | 已连接过此实例，无需重复连接 |

```python
token = client.poll_qrcode_status(uuid)
if token:
    client._save_token(token)
```

---

#### `ILinkClient.login`

```python
def login(self) -> str
```

完整扫码登录流程：获取二维码 → 终端展示 → 轮询状态 → 保存 Token。

**返回**：成功返回 `bot_token`，失败返回空字符串 `""`。

**示例**

```python
token = client.login()
if token:
    print(f"登录成功，Token 已保存")
```

---

#### `ILinkClient.ensure_logged_in`

```python
def ensure_logged_in(self) -> None
```

如果未登录，自动调用 `login()` 触发扫码流程。

```python
client.ensure_logged_in()
```

---

### 会话管理

#### `ILinkClient.notify_start`

```python
def notify_start(self) -> dict
```

通知服务器客户端启动上线。在 `get_updates` 之前调用。

**返回**：API 响应 dict，通常 `{"ret": 0}`

```python
client.ensure_logged_in()
client.notify_start()
```

---

#### `ILinkClient.notify_stop`

```python
def notify_stop(self) -> dict
```

通知服务器客户端停止下线。退出监听前调用。

**返回**：API 响应 dict，通常 `{"ret": 0}`

```python
try:
    client.notify_stop()
except Exception:
    pass
```

---

### 消息接收

#### `ILinkClient.get_updates`

```python
def get_updates(self, cursor: Optional[str] = None) -> tuple[list[ReceivedMessage], Optional[str]]
```

长轮询获取消息。服务器无消息时约 35 秒返回，有消息立即返回。

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cursor` | `str \| None` | `None` | 首次 `None`，后续传上次的 `get_updates_buf` |

**返回** `(messages: list[ReceivedMessage], next_cursor: Optional[str])`
- `messages`：收到的消息列表
- `next_cursor`：下次调用要传的游标（`get_updates_buf`）

**异常处理**

收到 `errcode=-14`（会话过期）时函数正常返回，不抛异常，但会在日志输出错误。调用方应检查：

```python
msgs, cursor = client.get_updates(cursor)
# 检查是否有过期错误
if client.bot_token is None:
    print("会话已过期")
```

```python
cursor = None
while True:
    msgs, cursor = client.get_updates(cursor)
    for msg in msgs:
        print(f"{msg.from_user_id}: {msg.text}")
```

---

### 消息发送

#### `ILinkClient.send_text`

```python
def send_text(self, to_user_id: str, text: str, context_token: str) -> dict
```

发送文字消息。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `to_user_id` | `str` | 目标用户 ID（格式如 `o9cq800xxx@im.wechat`） |
| `text` | `str` | 文字内容 |
| `context_token` | `str` | 上下文 Token（**必须**从入站消息获取并原样传递） |

**返回**：API 响应 dict

```python
result = client.send_text(
    to_user_id="o9cq800xxx@im.wechat",
    text="你好！",
    context_token="从入站消息获取的token",
)
print(result)
```

---

#### `ILinkClient.send_image`

```python
def send_image(self, to_user_id: str, context_token: str, image_path: str) -> dict
```

发送图片（本地文件）。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `to_user_id` | `str` | 目标用户 ID |
| `context_token` | `str` | 上下文 Token |
| `image_path` | `str` | 图片文件路径（.jpg/.png/.gif 等） |

**流程**：本地读取 → AES-128-ECB 加密 → CDN 上传 → sendmessage 引用。

```python
result = client.send_image(
    to_user_id="o9cq800xxx@im.wechat",
    context_token="从入站消息获取的token",
    image_path="./photo.jpg",
)
```

---

#### `ILinkClient.send_file`

```python
def send_file(self, to_user_id: str, context_token: str, file_path: str) -> dict
```

发送文件/音频。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `to_user_id` | `str` | 目标用户 ID |
| `context_token` | `str` | 上下文 Token |
| `file_path` | `str` | 文件路径（.mp3/.wav/.pdf 等） |

**media_type 自动映射**

| 扩展名 | media_type |
|--------|-------------|
| `.mp3 .wav .ogg .aac` | 4（语音） |
| `.jpg .jpeg .png .gif` | 1（图片） |
| `.mp4 .avi .mov` | 2（视频） |
| 其他 | 4（文件） |

```python
result = client.send_file(
    to_user_id="o9cq800xxx@im.wechat",
    context_token="从入站消息获取的token",
    file_path="./audio.mp3",
)
```

---

### 快捷回复

#### `ILinkClient.reply_to_message`

```python
def reply_to_message(self, msg: ReceivedMessage, text: str) -> dict
```

快捷回复：直接使用入站消息的 `from_user_id` 和 `context_token` 回复。

```python
msgs, cursor = client.get_updates(cursor)
for m in msgs:
    if m.text:
        client.reply_to_message(m, f"收到: {m.text}")
```

#### `ILinkClient.reply_image_to_message`

```python
def reply_image_to_message(self, msg: ReceivedMessage, image_path: str) -> dict
```

快捷回复图片。

#### `ILinkClient.reply_file_to_message`

```python
def reply_file_to_message(self, msg: ReceivedMessage, file_path: str) -> dict
```

快捷回复文件。

---

## ReceivedMessage

```python
from wechat_mcp.ilink_client import ReceivedMessage
```

收到的消息 dataclass。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `from_user_id` | `str` | 发送者用户 ID（`xxx@im.wechat`） |
| `to_user_id` | `str` | 接收者 Bot ID（`xxx@im.bot`） |
| `context_token` | `str` | 上下文 Token，回复时必须原样带回 |
| `msg_id` | `str` | 消息 ID |
| `msg_type` | `int` | 消息类型：1=用户文本, 2=用户图片等 |
| `items` | `list[dict]` | 消息内容列表（`item_list`） |
| `raw` | `dict` | 原始消息 dict |

### 属性方法

#### `ReceivedMessage.text` → `str | None`

从 `items` 中提取可读文本：

- `type=1`：返回 `text_item.text`
- `type=3`：返回 `"[语音] 转文字内容"` 或 `"[语音]"`
- 其他：返回 `None`

```python
msg: ReceivedMessage
print(msg.text)  # "你好"
print(msg.text)  # "[语音] 语音转文字内容"
print(msg.text)  # None  （图片/文件类）
```

---

## 常量定义

```python
from wechat_mcp.ilink_client import (
    BASE_URL,       # "https://ilinkai.weixin.qq.com"
    CDN_BASE_URL,  # "https://novac2c.cdn.weixin.qq.com/c2c"
    CHANNEL_VERSION, # "1.0.2"
    ILINK_APP_ID,   # "bot"
    BOT_AGENT,      # "OpenClaw"
    TIMEOUT,        # 40（秒）
)
```

---

## 错误码

| 值 | 说明 | 处理 |
|---|------|------|
| `ret=0, errcode=0` | 成功 | - |
| `ret≠0` | 请求级错误 | 检查 `errmsg` |
| `errcode=-14` | 会话过期 | 重新登录 |
| `errcode=-1` | 参数错误 | 检查请求参数 |
| `errcode=-2` | Token 无效 | 重新登录 |