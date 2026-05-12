"""
微信 iLink MCP Server
通过 stdio 与 MCP CLI 通信，暴露以下工具：
  - wechat_login       扫码登录
  - wechat_reply       发送文字消息
  - wechat_send_image  发送图片
  - wechat_send_file   发送文件/音频
  - wechat_send_voice  TTS 语音发送
  - wechat_listen      长轮询监听消息（事件模式）
"""

import sys
import json
import logging
from pathlib import Path
from typing import Any, Optional

from .ilink_client import ILinkClient, ReceivedMessage

logger = logging.getLogger("wechat_mcp.server")

# MCP 协议常量
JSONRPC_VERSION = "2.0"

# 全局 client 实例（进程内单例）
_client: Optional[ILinkClient] = None


def get_client() -> ILinkClient:
    global _client
    if _client is None:
        _client = ILinkClient()
    return _client


# ─────────────────────────────────────────────────────────────
# MCP 协议工具函数
# ─────────────────────────────────────────────────────────────

def resp_id(req: dict) -> Optional[Any]:
    return req.get("id")


def ok_result(data: Any, req_id: Any) -> dict:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "result": data,
    }


def err(code: int, msg: str, req_id: Any) -> dict:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "error": {"code": code, "message": msg},
    }


# ─────────────────────────────────────────────────────────────
# 工具定义（JSON Schema 格式）
# ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "wechat_login",
        "description": "扫码登录微信 Bot（首次使用需要微信扫码确认）",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "wechat_reply",
        "description": "向指定用户发送文字消息（需要 context_token）",
        "inputSchema": {
            "type": "object",
            "required": ["text", "to_user_id", "context_token"],
            "properties": {
                "to_user_id": {
                    "type": "string",
                    "description": "目标用户 ID（从消息中获取，格式如 o9cq800xxx@im.wechat）",
                },
                "text": {
                    "type": "string",
                    "description": "要发送的文字内容",
                },
                "context_token": {
                    "type": "string",
                    "description": "上下文 Token（从 getupdates 消息中获取）",
                },
            },
        },
    },
    {
        "name": "wechat_send_image",
        "description": "向指定用户发送图片（支持本地路径或 HTTP URL）",
        "inputSchema": {
            "type": "object",
            "required": ["to_user_id", "context_token", "image_path"],
            "properties": {
                "to_user_id": {
                    "type": "string",
                    "description": "目标用户 ID",
                },
                "context_token": {
                    "type": "string",
                    "description": "上下文 Token",
                },
                "image_path": {
                    "type": "string",
                    "description": "图片路径（本地路径或 HTTP URL）",
                },
            },
        },
    },
    {
        "name": "wechat_send_file",
        "description": "向指定用户发送文件/音频（支持 mp3/wav/文件）",
        "inputSchema": {
            "type": "object",
            "required": ["to_user_id", "context_token", "file_path"],
            "properties": {
                "to_user_id": {
                    "type": "string",
                    "description": "目标用户 ID",
                },
                "context_token": {
                    "type": "string",
                    "description": "上下文 Token",
                },
                "file_path": {
                    "type": "string",
                    "description": "文件路径（本地路径，支持 mp3/wav 等音频格式）",
                },
            },
        },
    },
    {
        "name": "wechat_send_voice",
        "description": "将文字转为 TTS 语音后发送给指定用户（需要配置 TTS）",
        "inputSchema": {
            "type": "object",
            "required": ["text", "to_user_id", "context_token"],
            "properties": {
                "to_user_id": {
                    "type": "string",
                    "description": "目标用户 ID",
                },
                "context_token": {
                    "type": "string",
                    "description": "上下文 Token",
                },
                "text": {
                    "type": "string",
                    "description": "要转为语音的文字内容",
                },
                "voice": {
                    "type": "string",
                    "description": "TTS 音色，默认为 zh-CN-XiaoxiaoNeural（Edge-TTS）",
                    "default": "zh-CN-XiaoxiaoNeural",
                },
            },
        },
    },
    {
        "name": "wechat_listen",
        "description": "长轮询监听微信消息，返回下一条消息（用于事件驱动）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cursor": {
                    "type": "string",
                    "description": "游标（首次留空，后续传上次的 get_updates_buf）",
                },
                "timeout": {
                    "type": "number",
                    "description": "轮询超时秒数（默认 35）",
                    "default": 35,
                },
            },
        },
    },
    {
        "name": "wechat_status",
        "description": "查看当前登录状态和 Bot Token",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ─────────────────────────────────────────────────────────────
# 工具执行函数
# ─────────────────────────────────────────────────────────────

def _handle_login(params: dict) -> dict:
    client = get_client()
    try:
        client.login()
        return {"status": "logged_in", "token": client.bot_token[:8] + "..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _handle_reply(params: dict) -> dict:
    client = get_client()
    to_user = params["to_user_id"]
    text = params["text"]
    token = params["context_token"]
    try:
        result = client.send_text(to_user, text, token)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_send_image(params: dict) -> dict:
    client = get_client()
    to_user = params["to_user_id"]
    token = params["context_token"]
    path = params["image_path"]
    try:
        # 下载 HTTP URL
        if path.startswith("http://") or path.startswith("https://"):
            import requests
            r = requests.get(path, timeout=30)
            r.raise_for_status()
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(r.content)
                path = f.name
        result = client.send_image(to_user, token, path)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_send_file(params: dict) -> dict:
    client = get_client()
    to_user = params["to_user_id"]
    token = params["context_token"]
    path = params["file_path"]
    try:
        if path.startswith("http://") or path.startswith("https://"):
            import requests
            r = requests.get(path, timeout=30)
            r.raise_for_status()
            import tempfile, os
            ext = path.split("?")[0].split(".")[-1]
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                f.write(r.content)
                path = f.name
        result = client.send_file(to_user, token, path)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_send_voice(params: dict) -> dict:
    text = params["text"]
    to_user = params["to_user_id"]
    token = params["context_token"]
    voice = params.get("voice", "zh-CN-XiaoxiaoNeural")

    try:
        import tempfile, os, subprocess

        # 尝试 edge-tts（需要安装）
        try:
            out_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            out_path = out_file.name
            out_file.close()
            cmd = [
                sys.executable, "-m", "edge_tts",
                "--text", text,
                "--voice", voice,
                "--write-media", out_path,
            ]
            subprocess.run(cmd, check=True, timeout=30)
        except (FileNotFoundError, subprocess.CalledProcessError):
            # fallback: 尝试 wechat_tts 配置的脚本
            tts_script = Path.home() / ".claude" / "scripts" / "wechat-tts.sh"
            if tts_script.exists():
                out_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                out_path = out_file.name
                out_file.close()
                subprocess.run(["bash", str(tts_script), text, out_path], check=True, timeout=30)
            else:
                return {
                    "success": False,
                    "error": "edge-tts 未安装且未找到 TTS 脚本。"
                             "请运行: pip install edge-tts 或配置 ~/.claude/scripts/wechat-tts.sh"
                }

        client = get_client()
        result = client.send_file(to_user, token, out_path)
        os.unlink(out_path)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_listen(params: dict) -> dict:
    client = get_client()
    cursor = params.get("cursor")
    try:
        msgs, next_cursor = client.get_updates(cursor)
        msg_list = []
        for m in msgs:
            msg_list.append({
                "from_user_id": m.from_user_id,
                "to_user_id": m.to_user_id,
                "context_token": m.context_token,
                "msg_id": m.msg_id,
                "msg_type": m.msg_type,
                "text": m.text,
                "raw": m.raw,
            })
        return {
            "messages": msg_list,
            "next_cursor": next_cursor,
        }
    except Exception as e:
        return {"error": str(e), "messages": []}


def _handle_status(params: dict) -> dict:
    client = get_client()
    return {
        "logged_in": client.bot_token is not None,
        "token_prefix": client.bot_token[:8] + "..." if client.bot_token else None,
    }


TOOL_HANDLERS = {
    "wechat_login": _handle_login,
    "wechat_reply": _handle_reply,
    "wechat_send_image": _handle_send_image,
    "wechat_send_file": _handle_send_file,
    "wechat_send_voice": _handle_send_voice,
    "wechat_listen": _handle_listen,
    "wechat_status": _handle_status,
}


# ─────────────────────────────────────────────────────────────
# MCP 协议主循环
# ─────────────────────────────────────────────────────────────

_initialized = False

def handle_request(req: dict) -> dict:
    """处理 MCP 请求"""
    global _initialized
    method = req.get("method", "")
    req_id = resp_id(req)
    params = req.get("params", {})

    # 初始化
    if method == "initialize":
        # 首次连接时通知服务器客户端上线
        if not _initialized:
            try:
                client = get_client()
                if client.bot_token:
                    client.notify_start()
            except Exception:
                pass
            _initialized = True
        return ok_result({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "wechat-mcp",
                "version": "0.1.0",
            },
        }, req_id)

    # 工具列表
    if method == "tools/list":
        return ok_result({"tools": TOOLS}, req_id)

    # 工具调用
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return err(-32601, f"Unknown tool: {tool_name}", req_id)

        try:
            result = handler(tool_args)
            return ok_result({
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False),
                    }
                ],
                "isError": result.get("error") or result.get("success") is False,
            }, req_id)
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            return ok_result({
                "content": [{"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}],
                "isError": True,
            }, req_id)

    # 未知方法
    return err(-32601, f"Method not found: {method}", req_id)


def main():
    """stdio 主循环，读取 JSON-RPC 请求并响应"""
    logger.info("WeChat MCP Server 已启动")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            print(json.dumps(resp), flush=True)
        except json.JSONDecodeError:
            resp = err(-32700, "Invalid JSON", None)
            print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()