"""
微信 iLink 协议核心客户端
参考官方 @tencent-weixin/openclaw-weixin v2.4.3 实现
支持：登录扫码、消息接收（长轮询）、发送文字/图片/文件/音频
"""

import json, time, uuid, base64, hashlib, logging, subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
CHANNEL_VERSION = "1.0.2"
ILINK_APP_ID = "bot"
BOT_AGENT = "OpenClaw"
TIMEOUT = 40  # 服务器长轮询约 35 秒


# ─────────────────────────────────────────────
# HTTP 底层
# ─────────────────────────────────────────────

def random_uin() -> str:
    """X-WECHAT-UIN: uint32 → decimal string → base64"""
    import secrets
    val = secrets.randbelow(2**32)
    return base64.b64encode(str(val).encode()).decode()


def _curl(url: str, method: str = "GET", headers: dict = None, body: bytes = None, timeout: int = 30) -> dict:
    """统一的 curl 封装。headers 中 Value 不要含冒号后的空格（curl -H "Key: Value"）"""
    headers = headers or {}
    h_args = []
    for k, v in headers.items():
        h_args += ["-H", f"{k}: {v}"]
    cmd = ["curl", "-s", "--max-time", str(timeout)]
    if method != "GET":
        cmd += ["-X", method]
    cmd += [url] + h_args
    if body is not None:
        cmd += ["-d", "@-"]
    try:
        r = subprocess.run(cmd, input=body, capture_output=True, start_new_session=True)
    except Exception as e:
        logger.error(f"curl 执行失败: {e}")
        return {}
    raw = r.stdout
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        logger.warning(f"JSON 解析失败: {raw[:200]}")
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
                return item.get("text_item", {}).get("text", "")
            if item.get("type") == 3:
                v = item.get("voice_item", {}).get("text", "")
                return f"[语音] {v}" if v else "[语音]"
        return None


# ─────────────────────────────────────────────
# 客户端
# ─────────────────────────────────────────────

