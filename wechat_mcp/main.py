"""
微信 iLink Agent 连接器 — 入口脚本
支持三种运行模式：
  python main.py login        扫码登录
  python main.py send        发送消息（文字/图片/音频）
  python main.py mcp         启动 MCP Server（stdio 模式，供 MCP CLI 使用）
  python main.py listen      长轮询监听消息
"""

import sys
import os
import logging
from pathlib import Path

# 添加项目根目录到 Python path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("wechat_mcp")


def cmd_login():
    from wechat_mcp.ilink_client import ILinkClient
    try:
        client = ILinkClient()
        client.login()
        print(f"\n✅ 登录成功！Token 已保存到 ~/.wechat_mcp/bot_token.txt")
        print(f"   Token 前 8 位: {client.bot_token[:8]}...")
    except KeyboardInterrupt:
        print("\n\n已取消登录")


def cmd_send(args):
    from wechat_mcp.ilink_client import ILinkClient
    client = ILinkClient()
    client.ensure_logged_in()

    if args.text:
        result = client.send_text(args.to, args.text, args.token)
        print(f"✅ 文字发送成功: {result}")
    elif args.image:
        result = client.send_image(args.to, args.token, args.image)
        print(f"✅ 图片发送成功: {result}")
    elif args.file:
        result = client.send_file(args.to, args.token, args.file)
        print(f"✅ 文件发送成功: {result}")


def cmd_listen(args):
    from wechat_mcp.ilink_client import ILinkClient
    client = ILinkClient()
    client.ensure_logged_in()
    # 通知服务器客户端启动
    try:
        client.notify_start()
    except Exception as e:
        print(f"notify_start 失败（忽略）: {e}")
    cursor = None
    print("开始长轮询监听微信消息... 按 Ctrl+C 退出\n")
    try:
        while True:
            msgs, cursor = client.get_updates(cursor)
            for m in msgs:
                print(f"\n收到消息:")
                print(f"  发送者: {m.from_user_id}")
                print(f"  类型: {m.msg_type} {'TEXT' if m.msg_type==1 else 'IMAGE' if m.msg_type==2 else 'OTHER'}")
                print(f"  内容: {m.text or '(媒体/其他)'}")
                print(f"  上下文: {m.context_token[:30]}...")
                if m.text and not args.quiet:
                    client.reply_to_message(m, f"收到: {m.text}")
                    print(f"  -> 已自动回复")
            if args.once:
                break
            if not msgs:
                print(".", end="", flush=True)
    except KeyboardInterrupt:
        print("\n\n退出监听")


def cmd_mcp():
    """启动 MCP Server（stdio 模式）"""
    from wechat_mcp.mcp_server import main
    main()


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="微信 iLink Agent 连接器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  登录:         python main.py login
  发送文字:     python main.py send --to <用户ID> --token <ctx> --text "你好"
  发送图片:     python main.py send --to <用户ID> --token <ctx> --image 1.jpg
  发送文件:     python main.py send --to <用户ID> --token <ctx> --file audio.mp3
  监听消息:     python main.py listen
  启动MCP:      python main.py mcp  (由 MCP CLI 调用)
        """,
    )

    sub = parser.add_subparsers(dest="cmd")

    # login
    sub.add_parser("login", help="扫码登录微信 Bot")

    # send
    send_p = sub.add_parser("send", help="发送消息")
    send_p.add_argument("--to", required=True, help="目标用户 ID")
    send_p.add_argument("--token", required=True, help="context_token")
    send_p.add_argument("--text", help="文字内容")
    send_p.add_argument("--image", help="图片路径")
    send_p.add_argument("--file", help="文件路径（mp3/音频等）")

    # listen
    listen_p = sub.add_parser("listen", help="长轮询监听消息")
    listen_p.add_argument("--once", action="store_true", help="只轮询一次")
    listen_p.add_argument("--quiet", action="store_true", help="静默模式，不自动回复")

    # mcp
    sub.add_parser("mcp", help="启动 MCP Server（stdio 模式）")

    args = parser.parse_args()

    if args.cmd == "login":
        cmd_login()
    elif args.cmd == "send":
        cmd_send(args)
    elif args.cmd == "listen":
        cmd_listen(args)
    elif args.cmd == "mcp":
        cmd_mcp()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()