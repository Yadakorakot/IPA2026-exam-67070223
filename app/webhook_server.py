
"""Part 4 student implementation."""

import json
import logging
import os

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from app.integration import process_request
from app.webex_client import WEBEX_API_BASE, WebexClient


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        # เก็บ Webex Client และ Bot Person ID
        self.client = client
        self.bot_person_id = bot_person_id

        # ใช้ Processor ที่กำหนด หรือใช้ Integration ของเรา
        self.processor = processor if processor is not None else process_request

    def handle_event(self, event):
        # ตรวจว่าเป็น Event messages/created หรือไม่
        if not isinstance(event, dict):
            return None

        if event.get("resource") != "messages":
            return None

        if event.get("event") != "created":
            return None

        data = event.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            return None

        # ป้องกัน Bot ตอบข้อความตัวเองซ้ำ
        if data.get("personId") == self.bot_person_id:
            return None

        # ดึงรายละเอียดข้อความจาก Webex API
        message = self.client.get_message(data["id"])

        if not isinstance(message, dict):
            return None

        # ตรวจผู้ส่งอีกครั้ง
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")
        if not room_id:
            return None

        mentions = message.get("mentionedPeople") or []
        files = message.get("files") or []

        # ถ้าแนบหลายไฟล์ ให้ตอบ Error ทันที
        if len(files) > 1:
            result = {
                "status": "error",
                "result": "multiple_attachments"
            }

        elif len(files) == 0:
            # ไม่มีไฟล์แนบ ส่ง None ให้ Validation ตรวจ
            result = self.processor(
                mentions,
                None,
                self.bot_person_id
            )

        else:
            # มีไฟล์เดียว ดาวน์โหลดและเก็บชั่วคราว
            with TemporaryDirectory() as temp_dir:
                file_path = Path(temp_dir) / "request.yaml"

                content = self.client.download_file(files[0])
                file_path.write_bytes(content)

                # ส่งไฟล์ไปตรวจและประมวลผล
                try:
                    result = self.processor(
                        mentions,
                        file_path,
                        self.bot_person_id
                    )
                except Exception:
                    logging.exception("Request processing failed")
                    result = {
                        "status": "error",
                        "result": "backend_failed"
                    }

            # TemporaryDirectory ลบไฟล์อัตโนมัติ

        # ส่ง JSON กลับไปยังห้อง Webex เดิม
        self.client.send_message(
            room_id,
            json.dumps(result, ensure_ascii=False)
        )

        return result


def make_http_handler(submit_event):
    # สร้าง HTTP Handler สำหรับ Webex Webhook
    class Handler(BaseHTTPRequestHandler):

        def send_json(self, status_code, data):
            body = json.dumps(data).encode("utf-8")

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()

            self.wfile.write(body)

        def do_GET(self):
            # Endpoint สำหรับตรวจสุขภาพ Server
            if self.path == "/health":
                self.send_json(200, {
                    "status": "ok",
                    "result": "healthy"
                })
            else:
                self.send_json(404, {
                    "status": "error",
                    "result": "not_found"
                })

        def do_POST(self):
            # รับเฉพาะ /webhook
            if self.path != "/webhook":
                self.send_json(404, {
                    "status": "error",
                    "result": "not_found"
                })
                return

            # ตรวจขนาด Request Body
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0

            if not 1 <= length <= 1000000:
                self.send_json(400, {
                    "status": "error",
                    "result": "invalid_event"
                })
                return

            # อ่าน JSON จาก Webex
            try:
                body = self.rfile.read(length)
                event = json.loads(body)

                if not isinstance(event, dict):
                    raise ValueError("Event must be a JSON object")

            except (ValueError, UnicodeError):
                self.send_json(400, {
                    "status": "error",
                    "result": "invalid_event"
                })
                return

            # ส่ง Event ไปประมวลผล
            submit_event(event)

            # ตอบรับ Event ทันที
            self.send_json(200, {
                "status": "ok",
                "result": "accepted"
            })

    return Handler


def main():
    # ตั้งค่า Logging
    logging.basicConfig(level=logging.INFO)

    # อ่าน Token ของ Bot จาก Environment
    client = WebexClient()

    # ใช้ Webex API อ่าน Person ID จริงของ Bot
    response = client.session.get(
        f"{WEBEX_API_BASE}/people/me",
        headers=client.headers,
        timeout=10
    )
    response.raise_for_status()

    bot_person_id = response.json()["id"]

    # สร้างตัวจัดการ Event
    handler = WebexEventHandler(
        client,
        bot_person_id
    )

    # ประมวลผลทีละ Event เพื่อไม่ให้แก้ Router ซ้อนกัน
    executor = ThreadPoolExecutor(max_workers=1)

    def process_event(event):
        try:
            handler.handle_event(event)
        except Exception:
            logging.exception("Webhook event failed")

    def submit_event(event):
        executor.submit(process_event, event)

    # เปิด HTTP Server
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "8000"))

    server = ThreadingHTTPServer(
        (host, port),
        make_http_handler(submit_event)
    )

    logging.info("Webhook server listening on %s:%s", host, port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping webhook server")
    finally:
        server.server_close()
        executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
