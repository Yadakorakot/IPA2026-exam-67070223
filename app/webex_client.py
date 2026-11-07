
"""Part 4 student implementation."""

import os

import requests

WEBEX_API_BASE = 'https://webexapis.com/v1'


class WebexClient:
    def __init__(self, token=None, session=None):
        # TODO: implement according to Part 4 specification

        # ใช้ Token ที่ส่งมา หรืออ่านจาก Environment
        self.token = token if token is not None else os.getenv(
            "WEBEX_BOT_TOKEN"
        )

        # ถ้าไม่มี Token ให้แจ้ง Error
        if not self.token:
            raise PermissionError("WEBEX_BOT_TOKEN is required")

        # ใช้ Fake Session สำหรับ Tests หรือ requests จริง
        self.session = session if session is not None else requests.Session()

    @property
    def headers(self):
        # TODO: implement according to Part 4 specification

        # สร้าง Header สำหรับยืนยันตัวตนกับ Webex
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_message(self, message_id):
        # TODO: implement according to Part 4 specification

        # อ่านข้อมูลข้อความด้วย Message ID
        response = self.session.get(
            f"{WEBEX_API_BASE}/messages/{message_id}",
            headers=self.headers,
            timeout=10
        )

        # ตรวจ HTTP Error เช่น 401, 404, 500
        response.raise_for_status()

        # แปลง JSON เป็น Python Dictionary
        return response.json()

    def download_file(self, file_url):
        # TODO: implement according to Part 4 specification

        # ดาวน์โหลดไฟล์แนบจาก Webex
        response = self.session.get(
            file_url,
            headers=self.headers,
            timeout=10
        )

        response.raise_for_status()

        # ส่งข้อมูลไฟล์กลับเป็น bytes
        return response.content

    def send_message(self, room_id, text):
        # TODO: implement according to Part 4 specification

        # ส่งข้อความกลับไปยังห้อง Webex เดิม
        response = self.session.post(
            f"{WEBEX_API_BASE}/messages",
            headers=self.headers,
            json={
                "roomId": room_id,
                "text": text
            },
            timeout=10
        )

        response.raise_for_status()

        return response.json()
