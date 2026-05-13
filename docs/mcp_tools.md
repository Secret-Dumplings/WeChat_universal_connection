# MCP Server 工具说明

> `wechat_mcp.mcp_server` — 通过 stdio 与 MCP CLI 通信，暴露 7 个工具

---

## 目录

- [使用方式](#使用方式)
- [工具列表](#工具列表)
  - [wechat_login](#wechat_login)
  - [wechat_reply](#wechat_reply)
  - [wechat_send_image](#wechat_send_image)
  - [wechat_send_file](#wechat_send_file)
  - [wechat_send_voice](#wechat_send_voice)
  - [wechat_listen](#wechat_listen)
  - [wechat_status](#wechat_status)
- [响应格式](#响应格式)
- [错误处理](#错误处理)

---

## 使用方式

### 启动 MCP Server

```bash
python main.py mcp
```

以 `stdio` 模式启动，从 stdin 读取 JSON-RPC 请求，向 stdout 写入响应。

### 配置 Claude Code

在项目根目录 `CLAUDE.md` 或全局配置中添加：

```json
{
  "mcp_servers": {
    "wechat": {
      "command": "python",
      "args": ["C:/path/to/main.py", "mcp"]
    }
  }
}
```

### 配置 Cursor

在 `.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "wechat": {
      "command": "python",
      "args": ["C:/path/to/main.py", "mcp"]
    }
  }
}
```

---

## 工具列表

### wechat_login

扫码登录微信 Bot。首次使用需要微信扫码确认。

**参数**：无

**返回**
```json
{
  "status": "logged_in",
  "token": "a195ce9526a9@im.bot:..."
}
```

**失败**
```json
{
  "status": "error",
  "message": "错误信息"
}
```

---

### wechat_reply

向指定用户发送文字消息。

**参数**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `to_user_id` | `string` | 是 | 目标用户 ID（格式如 `o9cq800xxx@im.wechat`） |
| `text` | `string` | 是 | 要发送的文字内容 |
| `context_token` | `string` | 是 | 上下文 Token（从 `wechat_listen` 获取） |

**返回**
```json
{
  "success": true,
  "result": { "ret": 0 }
}
```

**失败**
```json
{
  "success": false,
  "error": "错误信息"
}
```

---

### wechat_send_image

向指定用户发送图片。

**参数**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `to_user_id` | `string` | 是 | 目标用户 ID |
| `context_token` | `string` | 是 | 上下文 Token |
| `image_path` | `string` | 是 | 图片路径（本地路径或 HTTP URL） |

**支持**

- 本地路径：`C:/path/to/image.jpg`
- HTTP URL：`https://example.com/image.jpg`（会自动下载）

**返回**
```json
{
  "success": true,
  "result": { "ret": 0 }
}
```

---

### wechat_send_file

向指定用户发送文件或音频。

**参数**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `to_user_id` | `string` | 是 | 目标用户 ID |
| `context_token` | `string` | 是 | 上下文 Token |
| `file_path` | `string` | 是 | 文件路径（本地路径或 HTTP URL） |

**支持扩展名**

| 类型 | 扩展名 |
|------|--------|
| 语音 | `.mp3 .wav .ogg .aac` |
| 图片 | `.jpg .jpeg .png .gif` |
| 视频 | `.mp4 .avi .mov` |
| 文件 | 其他 |

**返回**
```json
{
  "success": true,
  "result": { "ret": 0 }
}
```

---

### wechat_send_voice

将文字转为 TTS 语音后发送给指定用户。

**参数**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `to_user_id` | `string` | 是 | — | 目标用户 ID |
| `context_token` | `string` | 是 | — | 上下文 Token |
| `text` | `string` | 是 | — | 要转为语音的文字 |
| `voice` | `string` | 否 | `zh-CN-XiaoxiaoNeural` | TTS 音色（Edge-TTS） |

**可用音色（部分）**

| 音色 | 语言 | 说明 |
|------|------|------|
| `zh-CN-XiaoxiaoNeural` | 中文 | 女声-晓晓 |
| `zh-CN-YunxiNeural` | 中文 | 男声-云希 |
| `zh-CN-YunyangNeural` | 中文 | 男声-云扬 |
| `en-US-JennyNeural` | 英文 | 女声-Jenny |
| `ja-JP-NanamiNeural` | 日文 | 女声-七美 |

**前置依赖**

```bash
pip install edge-tts
```

**返回**
```json
{
  "success": true,
  "result": { "ret": 0 }
}
```

**错误**：edge-tts 未安装且无 TTS 脚本时返回 `{"success": false, "error": "..."}`

---

### wechat_listen

长轮询监听微信消息，返回下一条消息。用于事件驱动模式。

**参数**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `cursor` | `string` | 否 | `null` | 游标（首次留空，后续传上次的 `next_cursor`） |
| `timeout` | `number` | 否 | `35` | 轮询超时秒数 |

**返回**
```json
{
  "messages": [
    {
      "from_user_id": "o9cq800xxx@im.wechat",
      "to_user_id": "a195ce9526a9@im.bot",
      "context_token": "xxx...",
      "msg_id": "msg_xxx",
      "msg_type": 1,
      "text": "用户发送的文本",
      "raw": { ... }
    }
  ],
  "next_cursor": "游标字符串，下次传入"
}
```

**注意**
- 超时时间由服务器控制（约 35 秒），`timeout` 参数仅影响本地超时
- 无消息时 `messages` 为空数组，`next_cursor` 为 `null` 或空字符串
- **必须保存并回传 `next_cursor`**，否则消息可能丢失

**消息类型**

| msg_type | 含义 | text 字段 |
|----------|------|----------|
| 1 | 用户文本 | 文本内容 |
| 2 | 用户图片 | `null` |
| 3 | 用户语音 | `[语音]` 或 `[语音] 转文字` |
| 4 | 用户文件 | `null` |
| 5 | 用户视频 | `null` |

---

### wechat_status

查看当前登录状态和 Bot Token（部分）。

**参数**：无

**返回**
```json
{
  "logged_in": true,
  "token_prefix": "a195ce95..."
}
```

---

## 响应格式

所有工具调用均返回以下 JSON 结构（JSON-RPC 2.0）：

```json
{
  "jsonrpc": "2.0",
  "id": <请求id>,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "工具执行结果的 JSON 字符串"
      }
    ],
    "isError": false
  }
}
```

工具执行结果被序列化在 `content[0].text` 字段中，调用方需 `JSON.parse` 获取实际数据。

---

## 错误处理

| 错误类型 | `isError` | 说明 |
|----------|-----------|------|
| 正常成功 | `false` | - |
| 工具内部异常 | `true` | 返回 `{"error": "异常信息"}` |
| `success=false` | `true` | 业务逻辑失败，返回 `{"success": false, "error": "..."}` |
| Token 未加载 | `true` | 未登录或 token 过期 |

---

## 内部架构

```
MCP CLI (stdin/stdout)
    │
    ▼
mcp_server.py
    ├── handle_request()      # 路由 JSON-RPC 请求
    │   ├── initialize()      # 协议初始化 + notify_start
    │   ├── tools/list        # 返回 TOOLS 列表
    │   └── tools/call        # 执行工具
    │
    ├── get_client()          # 全局单例 ILinkClient
    │
    └── TOOL_HANDLERS
        ├── _handle_login()
        ├── _handle_reply()
        ├── _handle_send_image()
        ├── _handle_send_file()
        ├── _handle_send_voice()
        ├── _handle_listen()
        └── _handle_status()
            │
            ▼
        ILinkClient
```

**全局单例**：进程内 `_client: Optional[ILinkClient] = None`，所有工具共享同一实例。