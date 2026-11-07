"""Apply Cisco IOS Loopback configuration using Ansible."""

import json
import os
import subprocess
import tempfile

from ipaddress import IPv4Interface
from pathlib import Path


ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"


def apply_interface(router, desired_interface, run_playbook=None):
    """Apply a desired interface state, preserving the test runner hook."""

    try:
        # แปลง IPv4/CIDR เป็น IP และ Netmask
        address = IPv4Interface(desired_interface["ipv4"])

        # เตรียมข้อมูลส่งไป Ansible
        variables = {
            "router": router,
            "interface_name": desired_interface["name"],
            "ipv4_address": str(address.ip),
            "netmask": str(address.network.netmask),
            "description": desired_interface["description"],
            "shutdown": desired_interface["admin_state"] == "down",
        }

        # ใช้ Fake Runner สำหรับ Public Tests
        if run_playbook is not None:
            run_playbook(variables)

        else:
            # สร้าง Inventory ชั่วคราวสำหรับ Router เป้าหมาย
            with tempfile.TemporaryDirectory() as directory:
                inventory = Path(directory) / "target.ini"

                inventory.write_text(
                    f"[routers]\ntarget ansible_host={router}\n",
                    encoding="utf-8",
                )

                # Environment สำหรับ Ansible
                env = {
                    **os.environ,
                    "ANSIBLE_HOST_KEY_CHECKING": "False",
                    "ANSIBLE_NOCOLOR": "1",
                }

                # เรียก Ansible Playbook
                result = subprocess.run(
                    [
                        "ansible-playbook",
                        "-i",
                        str(inventory),
                        "-i",
                        str(ANSIBLE_DIR / "inventory.ini"),
                        str(ANSIBLE_DIR / "apply_interface.yml"),
                        "--extra-vars",
                        json.dumps(variables),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=18,
                    env=env,
                )

                # ตรวจ Error จาก Ansible
                if result.returncode != 0:
                    output = (
                        (result.stdout or "")
                        + (result.stderr or "")
                    ).lower()

                    # Authentication Error
                    if any(s in output for s in (
                        "authentication failed",
                        "authentication failure",
                        "permission denied",
                        "invalid password",
                    )):
                        raise PermissionError(
                            "Ansible authentication failed"
                        )

                    # Connection Error
                    if any(s in output for s in (
                        "unreachable",
                        "connection refused",
                        "timed out",
                        "no route to host",
                        "could not resolve",
                        "connection failed",
                    )):
                        raise ConnectionError(
                            "Ansible connection failed"
                        )

                    raise RuntimeError(
                        "Ansible playbook failed"
                    )

        return {
            "status": "ok",
            "result": "applied"
        }

    except PermissionError:
        return {
            "status": "error",
            "result": "authentication_failed"
        }

    except (
        ConnectionError,
        TimeoutError,
        subprocess.TimeoutExpired
    ):
        return {
            "status": "error",
            "result": "connection_failed"
        }

    except Exception:
        return {
            "status": "error",
            "result": "backend_failed"
        }