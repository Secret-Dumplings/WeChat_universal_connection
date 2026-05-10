"""
微信 iLink 协议核心客户端
支持：登录扫码、消息接收（长轮询）、发送文字/图片/音频
"""

import json, time, uuid, base64, struct, hashlib, argparse, logging, subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://ilinkai.weixin.qq.com"
TIMEOUT = 40


def random_uin() -> str:
    raw = struct.pack('<I', uuid.uuid4().int & 0xFFFFFFFF)
    return base64.b64encode(raw).decode()


# ─────────────────────────────────────────────
# HTTP 底层（curl 响应 Ctrl+C）
# ─────────────────────────────────────────────

def _http_get(url: str, headers: dict, timeout: float = 30) -> dict:
    h_args = []
    for k, v in headers.items():
        h_args += ["-H", f"{k}: {v}"]
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(int(timeout)), url] + h_args,
        capture_output=True, text=True,
        start_new_session=True,
    )
    return json.loads(r.stdout)


def _http_post(url: str, data: dict, headers: dict, timeout: float = 30) -> dict:
    h_args = []
    for k, v in headers.items():
        h_args += ["-H", f"{k}: {v}"]
    body = json.dumps(data)
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(int(timeout)), "-X", "POST", url, "-d", body] + h_args,
        capture_output=True, text=True,
        start_new_session=True,
    )
    return json.loads(r.stdout)


def _http_put(url: str, data: bytes, headers: dict, timeout: float = 60) -> dict:
    h_args = []
    for k, v in headers.items():
        h_args += ["-H", f"{k}: {v}"]
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(int(timeout)), "-X", "PUT", url, "-d", "@-"] + h_args,
        input=data, capture_output=True,
        start_new_session=True,
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


# ─────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────

@dataclass
class ReceivedMessage:
    from_user_id: str
    to_user_id: str
    context_token: str
    msg_id: str
    msg_type: int
    items: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def text(self) -> Optional[str]:
        for item in self.items:
            if item.get("type") == 1:
                return item.get("text_item", {}).get("content", "")
        return None

    @property
    def has_media(self) -> bool:
        return any(item.get("type") in (2, 3, 4, 5) for item in self.items)


# ─────────────────────────────────────────────
# 客户端
# ─────────────────────────────────────────────

