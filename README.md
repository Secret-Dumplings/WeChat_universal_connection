# 微信 iLink Bot 连接器

通过微信 iLink 协议接入个人微信，支持消息收发、媒体文件发送、TTS 语音和 MCP Server。

> 参考官方 `@tencent-weixin/openclaw-weixin` v2.4.3 实现，基于逆向分析腾讯官方插件源码。

---

## 功能特性

- **扫码登录**：终端 ASCII 二维码 + 手机扫码授权
- **消息收发**：长轮询接收文字/图片/语音/文件，发送文本消息
- **媒体上传**：AES-128-ECB 加密 + CDN 中转发送图片/文件/语音
- **MCP Server**：`stdio` 模式，兼容 Claude MCP CLI / Cursor / 其他 MCP 客户端
- **TTS 语音**：文字转语音（edge-tts）发送给微信用户

---

## 安装

### 方式一：pip

```bash
pip install -e .
```

### 方式二：uv（推荐）

```bash
uv pip install -e .
```

### 依赖

- Python >= 3.12
- `pycryptodome`（AES 加密）
- `Pillow`（图片缩略图）
- `qrcode`（终端二维码渲染）
- 可选：`edge-tts`（TTS 语音）
- 可选：`mcp`（ MCP CLI）

---

## 快速开始

### 1. 扫码登录

```bash
python main.py login
```

终端显示 ASCII 二维码，用微信扫描并在手机确认。登录成功后将 Token 保存到 `~/.wechat_mcp/bot_token.txt`。

### 2. 监听消息

```bash
python main.py listen
# 或只轮询一次
python main.py listen --once
# 静默模式（不自动回复）
python main.py listen --quiet
```

### 3. 发送消息

需要先获取目标用户的 `to_user_id` 和 `context_token`（从监听消息中获取）。

```bash
# 发送文字
python main.py send --to <用户ID> --token <context_token> --text "你好"

# 发送图片
python main.py send --to <用户ID> --token <context_token> --image 1.jpg

# 发送文件/音频
python main.py send --to <用户ID> --token <context_token> --file audio.mp3
```

### 4. 启动 MCP Server

```bash
python main.py mcp
```

以 `stdio` 模式启动，供 MCP CLI 调用。

---

## 项目结构

```
WeChat_universal_connection/
├── main.py                  # CLI 入口（login/listen/send/mcp）
├── pyproject.toml            # 包配置
├── wechat_mcp/
│   ├── __init__.py
│   ├── ilink_client.py       # iLink 协议核心客户端（ILinkClient）
│   ├── mcp_server.py        # MCP Server（stdio 模式）
│   └── main.py              # CLI 子命令实现
├── docs/
│   ├── ilink_protocol.md    # 协议文档
│   ├── api_reference.md     # API 参考
│   ├── mcp_tools.md         # MCP 工具说明
│   └── development.md       # 二次开发指南
└── test_send_hello.py        # 测试脚本
```

---

## MCP Server 使用

### 配置 Claude Code

在 `~/.claude/projects/.../CLAUDE.md` 中添加：

```json
{
  "mcp_servers": {
    "wechat": {
      "command": "python",
      "args": ["C:/path/to/WeChat_universal_connection/main.py", "mcp"]
    }
  }
}
```

### 可用工具

| 工具 | 说明 |
|------|------|
| `wechat_login` | 扫码登录微信 Bot |
| `wechat_reply` | 发送文字消息 |
| `wechat_send_image` | 发送图片（本地路径或 HTTP URL） |
| `wechat_send_file` | 发送文件/音频 |
| `wechat_send_voice` | TTS 语音发送 |
| `wechat_listen` | 长轮询监听消息 |
| `wechat_status` | 查看登录状态 |

---

## 注意事项

1. **Token 安全**：Token 保存于 `~/.wechat_mcp/bot_token.txt`，泄露可能导致账号被盗用
2. **context_token 必需**：回复消息时必须原样带回入站消息的 `context_token`
3. **notify_start**：启动监听前 MCP Server 会自动调用，CLI 模式需手动调用
4. **会话过期（-14）**：收到 `errcode=-14` 后需重新扫码登录
5. **多设备登录**：微信 Web 协议支持多设备，但建议单实例运行

---

## 相关文档

- [协议文档](docs/ilink_protocol.md) — iLink 协议详细说明
- [API 参考](docs/api_reference.md) — Python API 完整参考
- [MCP 工具说明](docs/mcp_tools.md) — MCP Server 工具用法
- [二次开发指南](docs/development.md) — 扩展开发流程