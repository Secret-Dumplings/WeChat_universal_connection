#!/usr/bin/env python3
"""测试：收到消息后回复 Hello World"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wechat_mcp.ilink_client import ILinkClient

def main():
    client = ILinkClient()

    if not client.bot_token:
        print("未登录，请先 python main.py login")
        sys.exit(1)

    print(f"Bot Token: {client.bot_token[:20]}...")
    print()

    # 通知服务器客户端启动
    print("=== notify_start ===")
    try:
        r = client.notify_start()
        print(f"notify_start: {r}")
    except Exception as e:
        print(f"notify_start 失败: {e}")

    cursor = None

    print("\n等待收到消息...\n")

    try:
        while True:
            msgs, cursor = client.get_updates(cursor)
            if msgs:
                for m in msgs:
                    print(f"收到消息 from={m.from_user_id}")
                    print(f"  text={m.text}")
                    print(f"  context_token={m.context_token[:30]}...")
                    print()
                    if m.text:
                        print(f"=== 回复 Hello World 到 {m.from_user_id} ===")
                        result = client.send_text(
                            to_user_id=m.from_user_id,
                            text="Hello World",
                            context_token=m.context_token,
                        )
                        print(f"发送结果: {result}")
                        print("\n测试完成！")
                        return
                    elif cursor:
                        print(f"cursor: {cursor[:30]}...")
                print("收到媒体/其他类型消息，继续监听...")
            else:
                print(".", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n已退出")

if __name__ == "__main__":
    main()