class ILinkClient:
    def __init__(self, bot_token: Optional[str] = None, data_dir: Optional[Path] = None):
        self.bot_token = bot_token
        self.base_url = BASE_URL
        self._data_dir = data_dir or Path.home() / ".wechat_mcp"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._token_file = self._data_dir / "bot_token.txt"
        if not bot_token:
            bot_token = self._load_token()
        self.bot_token = bot_token

    def _load_token(self) -> Optional[str]:
        if self._token_file.exists():
            return self._token_file.read_text().strip()
        return None

    def _save_token(self, token: str):
        self._token_file.write_text(token)
        self.bot_token = token

    def _headers(self, need_auth: bool = True) -> dict:
        h = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": random_uin(),
        }
        if need_auth and self.bot_token:
            h["Authorization"] = f"Bearer {self.bot_token}"
        return h

    # ─────────────────────────────────────────────
    # 1. 登录 & 二维码
    # ─────────────────────────────────────────────

    def get_qrcode(self, bot_type: int = 3) -> tuple[str, str]:
        from urllib.parse import urlencode
        url = f"{self.base_url}/ilink/bot/get_bot_qrcode?{urlencode({'bot_type': bot_type})}"
        data = _http_get(url, self._headers(need_auth=False), timeout=30)
        return data.get("qrcode", ""), data.get("qrcode_img_content", "")

    def show_qrcode(self, qrcode_token: str, qrcode_img_url: str):
        import qrcode
        qr = qrcode.QRCode(
            version=1, box_size=1, border=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
        )
        qr.add_data(qrcode_token)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(self._data_dir / "qrcode.png")

        w = img.width
        print("\n+" + "-" * (w * 2) + "+")
        for y in range(w):
            line = "|"
            for x in range(w):
                px = img.getpixel((x, y))
                if isinstance(px, tuple):
                    brightness = (px[0] + px[1] + px[2]) // 3
                else:
                    brightness = px
                line += "██" if brightness < 128 else "  "
            line += "|"
            print(line)
        print("+" + "-" * (w * 2) + "+")
        print(f"Token: {qrcode_token}")
        print(f"图片: {self._data_dir / 'qrcode.png'}")

    def poll_qrcode_status(self, qrcode_token: str) -> Optional[str]:
        from urllib.parse import urlencode
        retry_count = 0
        max_retries = 30

        while retry_count < max_retries:
            try:
                url = f"{self.base_url}/ilink/bot/get_qrcode_status?{urlencode({'qrcode': qrcode_token})}"
                data = _http_get(url, self._headers(need_auth=False), timeout=120)
                code = data.get("status")
                if code == 1:
                    logger.info("已扫码，等待微信确认...")
                    time.sleep(2)
                elif code == 2:
                    token = data.get("bot_token", "")
                    logger.info("登录成功！")
                    return token
                elif code in ("expired", -1):
                    logger.warning("二维码已过期，重新获取...")
                    new_token, new_url = self.get_qrcode()
                    self.show_qrcode(new_token, new_url)
                    qrcode_token = new_token
                    retry_count += 1
                    time.sleep(3)
                elif code == 0:
                    retry_count += 1
                    logger.info(f"等待扫码... 请用微信扫码 ({retry_count}/{max_retries})")
                    time.sleep(3)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                retry_count += 1
                logger.warning(f"轮询异常 (重试 {retry_count}/{max_retries}): {e}")
                time.sleep(5)
                if retry_count >= max_retries:
                    raise Exception(f"多次连接失败: {e}")

    def login(self) -> str:
        qrcode_token, qrcode_img_url = self.get_qrcode()
        self.show_qrcode(qrcode_token, qrcode_img_url)
        token = self.poll_qrcode_status(qrcode_token)
        self._save_token(token)
        logger.info("Token 已保存，下次启动自动使用")
        return token

    def ensure_logged_in(self):
        if not self.bot_token:
            logger.info("需要登录...")
            self.login()

    # ─────────────────────────────────────────────
    # 2. 接收消息（长轮询）
    # ─────────────────────────────────────────────

    def get_updates(self, cursor: Optional[str] = None) -> tuple[list[ReceivedMessage], Optional[str]]:
        url = f"{self.base_url}/ilink/bot/getupdates"
        payload = {}
        if cursor:
            payload["get_updates_buf"] = cursor
        data = _http_post(url, payload, self._headers(), timeout=TIMEOUT + 5)

        messages = []
        for msg in data.get("messages", []):
            messages.append(ReceivedMessage(
                from_user_id=msg.get("from_user_id", ""),
                to_user_id=msg.get("to_user_id", ""),
                context_token=msg.get("context_token", ""),
                msg_id=msg.get("msg_id", ""),
                msg_type=msg.get("message_type", 0),
                items=msg.get("item_list", []),
                raw=msg,
            ))
        return messages, data.get("get_updates_buf") or None

    # ─────────────────────────────────────────────
    # 3. 发送文字
    # ─────────────────────────────────────────────

    def send_text(self, to_user_id: str, text: str, context_token: str) -> dict:
        url = f"{self.base_url}/ilink/bot/sendmessage"
        payload = {
            "msg": {
                "to_user_id": to_user_id,
                "context_token": context_token,
                "message_type": 1,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"content": text}}],
            }
        }
        return _http_post(url, payload, self._headers(), timeout=30)

    # ─────────────────────────────────────────────
    # 4. 发送图片（CDN + AES 加密）
    # ─────────────────────────────────────────────

    @staticmethod
    def _aes_encrypt(data: bytes, key: bytes) -> bytes:
        from Crypto.Cipher import AES
        pad_len = 16 - (len(data) % 16)
        padded = data + bytes([pad_len] * pad_len)
        return AES.new(key, AES.MODE_ECB).encrypt(padded)

    @staticmethod
    def _file_md5(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    def _get_upload_url(self, filekey: str, media_type: int, to_user_id: str,
                        raw_size: int, raw_md5: str, enc_size: int,
                        thumb_raw_size: Optional[int] = None,
                        thumb_raw_md5: Optional[str] = None,
                        thumb_enc_size: Optional[int] = None) -> dict:
        url = f"{self.base_url}/ilink/bot/getuploadurl"
        payload = {
            "filekey": filekey, "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": raw_size, "rawfilemd5": raw_md5, "filesize": enc_size,
        }
        if thumb_raw_size:
            payload["thumb_rawsize"] = thumb_raw_size
            payload["thumb_rawfilemd5"] = thumb_raw_md5
            payload["thumb_filesize"] = thumb_enc_size
        return _http_post(url, payload, self._headers(), timeout=30)

    def _upload_cdn(self, upload_url: str, encrypted_data: bytes) -> Optional[str]:
        headers = {"Content-Type": "application/octet-stream"}
        extra_args = []
        for k, v in headers.items():
            extra_args += ["-H", f"{k}: {v}"]
        r = subprocess.run(
            ["curl", "-s", "-X", "PUT", upload_url, "-d", "@-"] + extra_args,
            input=encrypted_data, capture_output=True,
            start_new_session=True,
        )
        return r.stdout.strip() or None

    def _generate_thumbnail(self, image_data: bytes, max_size: int = 256) -> bytes:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=80)
        return out.getvalue()

    def send_image(self, to_user_id: str, context_token: str, image_path: str) -> dict:
        import os, base64

        with open(image_path, "rb") as f:
            raw_data = f.read()
        raw_size = len(raw_data)
        raw_md5 = self._file_md5(raw_data)

        aes_key = os.urandom(16)
        enc_data = self._aes_encrypt(raw_data, aes_key)
        enc_size = len(enc_data)

        thumb_data = self._generate_thumbnail(raw_data)
        thumb_raw_md5 = self._file_md5(thumb_data)
        thumb_raw_size = len(thumb_data)
        thumb_key = os.urandom(16)
        thumb_enc = self._aes_encrypt(thumb_data, thumb_key)
        thumb_enc_size = len(thumb_enc)

        filekey = f"img_{uuid.uuid4().hex[:12]}"
        result = self._get_upload_url(
            filekey=filekey, media_type=1, to_user_id=to_user_id,
            raw_size=raw_size, raw_md5=raw_md5, enc_size=enc_size,
            thumb_raw_size=thumb_raw_size,
            thumb_raw_md5=thumb_raw_md5, thumb_enc_size=thumb_enc_size,
        )

        enc_param = self._upload_cdn(result.get("upload_param", ""), enc_data)
        if not enc_param:
            raise Exception("CDN 上传失败，未收到 encrypt_query_param")
        thumb_enc_param = self._upload_cdn(result.get("thumb_upload_param", ""), thumb_enc)
        if not thumb_enc_param:
            raise Exception("缩略图上传失败")

        url = f"{self.base_url}/ilink/bot/sendmessage"
        payload = {
            "msg": {
                "to_user_id": to_user_id,
                "context_token": context_token,
                "message_type": 2,
                "message_state": 2,
                "item_list": [{
                    "type": 2,
                    "image_item": {
                        "cdn_media": {
                            "encrypt_query_param": enc_param,
                            "aes_key": base64.b64encode(aes_key).decode(),
                        },
                        "thumb_cdn_media": {
                            "encrypt_query_param": thumb_enc_param,
                            "aes_key": base64.b64encode(thumb_key).decode(),
                        },
                    },
                }],
            }
        }
        return _http_post(url, payload, self._headers(), timeout=30)

    # ─────────────────────────────────────────────
    # 5. 发送文件/音频（FILE 类型）
    # ─────────────────────────────────────────────

    def send_file(self, to_user_id: str, context_token: str, file_path: str) -> dict:
        import os, base64

        with open(file_path, "rb") as f:
            raw_data = f.read()
        raw_size = len(raw_data)
        raw_md5 = self._file_md5(raw_data)

        aes_key = os.urandom(16)
        enc_data = self._aes_encrypt(raw_data, aes_key)
        enc_size = len(enc_data)

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".mp3", ".wav", ".ogg", ".aac"):
            media_type = 4
        elif ext in (".jpg", ".jpeg", ".png", ".gif"):
            media_type = 1
        elif ext in (".mp4", ".avi", ".mov"):
            media_type = 2
        else:
            media_type = 4

        filekey = f"file_{uuid.uuid4().hex[:12]}"
        result = self._get_upload_url(
            filekey=filekey, media_type=media_type, to_user_id=to_user_id,
            raw_size=raw_size, raw_md5=raw_md5, enc_size=enc_size,
        )

        enc_param = self._upload_cdn(result.get("upload_param", ""), enc_data)
        if not enc_param:
            raise Exception("文件 CDN 上传失败")

        url = f"{self.base_url}/ilink/bot/sendmessage"
        payload = {
            "msg": {
                "to_user_id": to_user_id,
                "context_token": context_token,
                "message_type": 2,
                "message_state": 2,
                "item_list": [{
                    "type": 4,
                    "file_item": {
                        "cdn_media": {
                            "encrypt_query_param": enc_param,
                            "aes_key": base64.b64encode(aes_key).decode(),
                        },
                        "file_name": os.path.basename(file_path),
                        "file_size": str(raw_size),
                    },
                }],
            }
        }
        return _http_post(url, payload, self._headers(), timeout=30)

    # ─────────────────────────────────────────────
    # 6. 快捷回复
    # ─────────────────────────────────────────────

    def reply_to_message(self, msg: ReceivedMessage, text: str) -> dict:
        return self.send_text(msg.from_user_id, text, msg.context_token)

    def reply_image_to_message(self, msg: ReceivedMessage, image_path: str) -> dict:
        return self.send_image(msg.from_user_id, msg.context_token, image_path)

    def reply_file_to_message(self, msg: ReceivedMessage, file_path: str) -> dict:
        return self.send_file(msg.from_user_id, msg.context_token, file_path)