class ILinkClient:
    def __init__(self, bot_token: Optional[str] = None, data_dir: Optional[Path] = None):
        self.base_url = BASE_URL
        self._data_dir = data_dir or Path.home() / ".wechat_mcp"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._token_file = self._data_dir / "bot_token.txt"
        # bot_token 格式：ilink_bot_id:token（如 a195ce9526a9@im.bot:060000...）
        self.bot_token = bot_token or self._load_token()

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
            "iLink-App-Id": ILINK_APP_ID,
            "X-WECHAT-UIN": random_uin(),
        }
        if need_auth and self.bot_token:
            h["Authorization"] = f"Bearer {self.bot_token}"
        return h

    def _build_base_info(self) -> dict:
        return {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}

    # ─────────────────────────────────────────────
    # 0. 会话通知（官方插件在网关启动/停止时调用）
    # ─────────────────────────────────────────────

    def notify_start(self) -> dict:
        """通知服务器客户端启动"""
        url = f"{self.base_url}/ilink/bot/msg/notifystart"
        payload = {"base_info": self._build_base_info()}
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=10)

    def notify_stop(self) -> dict:
        """通知服务器客户端停止"""
        url = f"{self.base_url}/ilink/bot/msg/notifystop"
        payload = {"base_info": self._build_base_info()}
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=10)

    # ─────────────────────────────────────────────
    # 1. 登录 & 二维码
    # ─────────────────────────────────────────────

    def get_qrcode(self, bot_type: int = 3) -> tuple[str, str]:
        """
        获取登录二维码。
        官方实现要点：
        - POST 请求带 body
        - body 包含 local_token_list（已有 token 列表），服务器据此判断是否已绑定
        - 返回 qrcode(UUID) 和 qrcode_img_content(扫码 URL)
        """
        url = f"{self.base_url}/ilink/bot/get_bot_qrcode?bot_type={bot_type}"
        body = json.dumps(
            {"local_token_list": [self.bot_token] if self.bot_token else []},
            ensure_ascii=False
        ).encode()
        data = _curl(url, "POST", self._headers(need_auth=False), body, timeout=30)
        return data.get("qrcode", ""), data.get("qrcode_img_content", "")

    def show_qrcode(self, qrcode_token: str, qrcode_url: str):
        """终端展示 ASCII 二维码"""
        import qrcode
        qr_data = qrcode_url or qrcode_token
        qr_obj = qrcode.QRCode(version=1, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr_obj.add_data(qr_data)
        qr_obj.make(fit=True)
        modules = qr_obj.modules
        size = len(modules)
        print("\n+" + "-" * (size * 2) + "+")
        for row in modules:
            print("|" + "".join("██" if m else "  " for m in row) + "|")
        print("+" + "-" * (size * 2) + "+")
        print(f"扫码链接: {qrcode_url or qrcode_token}")
        qr_obj.make_image(fill_color="black", back_color="white").save(self._data_dir / "qrcode.png")
        print(f"二维码图片: {self._data_dir / 'qrcode.png'}")

    def poll_qrcode_status(self, qrcode_token: str) -> Optional[str]:
        """
        轮询扫码状态（GET 请求，无 body）。
        官方状态码：wait / scaned / confirmed / expired
        另有：scaned_but_redirect / need_verifycode / verify_code_blocked / binded_redirect
        """
        url = f"{self.base_url}/ilink/bot/get_qrcode_status?qrcode={qrcode_token}"
        while True:
            data = _curl(url, "GET", self._headers(need_auth=False), timeout=40)
            status = data.get("status", "wait")
            if status == "wait":
                logger.info("等待扫码...")
                time.sleep(2)
            elif status == "scaned":
                logger.info("已扫码，请在微信中确认登录...")
                time.sleep(2)
            elif status == "confirmed":
                token = data.get("bot_token", "")
                if not token:
                    logger.error(f"confirmed 但无 bot_token: {data}")
                    return None
                # 优先用服务器返回的 baseurl 更新连接地址
                baseurl = data.get("baseurl", "").strip()
                if baseurl:
                    self.base_url = baseurl.rstrip("/")
                    logger.info(f"更新 base_url 为 {self.base_url}")
                logger.info(f"登录成功! ilink_bot_id={data.get('ilink_bot_id','')}")
                return token
            elif status == "expired":
                logger.warning("二维码过期，重新获取...")
                new_token, new_url = self.get_qrcode()
                self.show_qrcode(new_token, new_url)
                qrcode_token = new_token
                time.sleep(3)
            elif status in ("need_verifycode", "verify_code_blocked"):
                logger.warning(f"需要验证码: {status}")
                time.sleep(2)
            elif status == "binded_redirect":
                logger.info("已连接过此实例，无需重复连接")
                return None
            else:
                logger.warning(f"未知状态: {status}，响应: {data}")
                time.sleep(2)

    def login(self) -> str:
        """完整扫码登录流程"""
        qrcode_token, qrcode_url = self.get_qrcode()
        self.show_qrcode(qrcode_token, qrcode_url)
        token = self.poll_qrcode_status(qrcode_token)
        if token:
            self._save_token(token)
            logger.info("Token 已保存")
        return token or ""

    def ensure_logged_in(self):
        if not self.bot_token:
            logger.info("需要登录...")
            self.login()

    # ─────────────────────────────────────────────
    # 2. 接收消息（长轮询）
    # ─────────────────────────────────────────────

    def get_updates(self, cursor: Optional[str] = None) -> tuple[list[ReceivedMessage], Optional[str]]:
        """
        长轮询获取消息。
        - timeout 由服务器控制（约 35 秒）
        - cursor（get_updates_buf）必须原样回传
        - API 返回 ret!=0 或 errcode!=0 表示错误（-14=会话过期）
        """
        url = f"{self.base_url}/ilink/bot/getupdates"
        payload = {
            "get_updates_buf": cursor or "",
            "base_info": self._build_base_info(),
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        data = _curl(url, "POST", self._headers(), body, timeout=TIMEOUT + 15)

        # 错误检查
        ret = data.get("ret", 0) if data else 0
        errcode = data.get("errcode", 0) if data else 0
        if ret != 0 or errcode != 0:
            errmsg = data.get("errmsg", "")
            logger.warning(f"get_updates 错误: ret={ret} errcode={errcode} errmsg={errmsg}")
            if errcode == -14 or ret == -14:
                logger.error("会话过期，请重新登录！")

        messages = []
        for msg in data.get("msgs", []):
            messages.append(ReceivedMessage(
                from_user_id=msg.get("from_user_id", ""),
                to_user_id=msg.get("to_user_id", ""),
                context_token=msg.get("context_token", ""),
                msg_id=str(msg.get("msg_id", "")),
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
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"py-{uuid.uuid4()}",
                "message_type": 2,   # BOT 发送
                "message_state": 2,  # FINISH
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
            "base_info": self._build_base_info(),
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=30)

    # ─────────────────────────────────────────────
    # 4. 发送图片（CDN + AES-128-ECB）
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

    @staticmethod
    def _aes_padded_size(plaintext_size: int) -> int:
        """PKCS7 填充后的密文长度（16 字节对齐）"""
        return ((plaintext_size // 16) + 1) * 16

    def _get_upload_url(self, filekey: str, media_type: int, to_user_id: str,
                        raw_size: int, raw_md5: str, enc_size: int,
                        aeskey: str,
                        thumb_raw_size: Optional[int] = None,
                        thumb_raw_md5: Optional[str] = None,
                        thumb_enc_size: Optional[int] = None) -> dict:
        """获取 CDN 上传预签名 URL"""
        url = f"{self.base_url}/ilink/bot/getuploadurl"
        payload = {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": raw_size,
            "rawfilemd5": raw_md5,
            "filesize": enc_size,
            "aeskey": aeskey,   # hex 字符串
            "base_info": self._build_base_info(),
        }
        if thumb_raw_size:
            payload["thumb_rawsize"] = thumb_raw_size
            payload["thumb_rawfilemd5"] = thumb_raw_md5
            payload["thumb_filesize"] = thumb_enc_size
            payload["no_need_thumb"] = False
        else:
            payload["no_need_thumb"] = True
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=30)

    def _upload_cdn(self, upload_url: str, encrypted_data: bytes) -> Optional[str]:
        """
        上传密文到 CDN，返回 x-encrypted-param 下载参数。
        - CDN 返回 x-encrypted-param HTTP 响应头
        - 上传目标优先用 upload_full_url（完整 URL），否则用 upload_param 拼接
        """
        r = subprocess.run(
            ["curl", "-s", "-i", "-X", "POST",
             "-H", "Content-Type: application/octet-stream",
             "--max-time", "60",
             "-d", "@-", upload_url],
            input=encrypted_data, capture_output=True,
            start_new_session=True,
        )
        raw = r.stdout
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        # HTTP/1.1 200 OK\r\nheaders\r\n\r\nbody
        sep = "\r\n\r\n"
        idx = raw.find(sep)
        if idx == -1:
            logger.warning(f"CDN 上传响应无 body 分隔符")
            return None
        header_section = raw[:idx]
        for line in header_section.splitlines():
            if line.lower().startswith("x-encrypted-param:"):
                return line.split(":", 1)[1].strip()
        logger.warning(f"CDN 上传响应无 x-encrypted-param 头: {header_section[:200]}")
        return None

    def _generate_thumbnail(self, image_data: bytes, max_size: int = 256) -> bytes:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)
        return out.getvalue()

    def send_image(self, to_user_id: str, context_token: str, image_path: str) -> dict:
        """
        发送图片：本地读取 → AES-128-ECB 加密 → CDN 上传 → 引用发送
        """
        import os, base64

        with open(image_path, "rb") as f:
            raw_data = f.read()

        raw_size = len(raw_data)
        raw_md5 = self._file_md5(raw_data)

        # 主图 AES 加密
        aes_key = os.urandom(16)
        aeskey_hex = aes_key.hex()
        enc_data = self._aes_encrypt(raw_data, aes_key)
        enc_size = len(enc_data)

        # 缩略图
        thumb_data = self._generate_thumbnail(raw_data)
        thumb_raw_size = len(thumb_data)
        thumb_raw_md5 = self._file_md5(thumb_data)
        thumb_key = os.urandom(16)
        thumb_enc = self._aes_encrypt(thumb_data, thumb_key)
        thumb_enc_size = len(thumb_enc)

        filekey = f"img_{uuid.uuid4().hex[:12]}"
        result = self._get_upload_url(
            filekey=filekey, media_type=1, to_user_id=to_user_id,
            raw_size=raw_size, raw_md5=raw_md5, enc_size=enc_size,
            aeskey=aeskey_hex,
            thumb_raw_size=thumb_raw_size,
            thumb_raw_md5=thumb_raw_md5, thumb_enc_size=thumb_enc_size,
        )

        # 上传主图：优先用 upload_full_url
        cdn_url = result.get("upload_full_url") or ""
        if not cdn_url:
            up = result.get("upload_param", "")
            cdn_url = f"{CDN_BASE_URL}/upload?encrypted_query_param={up}&filekey={filekey}"
        enc_param = self._upload_cdn(cdn_url, enc_data)
        if not enc_param:
            raise Exception("CDN 主图上传失败")

        # 上传缩略图
        thumb_cdn_url = result.get("thumb_upload_full_url") or ""
        if not thumb_cdn_url:
            thumb_up = result.get("thumb_upload_param", "")
            if thumb_up:
                thumb_cdn_url = f"{CDN_BASE_URL}/upload?encrypted_query_param={thumb_up}&filekey={filekey}_thumb"
        thumb_enc_param = None
        if thumb_cdn_url:
            thumb_enc_param = self._upload_cdn(thumb_cdn_url, thumb_enc)

        # AES key 格式：hex → UTF-8 → base64
        aes_key_base64 = base64.b64encode(aeskey_hex.encode("utf-8")).decode("utf-8")
        thumb_key_base64 = base64.b64encode(thumb_key.hex().encode("utf-8")).decode("utf-8")

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
                    "type": 2,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": enc_param,
                            "aes_key": aes_key_base64,
                            "encrypt_type": 1,
                            "mid_size": enc_size,
                        },
                        **({"thumb_media": {
                            "encrypt_query_param": thumb_enc_param,
                            "aes_key": thumb_key_base64,
                            "encrypt_type": 1,
                        }} if thumb_enc_param else {}),
                    },
                }],
            },
            "base_info": self._build_base_info(),
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=30)

    # ─────────────────────────────────────────────
    # 5. 发送文件/音频
    # ─────────────────────────────────────────────

    def send_file(self, to_user_id: str, context_token: str, file_path: str) -> dict:
        """发送文件/音频"""
        import os, base64

        with open(file_path, "rb") as f:
            raw_data = f.read()
        raw_size = len(raw_data)
        raw_md5 = self._file_md5(raw_data)

        aes_key = os.urandom(16)
        aeskey_hex = aes_key.hex()
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
            media_type = 4  # 文件

        filekey = f"file_{uuid.uuid4().hex[:12]}"
        result = self._get_upload_url(
            filekey=filekey, media_type=media_type, to_user_id=to_user_id,
            raw_size=raw_size, raw_md5=raw_md5, enc_size=enc_size,
            aeskey=aeskey_hex,
        )

        cdn_url = result.get("upload_full_url") or ""
        if not cdn_url:
            up = result.get("upload_param", "")
            cdn_url = f"{CDN_BASE_URL}/upload?encrypted_query_param={up}&filekey={filekey}"
        enc_param = self._upload_cdn(cdn_url, enc_data)
        if not enc_param:
            raise Exception("CDN 文件上传失败")

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
                    "type": 4,
                    "file_item": {
                        "media": {
                            "encrypt_query_param": enc_param,
                            "aes_key": aes_key_base64,
                            "encrypt_type": 1,
                        },
                        "file_name": os.path.basename(file_path),
                        "len": str(raw_size),
                    },
                }],
            },
            "base_info": self._build_base_info(),
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        return _curl(url, "POST", self._headers(), body, timeout=30)

    # ─────────────────────────────────────────────
    # 6. 快捷回复
    # ─────────────────────────────────────────────

    def reply_to_message(self, msg: ReceivedMessage, text: str) -> dict:
        return self.send_text(msg.from_user_id, text, msg.context_token)

    def reply_image_to_message(self, msg: ReceivedMessage, image_path: str) -> dict:
        return self.send_image(msg.from_user_id, msg.context_token, image_path)

    def reply_file_to_message(self, msg: ReceivedMessage, file_path: str) -> dict:
        return self.send_file(msg.from_user_id, msg.context_token, file_path)
