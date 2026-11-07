
"""Part 4 student implementation."""

import json
import logging
import os
import hashlib
import hmac

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from app.integration import process_request
from app.webex_client import WEBEX_API_BASE, WebexClient


# ==========================================
# ตรวจสอบ Webex Webhook Signature
# ==========================================
def verify_webex_signature(body, headers, secret):
    """Verify Webex webhook signature."""

    if not secret:
        return False

    key = secret.encode("utf-8")

    # Webex Signature แบบใหม่
    signature = headers.get("X-Webex-Signature")

    if signature:
        algorithms = {
            "SHA-256": hashlib.sha256,
            "SHA-512": hashlib.sha512,
        }

        for part in signature.split(","):
            algorithm, sep, value = part.strip().partition("=")

            if not sep:
                continue

            hash_function = algorithms.get(algorithm.upper())

            if hash_function is None:
                continue

            expected = hmac.new(
                key,
                body,
                hash_function
            ).hexdigest()

            if hmac.compare_digest(expected, value.strip()):
                return True

        return False

    # Webex Signature แบบเดิม
    signature = headers.get("X-Spark-Signature", "")

    expected = hmac.new(
        key,
        body,
        hashlib.sha1
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ==========================================
# จัดการ Event จาก Webex
# ==========================================
class WebexEventHandler:

    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id

        self.processor = (
            processor
            if processor is not None
            else process_request
        )

    def handle_event(self, event):
        # ตรวจโครงสร้าง Event
        if not isinstance(event, dict):
            return None

        if event.get("resource") != "messages":
            return None

        if event.get("event") != "created":
            return None

        data = event.get("data")

        if not isinstance(data, dict):
            return None

        message_id = data.get("id")

        if not message_id:
            return None

        # ไม่ประมวลผลข้อความของ Bot เอง
        if data.get("personId") == self.bot_person_id:
            return None

        # ดึงข้อความจริงผ่าน Webex API
        message = self.client.get_message(message_id)

        if not isinstance(message, dict):
            return None

        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")

        if not room_id:
            return None

        mentions = message.get("mentionedPeople") or []
        files = message.get("files") or []

        # ==================================
        # แนบไฟล์มากกว่า 1 ไฟล์
        # ==================================
        if len(files) > 1:
            result = {
                "status": "error",
                "result": "multiple_attachments"
            }

        # ==================================
        # ไม่แนบไฟล์ YAML
        # ==================================
        elif len(files) == 0:
            result = self.processor(
                mentions,
                None,
                self.bot_person_id
            )

        # ==================================
        # แนบไฟล์ YAML จำนวน 1 ไฟล์
        # ==================================
        else:
            with TemporaryDirectory() as temp_dir:
                file_path = Path(temp_dir) / "request.yaml"

                # ดาวน์โหลดไฟล์จาก Webex
                content = self.client.download_file(files[0])

                # เก็บไฟล์ชั่วคราว
                file_path.write_bytes(content)

                try:
                    result = self.processor(
                        mentions,
                        file_path,
                        self.bot_person_id
                    )

                except Exception:
                    logging.exception(
                        "Request processing failed"
                    )

                    result = {
                        "status": "error",
                        "result": "backend_failed"
                    }

            # TemporaryDirectory ลบไฟล์ให้อัตโนมัติ

        # ส่งผลลัพธ์กลับไปห้องเดิม
        self.client.send_message(
            room_id,
            json.dumps(result, ensure_ascii=False)
        )

        return result


# ==========================================
# HTTP Server
# ==========================================
def make_http_handler(submit_event, signature_secret=None):
    """
    Create HTTP handler.

    signature_secret=None:
        ใช้สำหรับ Public Tests และ Image Check

    signature_secret มีค่า:
        ตรวจสอบ Webex Signature สำหรับ Server จริง
    """

    class Handler(BaseHTTPRequestHandler):

        # ส่งผลลัพธ์เป็น JSON
        def send_json(self, status_code, data):
            body = json.dumps(data).encode("utf-8")

            self.send_response(status_code)

            self.send_header(
                "Content-Type",
                "application/json"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()
            self.wfile.write(body)

        # ==================================
        # GET /health
        # ==================================
        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {
                    "status": "ok",
                    "result": "healthy"
                })
                return

            self.send_json(404, {
                "status": "error",
                "result": "not_found"
            })

        # ==================================
        # POST /webhook
        # ==================================
        def do_POST(self):

            # รับเฉพาะ /webhook
            if self.path != "/webhook":
                self.send_json(404, {
                    "status": "error",
                    "result": "not_found"
                })
                return

            # อ่าน Content-Length
            try:
                length = int(
                    self.headers.get("Content-Length", "0")
                )
            except (ValueError, TypeError):
                length = 0

            # จำกัดขนาด Request
            if not 1 <= length <= 1000000:
                self.send_json(400, {
                    "status": "error",
                    "result": "invalid_event"
                })
                return

            try:
                # อ่าน Raw Body
                body = self.rfile.read(length)

                # ตรวจ Signature เฉพาะเมื่อ Server
                # ถูกสร้างพร้อม signature_secret
                if signature_secret is not None:
                    if not verify_webex_signature(
                        body,
                        self.headers,
                        signature_secret
                    ):
                        self.send_json(401, {
                            "status": "error",
                            "result": "invalid_signature"
                        })
                        return

                # แปลง JSON
                event = json.loads(body)

                if not isinstance(event, dict):
                    raise ValueError(
                        "Event must be a JSON object"
                    )

            except (ValueError, UnicodeError):
                self.send_json(400, {
                    "status": "error",
                    "result": "invalid_event"
                })
                return

            # ส่ง Event เข้าคิว
            submit_event(event)

            # ตอบ Webex ว่ารับ Event แล้ว
            self.send_json(200, {
                "status": "ok",
                "result": "accepted"
            })

    return Handler


# ==========================================
# เริ่ม Webhook Server จริง
# ==========================================
def main():

    logging.basicConfig(level=logging.INFO)

    # อ่าน Secret สำหรับ Server จริง
    secret = os.getenv("WEBEX_WEBHOOK_SECRET", "")

    # Server จริงต้องมี Secret เสมอ
    if not secret:
        raise RuntimeError(
            "WEBEX_WEBHOOK_SECRET is required"
        )

    # สร้าง Webex Client
    client = WebexClient()

    # ดึง Person ID ของ Bot
    response = client.session.get(
        f"{WEBEX_API_BASE}/people/me",
        headers=client.headers,
        timeout=10
    )

    response.raise_for_status()
    bot_person_id = response.json()["id"]

    # สร้าง Event Handler
    handler = WebexEventHandler(
        client,
        bot_person_id
    )

    # ประมวลผลทีละ Event
    executor = ThreadPoolExecutor(max_workers=1)

    def process_event(event):
        try:
            handler.handle_event(event)
        except Exception:
            logging.exception(
                "Webhook event failed"
            )

    def submit_event(event):
        executor.submit(process_event, event)

    # อ่าน Host และ Port
    host = os.getenv(
        "WEBHOOK_HOST",
        "0.0.0.0"
    )

    port = int(
        os.getenv("WEBHOOK_PORT", "8000")
    )

    # สร้าง Server พร้อมเปิดตรวจ Signature
    server = ThreadingHTTPServer(
        (host, port),
        make_http_handler(
            submit_event,
            signature_secret=secret
        )
    )

    logging.info(
        "Webhook server listening on %s:%s",
        host,
        port
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        logging.info(
            "Stopping webhook server"
        )

    finally:
        server.server_close()
        executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
