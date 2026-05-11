"""Capture selected WeChat group chats into the shared raw message store."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.recorder_service import RecorderService  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one capture iteration.")
    parser.add_argument("--forever", action="store_true", help="Run capture loop until process exits.")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--discover", action="store_true", help="Refresh the WeChat session list before capture.")
    parser.add_argument("--notify", action="store_true", help="Send collection notices when enabled for a group.")
    parser.add_argument("--tenant-id", default="", help="Tenant scope for recorder state and storage.")
    args = parser.parse_args()

    tenant_id = active_tenant_id(args.tenant_id or None)
    os.environ["WECHAT_KNOWLEDGE_TENANT"] = tenant_id
    service = RecorderService(tenant_id=tenant_id)
    interval = max(1, int(args.interval_seconds or 30))

    if args.forever:
        if args.discover:
            discover_payload = service.discover_sessions()
            print(json.dumps({"kind": "discover", "tenant_id": tenant_id, "result": discover_payload}, ensure_ascii=False), flush=True)
        index = 0
        while True:
            index += 1
            result = service.capture_selected_once(send_notifications=bool(args.notify))
            print(
                json.dumps(
                    {
                        "kind": "capture",
                        "tenant_id": tenant_id,
                        "iteration": index,
                        "captured_at": datetime.now().isoformat(timespec="seconds"),
                        "result": result,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            time.sleep(interval)

    events: list[dict[str, Any]] = []
    if args.discover:
        events.append({"kind": "discover", "tenant_id": tenant_id, "result": service.discover_sessions()})
    iterations = 1 if args.once else max(1, int(args.iterations or 1))
    for index in range(iterations):
        result = service.capture_selected_once(send_notifications=bool(args.notify))
        events.append({"kind": "capture", "tenant_id": tenant_id, "iteration": index + 1, "result": result})
        if index + 1 < iterations:
            time.sleep(interval)
    print(json.dumps({"ok": True, "tenant_id": tenant_id, "events": events}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
