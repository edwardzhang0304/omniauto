"""Config-driven guarded WeChat customer-service workflow.

This workflow is the next layer above the single-target minimal loop. It can
poll multiple whitelisted conversations, aggregate recent unprocessed messages,
apply deterministic rules, enforce simple rate limits, optionally send, verify
by reading back, and append audit events.

Default behavior is safe:
- one pass only, unless configured or overridden;
- dry-run unless ``--send`` is passed;
- target conversations must be explicitly enabled in the config;
- fallback replies are blocked unless allowed in the config or CLI.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
ADAPTERS_ROOT = APP_ROOT / "adapters"
WORKFLOWS_ROOT = Path(__file__).resolve().parent
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, APP_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_data_capture import append_customer_row, extract_customer_data
from customer_intent_assist import (
    analyze_intent,
    build_llm_prompt_pack,
    call_deepseek_advisory,
    validate_llm_candidate,
)
from customer_service_loop import BOT_PREFIX, ReplyDecision, decide_reply, format_reply, load_rules
from apps.wechat_ai_customer_service.cloud_gate import cloud_gate_status, cloud_required_enabled
from apps.wechat_ai_customer_service.llm_config import resolve_effective_llm_provider
from apps.wechat_ai_customer_service.platform_safety_rules import guard_term_set, load_platform_safety_rules
from knowledge_loader import build_evidence_pack
from llm_intent_router import route_intent, IntentRouteResult
from llm_reply_synthesis import maybe_synthesize_reply
from product_knowledge import decide_product_knowledge_reply, load_product_knowledge
from rag_answer_layer import maybe_build_rag_reply
from rag_experience_store import record_rag_reply_experience
from realtime_reply_router import (
    build_synthesis_config_for_route,
    choose_reply_variant,
    de_template_reply_text,
    decide_realtime_reply_route,
    initial_token_budget,
    maybe_build_realtime_reply,
    reply_similarity,
    update_token_budget_from_synthesis,
)
from reply_style_adapter import adapt_reply_style, infer_source_channel
from wechat_connector import FILE_TRANSFER_ASSISTANT, ROOT, WeChatConnector
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime import (
    summarize_listener_result,
    write_runtime_status,
)
from admin_backend.services.customer_service_settings import CustomerServiceSettings
from apps.wechat_ai_customer_service.admin_backend.services.knowledge_contamination_guard import (
    message_learning_exclusion_reason,
    text_has_model_reply_marker,
    text_has_test_marker,
)
from admin_backend.services.raw_message_store import RawMessageStore
from apps.wechat_ai_customer_service.admin_backend.services.session_monitor import SessionMonitor
from apps.wechat_ai_customer_service.admin_backend.services.customer_profile_store import CustomerProfileStore
from apps.wechat_ai_customer_service.admin_backend.services.work_queue import WorkQueueService
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id


CONFIG_PATH = ROOT / "apps/wechat_ai_customer_service/configs/default.example.json"
MAX_STORED_IDS = 1000
DEFAULT_MAX_BATCH_MESSAGES = 8


EXPLICIT_HANDOFF_PATTERNS = (
    r"转人工",
    r"人工客服",
    r"真人客服",
    r"线路切换",
    r"请联系顾问",
    r"(销售|顾问|同事|专员).{0,6}(联系|跟进|对接|接管)",
    r"(转给|交给).{0,6}(同事|顾问|专员|客服)",
)
PRICE_HARD_BOUNDARY_TERMS = ("价格", "报价", "最低", "底价", "优惠", "折扣", "少点", "便宜", "贷款", "金融", "包过", "首付", "月供")
APPOINTMENT_TERMS = ("试驾", "到店", "看车", "订金", "定金", "留车", "锁车", "预约", "周末", "周六", "周日", "上午", "下午", "几点", "安排", "过去", "来店", "门店")
LOCATION_CONTACT_TERMS = ("门店地址", "店地址", "地址", "导航", "位置", "在哪", "哪里", "找谁", "联系人", "对接人", "到了找")
LOCATION_CONTACT_STRONG_TERMS = ("门店地址", "店地址", "地址", "导航", "位置", "在哪", "哪里", "找谁", "对接人", "到了找", "到店找", "跑错")
LOCATION_VISIT_CONTEXT_TERMS = ("门店", "店里", "到店", "到了", "过去", "看车", "试驾", "来店", "导航", "地址")
CONTACT_DATA_TERMS = ("电话", "手机号", "联系方式", "我叫", "联系人", "姓名", "先生", "女士")
AFTER_SALES_TERMS = ("赔偿", "退款", "纠纷", "投诉", "事故", "水泡", "火烧", "过户", "上牌")
TRADE_IN_TERMS = ("置换", "抵车款", "抵多少", "抵扣", "抵一点", "卖车", "收车", "旧车", "估价", "估个", "估一下", "估一", "怎么估")
INTERNAL_PROBE_TERMS = ("系统提示词", "内部规则", "API密钥", "api密钥", "api key", "密钥", "prompt", "是不是ai", "是不是AI", "是不是机器人", "机器人")
NEW_ENERGY_TERMS = ("新能源", "电池", "三电", "续航", "充电", "混动", "DM-i", "dmi", "插混")
DOCUMENT_TERMS = ("合同", "发票", "开票", "抬头", "税号", "少开", "低开", "保险")
OFF_TOPIC_TERMS = ("外挂", "破解", "脚本", "刷单", "灰产", "游戏外挂")


@dataclass(frozen=True)
class TargetConfig:
    name: str
    enabled: bool
    exact: bool
    allow_self_for_test: bool
    max_batch_messages: int


@dataclass(frozen=True)
class BatchSelection:
    batch: list[dict[str, Any]]
    overflow_messages: list[dict[str, Any]]
    eligible_count: int
    max_batch_messages: int

    @property
    def truncated(self) -> bool:
        return bool(self.overflow_messages)


class StateLock:
    """Small cross-process lock for workflow state writes."""

    def __init__(self, path: Path, timeout_seconds: int, stale_seconds: int) -> None:
        self.path = path
        self.timeout_seconds = max(1, timeout_seconds)
        self.stale_seconds = max(60, stale_seconds)
        self.fd: int | None = None

    def __enter__(self) -> "StateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            self.remove_stale_lock()
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = f"pid={os.getpid()}\ncreated_at={datetime.now().isoformat(timespec='seconds')}\n"
                os.write(self.fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Workflow state is locked: {self.path}")
                time.sleep(0.5)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def remove_stale_lock(self) -> None:
        try:
            age_seconds = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age_seconds >= self.stale_seconds:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        # If lock holder PID is dead, remove immediately regardless of age
        if self._lock_holder_dead():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _lock_holder_dead(self) -> bool:
        try:
            content = self.path.read_text(encoding="utf-8")
        except (OSError, FileNotFoundError):
            return True
        for line in content.splitlines():
            if line.startswith("pid="):
                try:
                    pid = int(line.split("=", 1)[1].strip())
                except ValueError:
                    continue
                if pid <= 0:
                    return True
                try:
                    os.kill(pid, 0)
                    return False
                except OSError:
                    return True
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--once", action="store_true", help="Run exactly one iteration.")
    parser.add_argument("--iterations", type=int, help="Override configured iteration count.")
    parser.add_argument("--interval-seconds", type=int, help="Override configured poll interval.")
    parser.add_argument("--send", action="store_true", help="Actually send replies.")
    parser.add_argument(
        "--allow-fallback-send",
        action="store_true",
        help="Allow sending default replies when no rule matched.",
    )
    parser.add_argument(
        "--mark-dry-run",
        action="store_true",
        help="Mark planned dry-run batches as processed.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Mark existing text messages as processed without replying.",
    )
    parser.add_argument(
        "--write-data",
        action="store_true",
        help="Write extracted customer data to Excel.",
    )
    parser.add_argument(
        "--target",
        action="append",
        help=(
            "Temporary runtime target for bootstrap/dry-run checks. "
            "Send mode is blocked for runtime targets unless they are in config."
        ),
    )
    args = parser.parse_args()

    gate_error = cloud_gate_error_result()
    if gate_error is not None:
        write_runtime_status(
            "stopped",
            str(gate_error.get("message") or "云端授权未通过"),
            cloud_gate=gate_error.get("cloud_gate"),
        )
        print_json(gate_error)
        return 1

    try:
        write_runtime_status("thinking", "正在读取微信消息并调用必要的大模型。")
        result = run_workflow(args)
    except Exception as exc:
        write_runtime_status("idle", "本轮处理出错，监听会自动重试。", last_error=repr(exc))
        result = {"ok": False, "error": repr(exc)}
    else:
        write_runtime_status("idle", "本轮微信消息处理完成。", **summarize_listener_result(result))

    print_json(result)
    return 0 if result.get("ok") else 1


def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    gate_error = cloud_gate_error_result()
    if gate_error is not None:
        return gate_error

    config = load_config(args.config)
    config = apply_local_customer_service_settings(config)
    session_routing = config.get("_local_customer_service_session_routing", {}) or {}
    if not isinstance(session_routing, dict):
        session_routing = {}
    respond_all_unread_sessions = bool(session_routing.get("respond_all_unread_sessions", False))
    managed_session_targets = bool(session_routing.get("managed", False))
    ignored_session_names = {
        str(item).strip()
        for item in session_routing.get("ignored_names", []) or []
        if str(item).strip()
    }
    state_path = resolve_path(config.get("state_path"))
    audit_path = resolve_path(config.get("audit_log_path"))
    rules_path = config.get("rules_path")
    rules = load_rules(resolve_path(rules_path)) if rules_path else config

    iterations = resolve_iterations(args, config)
    interval = int(args.interval_seconds or config.get("poll", {}).get("interval_seconds", 15))
    targets = parse_targets(
        config,
        allow_empty=bool(respond_all_unread_sessions or managed_session_targets),
    )
    if args.target:
        if args.send:
            configured_names = {target.name for target in targets}
            runtime_names = {str(name).strip() for name in args.target if str(name).strip()}
            non_configured = sorted(runtime_names - configured_names)
            if non_configured:
                raise ValueError(
                    "Runtime --target is only allowed for bootstrap/dry-run. "
                    "Add runtime targets to config before --send."
                )
        targets = parse_runtime_targets(args.target, config_targets=targets)
    lock_settings = config.get("state_lock", {}) or {}
    with StateLock(
        state_path.with_suffix(state_path.suffix + ".lock"),
        timeout_seconds=int(lock_settings.get("timeout_seconds", 120)),
        stale_seconds=int(lock_settings.get("stale_seconds", 900)),
    ):
        connector = WeChatConnector()
        state = load_state(state_path)

        status = connector.require_online()
        summary: dict[str, Any] = {
            "ok": True,
            "dry_run": not args.send,
            "iterations": iterations,
            "status": status,
            "targets": [target.name for target in targets],
            "events": [],
        }

        multi_target_cfg = config.get("multi_target") or {}
        use_multi_target = bool(multi_target_cfg.get("enabled")) and not args.target
        session_monitor: SessionMonitor | None = None
        if use_multi_target:
            whitelist = set() if respond_all_unread_sessions else {t.name for t in targets}
            session_monitor = SessionMonitor(
                whitelist=whitelist,
                blacklist=ignored_session_names,
                max_targets_per_iteration=int(multi_target_cfg.get("max_targets_per_iteration", 5)),
                min_switch_interval_seconds=int(multi_target_cfg.get("min_switch_interval_seconds", 2)),
            )

        for iteration in range(iterations):
            iteration_events = []
            if use_multi_target and session_monitor is not None:
                active = session_monitor.poll(connector)
                dynamic_targets = build_iteration_targets(
                    config_targets=targets,
                    active_targets=active,
                    multi_target_cfg=multi_target_cfg,
                    allow_dynamic_active_targets=respond_all_unread_sessions,
                    blocked_names=ignored_session_names,
                )
                summary["active_target_names"] = [str(item.name) for item in active]
                summary["iteration_target_names"] = [str(item.name) for item in dynamic_targets]
                summary["active_sessions"] = session_monitor.all_sessions()
            else:
                dynamic_targets = targets

            for target in dynamic_targets:
                if args.bootstrap:
                    event = bootstrap_target(connector, target, state, config)
                else:
                    event = process_target(
                        connector=connector,
                        target=target,
                        config=config,
                        rules=rules,
                        state=state,
                        send=bool(args.send),
                        write_data=bool(args.write_data),
                        allow_fallback_send=bool(args.allow_fallback_send),
                        mark_dry_run=bool(args.mark_dry_run),
                    )
                event["iteration"] = iteration + 1
                append_audit(audit_path, event)
                iteration_events.append(event)
                if use_multi_target and session_monitor is not None:
                    session_monitor.reset_unread(target.name)
            save_state(state_path, state)
            summary["events"].extend(iteration_events)
            if iteration < iterations - 1:
                time.sleep(max(1, interval))

    return summary


def cloud_gate_error_result() -> dict[str, Any] | None:
    if not cloud_required_enabled():
        return None
    gate = cloud_gate_status()
    if gate.get("ok"):
        return None
    message = "云端授权未通过，当前自动客服已锁定。请先连接服务端并刷新共享行业知识库。"
    return {
        "ok": False,
        "error": "cloud_authoritative_access_required",
        "message": message,
        "cloud_gate": gate,
    }


def _enqueue_post_reply_work(
    target: TargetConfig,
    config: dict[str, Any],
    raw_capture: dict[str, Any],
    data_capture: dict[str, Any],
) -> None:
    """Enqueue background tasks after a reply has been sent."""
    try:
        tenant_id = active_tenant_id()
        queue = WorkQueueService(tenant_id=tenant_id)

        # 1. experience_interpretation — raw message batch LLM processing
        batch_id = str((raw_capture or {}).get("batch", {}).get("batch_id") or "")
        raw_settings = config.get("raw_messages", {}) or {}
        if batch_id and raw_settings.get("auto_learn", False):
            queue.enqueue(
                kind="experience_interpretation",
                payload={
                    "batch_id": batch_id,
                    "tenant_id": tenant_id,
                    "use_llm": raw_settings.get("use_llm", True) is not False,
                },
                queue="customer_service",
                dedupe_key=f"exp_interp:{tenant_id}:{batch_id}",
                priority=4,
            )

        # 2. customer_data_sync — Excel write or other data persistence
        if data_capture.get("enabled") and data_capture.get("is_customer_data"):
            queue.enqueue(
                kind="customer_data_sync",
                payload={
                    "target_name": target.name,
                    "tenant_id": tenant_id,
                    "data_capture": {
                        "fields": data_capture.get("fields", {}),
                        "message_ids": data_capture.get("message_ids", []),
                        "raw_text": data_capture.get("raw_text", ""),
                    },
                },
                queue="customer_service",
                dedupe_key=f"data_sync:{tenant_id}:{target.name}:{','.join(str(item) for item in data_capture.get('message_ids', []))}",
                priority=3,
            )

        # 3. customer_profile_analysis — async LLM tag extraction
        profile_cfg = config.get("customer_profiles") or {}
        if isinstance(profile_cfg, dict) and profile_cfg.get("analysis", {}).get("enabled", True):
            queue.enqueue(
                kind="customer_profile_analysis",
                payload={
                    "target_name": target.name,
                    "tenant_id": tenant_id,
                },
                queue="customer_service",
                dedupe_key=f"profile_analysis:{tenant_id}:{target.name}",
                priority=6,
            )

        # 4. raw_message_archive — periodic cleanup (deduped, low priority)
        queue.enqueue(
            kind="raw_message_archive",
            payload={"tenant_id": tenant_id, "days": 30},
            queue="customer_service",
            dedupe_key=f"raw_archive:{tenant_id}",
            priority=8,
        )
    except Exception:
        # Work queue failures must never block the reply path
        pass


def process_target(
    connector: WeChatConnector,
    target: TargetConfig,
    config: dict[str, Any],
    rules: dict[str, Any],
    state: dict[str, Any],
    send: bool,
    write_data: bool,
    allow_fallback_send: bool,
    mark_dry_run: bool,
) -> dict[str, Any]:
    target_state = state.setdefault("targets", {}).setdefault(
        target.name,
        {
            "processed_message_ids": [],
            "handoff_message_ids": [],
            "sent_replies": [],
            "reply_timestamps": [],
        },
    )
    payload = connector.get_messages(target.name, exact=target.exact)
    if not payload.get("ok"):
        return base_event(target, "error", {"messages": payload})
    console_settings = config.get("_local_customer_service_settings", {}) or {}
    if console_settings.get("enabled") is False:
        raw_capture = maybe_record_raw_messages(target, config, payload.get("messages", []) or [])
        return base_event(target, "skipped", {"reason": "customer_service_disabled", "raw_capture": raw_capture})
    if str(console_settings.get("reply_mode") or "") == "record_only":
        raw_capture = maybe_record_raw_messages(target, config, payload.get("messages", []) or [])
        return base_event(target, "skipped", {"reason": "record_only_mode", "raw_capture": raw_capture})
    if str(console_settings.get("reply_mode") or "") == "manual_assist":
        send = False

    payload = maybe_enrich_messages_with_history(
        connector=connector,
        target=target,
        config=config,
        payload=payload,
        target_state=target_state,
    )
    raw_capture = maybe_record_raw_messages(target, config, payload.get("messages", []) or [])
    selection = select_batch_details(
        payload.get("messages", []) or [],
        target_state=target_state,
        allow_self_for_test=target.allow_self_for_test,
        max_batch_messages=target.max_batch_messages,
        config=config,
    )
    batch = selection.batch
    if not batch:
        return base_event(
            target,
            "skipped",
            {
                "reason": "no eligible unprocessed text messages",
                "raw_capture": raw_capture,
                "batch_selection": batch_selection_payload(selection),
            },
        )

    # Load or create customer profile
    profile_store = CustomerProfileStore()
    profile = profile_store.get_or_create(target_name=target.name, display_name=target.name)
    profile_store.increment_message_stats(target_name=target.name, is_reply=False)

    semantic_batch_plan = plan_message_batch_semantics(batch, config)
    combined = str(semantic_batch_plan.get("combined_text") or "\n".join(str(item.get("content") or "") for item in batch))
    message_ids = [str(item.get("id") or "") for item in batch]
    write_runtime_status(
        "thinking",
        f"正在处理「{target.name}」的 {len(batch)} 条新消息。",
        target=target.name,
        message_count=len(batch),
        message_ids=message_ids,
    )
    if send:
        backoff = get_rate_limit_backoff(target_state, message_ids)
        if backoff:
            return base_event(
                target,
                "skipped",
                {
                    "reason": "rate_limit_backoff_active",
                    "message_ids": message_ids,
                    "message_count": len(batch),
                    "retry_after_at": backoff.get("retry_after_at"),
                    "rate_limit_reason": backoff.get("reason"),
                },
            )

    # 1. Build evidence pack for intent analysis and synthesis
    evidence_pack = build_evidence_pack(
        combined,
        context=conversation_context_from_product_result(
            target_state.get("conversation_context", {}) or {}
        ),
    )

    # 2. LLM intent routing — replaces keyword-based customer_data gate
    intent_result = route_intent(
        combined=combined,
        config=config,
        evidence_pack=evidence_pack,
        target_state=target_state,
    )

    # 3. Branch by intent
    data_capture: dict[str, Any] = {"enabled": False}
    product_knowledge: dict[str, Any] | None = None
    decision: ReplyDecision

    if intent_result.intent == "customer_data_provide":
        data_capture = maybe_capture_customer_data(
            config=config,
            target_state=target_state,
            target=target,
            batch=batch,
            combined=combined,
            write_data=False,
            intent_result=intent_result,
        )
        if data_capture.get("enabled"):
            data_capture["write_requested"] = write_data
        decision = decide_reply_with_data_capture(
            combined, rules, config, data_capture, product_knowledge
        )

    elif intent_result.intent == "handoff_request":
        decision = ReplyDecision(
            reply_text=handoff_acknowledgement_text(config),
            rule_name="handoff_request",
            matched=True,
            need_handoff=True,
            reason="customer_explicit_handoff_intent",
        )

    else:
        # product_inquiry, general_chat, greeting, unclear
        # Extract data fields without blocking the flow
        data_capture = maybe_capture_customer_data(
            config=config,
            target_state=target_state,
            target=target,
            batch=batch,
            combined=combined,
            write_data=False,
            intent_result=intent_result,
        )
        if data_capture.get("enabled"):
            data_capture["write_requested"] = write_data

        product_knowledge = maybe_match_product_knowledge(
            config, target_state, combined, data_capture
        )
        update_conversation_context(target_state, product_knowledge)
        decision = decide_reply_with_data_capture(
            combined, rules, config, data_capture, product_knowledge
        )
    reply_prefix = configured_reply_prefix(config)
    reply_text = format_reply(decision.reply_text, reply_prefix)
    fallback_allowed = bool(allow_fallback_send or config.get("reply", {}).get("allow_fallback_send"))

    event = base_event(
        target,
        "planned",
        {
            "message_ids": message_ids,
            "message_count": len(batch),
            "combined_content": combined,
            "decision": {
                **decision.__dict__,
                "raw_reply_text": decision.reply_text,
                "reply_text": reply_text,
            },
            "data_capture": data_capture,
            "raw_capture": raw_capture,
            "batch_selection": batch_selection_payload(selection),
            "semantic_batch_plan": semantic_batch_plan,
            "history_backfill": payload.get("_history_backfill", {}),
            "product_knowledge": product_knowledge,
            "intent_result": intent_result.to_dict(),
            "intent_assist": skipped_intent_assist(config, "not_evaluated_yet"),
            "dry_run": not send,
        },
    )

    rate_check = check_rate_limit(target_state, config)
    if send and not rate_check["allowed"]:
        return handle_rate_limit_block(
            connector=connector,
            target=target,
            config=config,
            target_state=target_state,
            event=event,
            message_ids=message_ids,
            rate_check=rate_check,
        )

    clear_rate_limit_backoff(target_state, message_ids)

    event["intent_assist"] = maybe_analyze_intent(
        config=config,
        combined=combined,
        decision=decision,
        reply_text=reply_text,
        data_capture=data_capture,
        product_knowledge=product_knowledge,
    )
    rag_reply = maybe_build_rag_reply(
        config=config,
        text=combined,
        decision=decision,
        reply_text=reply_text,
        intent_assist=event["intent_assist"],
        product_knowledge=product_knowledge,
        data_capture=data_capture,
    )
    event["rag_reply"] = rag_reply
    if rag_reply.get("applied"):
        decision = ReplyDecision(
            reply_text=str(rag_reply.get("raw_reply_text") or ""),
            rule_name=str(rag_reply.get("rule_name") or "rag_context_reply"),
            matched=True,
            need_handoff=bool(rag_reply.get("needs_handoff")),
            reason=str(rag_reply.get("reason") or "safe_rag_context_reply"),
        )
        reply_text = str(rag_reply.get("reply_text") or reply_text)
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": reply_text,
        }
    if rag_reply.get("applied") and (config.get("rag_response", {}) or {}).get("skip_llm_after_apply", True):
        llm_settings = (config.get("intent_assist", {}) or {}).get("llm_advisory", {}) or {}
        llm_reply = {
            "enabled": bool(llm_settings.get("enabled", False)),
            "apply_to_reply": bool(llm_settings.get("apply_to_reply", False)),
            "applied": False,
            "reason": "skipped_after_rag_reply",
        }
    else:
        llm_reply = maybe_apply_llm_reply(
            config=config,
            decision=decision,
            reply_text=reply_text,
            intent_assist=event["intent_assist"],
            product_knowledge=product_knowledge,
            data_capture=data_capture,
        )
    event["llm_reply"] = llm_reply
    if llm_reply.get("applied"):
        decision = ReplyDecision(
            reply_text=str(llm_reply.get("raw_reply_text") or ""),
            rule_name=str(llm_reply.get("rule_name") or "llm_boundary_reply"),
            matched=True,
            need_handoff=bool(llm_reply.get("needs_handoff")),
            reason=str(llm_reply.get("reason") or "llm_boundary_reply"),
        )
        reply_text = str(llm_reply.get("reply_text") or reply_text)
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": reply_text,
        }

    recent_reply_texts = recent_customer_visible_reply_texts(target_state)
    realtime_combined = build_realtime_context_combined(combined, target_state)
    event["realtime_context"] = {
        "applied": realtime_combined != combined,
        "text": realtime_combined[:1200] if realtime_combined != combined else "",
    }
    runtime_route = decide_realtime_reply_route(
        config=config,
        combined=realtime_combined,
        decision=decision,
        intent_result=intent_result,
        intent_assist=event["intent_assist"],
        rag_reply=rag_reply,
        llm_reply=llm_reply,
        product_knowledge=product_knowledge,
        data_capture=data_capture,
        evidence_pack=evidence_pack,
        recent_reply_texts=recent_reply_texts,
    )
    event["runtime_route"] = runtime_route
    if runtime_route.get("level") == "L0" and runtime_route.get("reason") == "deterministic_handoff_or_high_risk_boundary":
        decision = ReplyDecision(
            reply_text=decision.reply_text,
            rule_name=decision.rule_name,
            matched=decision.matched,
            need_handoff=True,
            reason=str(runtime_route.get("reason") or decision.reason),
        )
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": reply_text,
        }
    token_budget = initial_token_budget(runtime_route)
    realtime_reply = maybe_build_realtime_reply(
        config=config,
        route=runtime_route,
        combined=realtime_combined,
        evidence_pack=evidence_pack,
        current_reply_text=reply_text,
        recent_reply_texts=recent_reply_texts,
    )
    event["realtime_reply"] = realtime_reply
    if realtime_reply.get("applied"):
        decision = ReplyDecision(
            reply_text=str(realtime_reply.get("raw_reply_text") or ""),
            rule_name=str(realtime_reply.get("rule_name") or "realtime_local_reply"),
            matched=True,
            need_handoff=False,
            reason=str(realtime_reply.get("reason") or "realtime_local_reply"),
        )
        reply_text = format_reply(str(realtime_reply.get("raw_reply_text") or ""), configured_reply_prefix(config))
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": reply_text,
        }
        clear_no_relevant_handoff_after_safe_realtime_reply(event["intent_assist"], realtime_reply)

    synthesis_enabled = bool((config.get("llm_reply_synthesis", {}) or {}).get("enabled", False))
    explicit_synthesis_override = llm_synthesis_explicit_override(config)
    if runtime_route.get("enabled") is not False and not runtime_route.get("foreground_llm_allowed") and not explicit_synthesis_override:
        llm_synthesis = {
            "enabled": synthesis_enabled,
            "applied": False,
            "reason": "skipped_by_realtime_route",
            "route_level": runtime_route.get("level"),
            "route_reason": runtime_route.get("reason"),
        }
    else:
        synthesis_config = build_synthesis_config_for_route(config, runtime_route)
        llm_synthesis = maybe_synthesize_reply(
            config=synthesis_config,
            target_name=target.name,
            target_state=target_state,
            batch=batch,
            combined=combined,
            decision=decision,
            reply_text=reply_text,
            intent_assist=event["intent_assist"],
            rag_reply=rag_reply,
            llm_reply=llm_reply,
            product_knowledge=product_knowledge,
            data_capture=data_capture,
            raw_capture=raw_capture,
            customer_profile=profile,
        )
    token_budget = update_token_budget_from_synthesis(token_budget, llm_synthesis)
    event["token_budget"] = token_budget
    event["llm_reply_synthesis"] = llm_synthesis
    if llm_synthesis.get("applied"):
        decision = ReplyDecision(
            reply_text=str(llm_synthesis.get("raw_reply_text") or ""),
            rule_name=str(llm_synthesis.get("rule_name") or "llm_synthesis_reply"),
            matched=True,
            need_handoff=bool(llm_synthesis.get("needs_handoff")),
            reason=str(llm_synthesis.get("reason") or "guarded_llm_synthesis"),
        )
        if decision.need_handoff:
            handoff_raw = str(llm_synthesis.get("raw_reply_text") or "").strip()
            if handoff_raw:
                reply_text = format_reply(handoff_raw, configured_reply_prefix(config))
            else:
                reply_text = format_reply(handoff_acknowledgement_text(config), configured_reply_prefix(config))
        else:
            reply_text = format_reply(str(llm_synthesis.get("raw_reply_text") or ""), configured_reply_prefix(config))
            clear_no_relevant_handoff_after_safe_synthesis(event["intent_assist"], llm_synthesis)
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": reply_text,
        }

    style_channel = infer_source_channel(
        realtime_reply=realtime_reply,
        llm_synthesis=llm_synthesis,
        llm_reply=llm_reply,
        rag_reply=rag_reply,
    )
    style_adaptation = adapt_reply_style(
        config=config,
        customer_message=combined,
        reply_text=reply_text,
        source_channel=style_channel,
        evidence_pack=evidence_pack,
        recent_reply_texts=recent_reply_texts,
        needs_handoff=bool(decision.need_handoff),
    )
    event["reply_style_adapter"] = style_adaptation
    if style_adaptation.get("applied"):
        decision = ReplyDecision(
            reply_text=str(style_adaptation.get("raw_reply_text") or ""),
            rule_name=decision.rule_name,
            matched=decision.matched,
            need_handoff=decision.need_handoff,
            reason=str(decision.reason or "") + "+style_adapter",
        )
        reply_text = str(style_adaptation.get("reply_text") or reply_text)
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": reply_text,
        }

    if send:
        freshness = detect_newer_messages_before_send(
            connector=connector,
            target=target,
            target_state=target_state,
            batch=batch,
            config=config,
        )
        event["freshness_check"] = freshness
        if freshness.get("has_newer_messages"):
            event["action"] = "skipped"
            event["reason"] = "newer_message_arrived_during_reply_build"
            write_runtime_status(
                "idle",
                "客户刚刚又发了新消息，本轮旧回复已暂停，下一轮会合并最新上下文再答。",
                target=target.name,
                last_action="skipped",
                last_reason=event["reason"],
            )
            return event

    handoff_enabled = (config.get("handoff", {}) or {}).get("enabled", True) is not False
    operator_handoff_required = should_operator_handoff(
        decision,
        product_knowledge,
        fallback_allowed,
        intent_assist=event["intent_assist"],
    )
    operator_handoff = handoff_enabled and operator_handoff_required
    prebuilt_handoff_reason = ""
    prebuilt_handoff_reply_text = ""
    if operator_handoff_required:
        prebuilt_handoff_reason = handoff_reason(decision, product_knowledge, intent_assist=event["intent_assist"])
        prebuilt_handoff_reply_text = build_operator_handoff_reply_text(
            config,
            decision,
            product_knowledge,
            reply_text,
            intent_assist=event["intent_assist"],
            combined=combined,
        )
        prebuilt_handoff_reply_text = _apply_greeting(
            prebuilt_handoff_reply_text,
            profile,
            config,
            target_state=target_state,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
        )
        prebuilt_handoff_reply_text = sanitize_customer_visible_reply_text(
            prebuilt_handoff_reply_text,
            config=config,
            combined=combined,
            reason=prebuilt_handoff_reason,
            force_handoff_style=True,
            recent_reply_texts=recent_reply_texts,
        )
        handoff_style_adaptation = adapt_reply_style(
            config=config,
            customer_message=combined,
            reply_text=prebuilt_handoff_reply_text,
            source_channel="handoff",
            evidence_pack=evidence_pack,
            recent_reply_texts=recent_reply_texts,
            needs_handoff=True,
        )
        event["reply_style_adapter_handoff"] = handoff_style_adaptation
        if handoff_style_adaptation.get("applied"):
            prebuilt_handoff_reply_text = str(handoff_style_adaptation.get("reply_text") or prebuilt_handoff_reply_text)
        handoff_naturalness = polish_customer_visible_reply_text(
            prebuilt_handoff_reply_text,
            config=config,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
        )
        event["outbound_naturalness_handoff"] = handoff_naturalness
        if handoff_naturalness.get("applied"):
            prebuilt_handoff_reply_text = str(handoff_naturalness.get("reply_text") or prebuilt_handoff_reply_text)
        decision = ReplyDecision(
            reply_text=split_reply_prefix(prebuilt_handoff_reply_text, config)[1],
            rule_name=decision.rule_name,
            matched=decision.matched,
            need_handoff=True,
            reason=prebuilt_handoff_reason,
        )
        reply_text = prebuilt_handoff_reply_text
        event["decision"] = {
            **decision.__dict__,
            "raw_reply_text": decision.reply_text,
            "reply_text": prebuilt_handoff_reply_text,
            "handoff_reason": prebuilt_handoff_reason,
        }
    if send and operator_handoff_required and not handoff_enabled:
        event["action"] = "skipped"
        event["reason"] = "operator_handoff_disabled"
        event["intent_assist"]["handoff_disabled"] = True
        return event
    if send and operator_handoff:
        reason = prebuilt_handoff_reason or handoff_reason(decision, product_knowledge, intent_assist=event["intent_assist"])
        if data_capture.get("enabled") and data_capture.get("is_customer_data"):
            data_capture["write_requested"] = write_data
            if data_capture.get("complete") and write_data:
                if customer_data_write_allowed_before_handoff(event["intent_assist"]):
                    write_customer_data_if_ready(config, target, data_capture)
                    if not data_capture.get("write_result", {}).get("ok"):
                        event["data_capture"] = data_capture
                        event["action"] = "blocked"
                        event["reason"] = "customer data was not written before operator handoff"
                        event["intent_assist"] = skipped_intent_assist(config, "customer_data_write_blocked_before_handoff")
                        return event
                else:
                    data_capture["write_skipped_reason"] = "operator_handoff_required"
            elif data_capture.get("complete"):
                data_capture["write_skipped_reason"] = "operator_handoff_required_write_data_false"
            else:
                data_capture["write_skipped_reason"] = "operator_handoff_required"
            event["data_capture"] = data_capture
        handoff_reply_text = prebuilt_handoff_reply_text or build_operator_handoff_reply_text(
            config,
            decision,
            product_knowledge,
            reply_text,
            intent_assist=event["intent_assist"],
            combined=combined,
        )
        event["decision"]["need_handoff"] = True
        event["decision"]["handoff_reason"] = reason
        event["decision"]["reply_text"] = handoff_reply_text
        verified = connector.send_text_and_verify(target.name, handoff_reply_text, exact=target.exact)
        event["send_result"] = verified
        event["verified"] = bool(verified.get("verified"))
        if not event["verified"]:
            event["action"] = "error"
            event["ok"] = False
            return event
        reply_trace_id = build_reply_trace_id(target.name, batch, handoff_reply_text)
        event["reply_trace_id"] = reply_trace_id
        alert = record_operator_alert(
            config=config,
            target_state=target_state,
            target=target,
            batch=batch,
            combined=combined,
            reason=reason,
            reply_text=handoff_reply_text,
            product_knowledge=product_knowledge,
        )
        mark_handoff(
            target_state,
            batch,
            reason=reason,
            status="open",
            operator_alert=alert,
            reply_trace_id=reply_trace_id,
            reply_text=handoff_reply_text,
        )
        mark_processed(target_state, batch, handoff_reply_text, reply_trace_id=reply_trace_id, send_result=verified)
        mark_coalesced_messages(
            target_state,
            selection.overflow_messages,
            reply_trace_id=reply_trace_id,
            reply_text=handoff_reply_text,
            reason="overflow_coalesced_after_handoff_reply",
        )
        record_reply_timestamp(target_state)
        finalize_data_capture_state(target_state, data_capture)
        _enqueue_post_reply_work(target, config, raw_capture, data_capture)
        event["operator_alert"] = alert
        event["action"] = "handoff_sent"
        return event

    if send and not decision.matched and not fallback_allowed:
        if handoff_enabled:
            mark_handoff(target_state, batch, reason="no_rule_matched", status="open")
            event["action"] = "handoff"
            event["reason"] = "fallback reply blocked"
        else:
            event["action"] = "skipped"
            event["reason"] = "fallback reply blocked and operator handoff disabled"
        event["intent_assist"] = skipped_intent_assist(config, "fallback_reply_blocked")
        return event

    if data_capture.get("is_customer_data") and data_capture.get("complete") and write_data:
        write_customer_data_if_ready(config, target, data_capture)

    if (
        send
        and data_capture.get("is_customer_data")
        and data_capture.get("complete")
        and not data_capture.get("write_result", {}).get("ok")
    ):
        event["data_capture"] = data_capture
        event["action"] = "blocked"
        event["reason"] = "customer data was not written; pass --write-data"
        event["intent_assist"] = skipped_intent_assist(config, "customer_data_write_blocked")
        return event

    event["data_capture"] = data_capture

    should_mark_after_data_write = bool(data_capture.get("write_result", {}).get("ok") and not send)

    if send:
        reply_text = _apply_greeting(
            reply_text,
            profile,
            config,
            target_state=target_state,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
        )
        reply_text = sanitize_customer_visible_reply_text(
            reply_text,
            config=config,
            combined=combined,
            reason=str(event.get("reason") or event["decision"].get("reason") or ""),
            force_handoff_style=False,
            recent_reply_texts=recent_reply_texts,
        )
        outbound_naturalness = polish_customer_visible_reply_text(
            reply_text,
            config=config,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
        )
        event["outbound_naturalness"] = outbound_naturalness
        if outbound_naturalness.get("applied"):
            reply_text = str(outbound_naturalness.get("reply_text") or reply_text)
        event["decision"]["reply_text"] = reply_text
        verified = connector.send_text_and_verify(target.name, reply_text, exact=target.exact)
        event["send_result"] = verified
        event["verified"] = bool(verified.get("verified"))
        if not event["verified"]:
            event["action"] = "error"
            event["ok"] = False
            return event
        reply_trace_id = build_reply_trace_id(target.name, batch, reply_text)
        event["reply_trace_id"] = reply_trace_id
        finalize_data_capture_state(target_state, data_capture)
        record = maybe_record_rag_experience(
            target=target,
            message_ids=message_ids,
            combined=combined,
            reply_text=reply_text,
            event=event,
            reply_trace_id=reply_trace_id,
        )
        if record:
            event["rag_experience"] = record
        _enqueue_post_reply_work(target, config, raw_capture, data_capture)
        mark_processed(target_state, batch, reply_text, reply_trace_id=reply_trace_id, send_result=verified)
        mark_coalesced_messages(
            target_state,
            selection.overflow_messages,
            reply_trace_id=reply_trace_id,
            reply_text=reply_text,
            reason="overflow_coalesced_after_customer_reply",
        )
        record_reply_timestamp(target_state)
        profile_store = CustomerProfileStore()
        profile_store.increment_message_stats(target_name=target.name, is_reply=True)
        event["action"] = "sent"
        return event

    if should_mark_after_data_write:
        finalize_data_capture_state(target_state, data_capture)
        mark_processed(target_state, batch, reply_text)
        mark_coalesced_messages(
            target_state,
            selection.overflow_messages,
            reply_text=reply_text,
            reason="overflow_coalesced_after_data_write",
        )
        event["marked_processed"] = True
        event["action"] = "captured"
        return event

    if mark_dry_run:
        finalize_data_capture_state(target_state, data_capture)
        mark_processed(target_state, batch, reply_text)
        mark_coalesced_messages(
            target_state,
            selection.overflow_messages,
            reply_text=reply_text,
            reason="overflow_coalesced_after_dry_run",
        )
        event["marked_processed"] = True
    return event


def maybe_record_raw_messages(target: TargetConfig, config: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    settings = config.get("raw_messages", {}) or {}
    console_settings = config.get("_local_customer_service_settings", {}) or {}
    if console_settings.get("record_messages") is False:
        return {"enabled": False, "reason": "customer_service_record_messages_disabled"}
    if settings.get("enabled", True) is False:
        return {"enabled": False}
    normalized_messages = [item for item in messages if isinstance(item, dict) and str(item.get("content") or "").strip()]
    if not normalized_messages:
        return {"enabled": True, "ok": True, "inserted_count": 0, "duplicate_count": 0}
    try:
        store = RawMessageStore()
        allow_customer_service_learning = settings.get("allow_customer_service_learning") is True
        raw_learning_enabled = settings.get("learning_enabled", False) is True and allow_customer_service_learning
        result = store.upsert_messages(
            {
                "target_name": target.name,
                "display_name": target.name,
                "conversation_type": str(settings.get("conversation_type") or infer_raw_conversation_type(target.name)),
                "status": "active",
                "exact": target.exact,
                "record_self": True,
                "learning_enabled": raw_learning_enabled,
                "allow_learning_from_customer_service": allow_customer_service_learning,
                "notify_enabled": bool(settings.get("notify_enabled", False)),
                "source": {"type": "customer_service_listener"},
            },
            normalized_messages,
            source_module="customer_service",
            learning_enabled=raw_learning_enabled,
            create_batch=True,
            batch_reason="customer_service_poll",
        )
        if settings.get("auto_learn", False) and result.get("batch"):
            result["learning"] = {"status": "pending_enqueue", "batch_id": str(result["batch"].get("batch_id") or "")}
        return {"enabled": True, **result}
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": repr(exc)}


def infer_raw_conversation_type(target_name: str) -> str:
    if target_name == FILE_TRANSFER_ASSISTANT:
        return "file_transfer"
    if "群" in target_name or "chatroom" in target_name.lower():
        return "group"
    return "private"


def handle_rate_limit_block(
    connector: WeChatConnector,
    target: TargetConfig,
    config: dict[str, Any],
    target_state: dict[str, Any],
    event: dict[str, Any],
    message_ids: list[str],
    rate_check: dict[str, Any],
) -> dict[str, Any]:
    record_rate_limit_backoff(target_state, message_ids, rate_check)
    event["action"] = "blocked"
    event["reason"] = rate_check["reason"]
    event["rate_limit"] = rate_check
    event["intent_assist"] = skipped_intent_assist(
        config,
        "rate_limited",
        {"rate_limit": rate_check},
    )
    if not should_send_rate_limit_notice(target_state, config, rate_check):
        return event

    reply_prefix = configured_reply_prefix(config)
    notice_text = format_reply(build_rate_limit_notice_text(config, rate_check), reply_prefix)
    verified = connector.send_text_and_verify(target.name, notice_text, exact=target.exact)
    event["rate_limit_notice"] = {
        "reply_text": notice_text,
        "send_result": verified,
        "verified": bool(verified.get("verified")),
    }
    if event["rate_limit_notice"]["verified"]:
        record_rate_limit_notice(target_state, message_ids, rate_check, notice_text)
        event["action"] = "rate_limit_notice_sent"
    return event


def maybe_record_rag_experience(
    *,
    target: TargetConfig,
    message_ids: list[str],
    combined: str,
    reply_text: str,
    event: dict[str, Any],
    reply_trace_id: str = "",
) -> dict[str, Any] | None:
    rag_reply = event.get("rag_reply", {}) or {}
    if not rag_reply.get("applied"):
        return None
    try:
        return record_rag_reply_experience(
            target=target.name,
            message_ids=message_ids,
            question=combined,
            reply_text=reply_text,
            raw_reply_text=str(rag_reply.get("raw_reply_text") or reply_text),
            intent_assist=event.get("intent_assist", {}) or {},
            rag_reply=rag_reply,
            reply_trace_id=reply_trace_id,
        )
    except Exception as exc:
        event["rag_experience_error"] = repr(exc)
        return None


def identity_guard_enabled_for_customer_reply(config: dict[str, Any]) -> bool:
    llm_synthesis = config.get("llm_reply_synthesis", {}) or {}
    return llm_synthesis.get("identity_guard_enabled", True) is not False


def split_reply_prefix(reply_text: str, config: dict[str, Any]) -> tuple[str, str]:
    clean = str(reply_text or "").strip()
    if not clean:
        return "", ""
    prefix = configured_reply_prefix(config)
    if prefix and clean.startswith(prefix):
        return prefix, clean[len(prefix) :].strip()
    return "", clean


def recent_customer_visible_reply_texts(target_state: dict[str, Any], *, limit: int = 5) -> list[str]:
    replies: list[tuple[str, str]] = []
    for item in target_state.get("sent_replies", []) or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("reply_text") or "").strip()
        if text and state_context_item_is_usable(item, text=text, allow_polluted_message_contents=True):
            replies.append((str(item.get("processed_at") or ""), text))
    for item in target_state.get("handoff_events", []) or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("reply_text") or "").strip()
        if text and state_context_item_is_usable(item, text=text, timestamp_key="created_at"):
            replies.append((str(item.get("created_at") or ""), text))
    replies.sort(key=lambda item: item[0])
    return [text for _, text in replies[-max(1, limit) :]]


def recent_customer_message_texts(target_state: dict[str, Any], *, limit: int = 5) -> list[str]:
    messages: list[str] = []
    for item in target_state.get("sent_replies", []) or []:
        if not isinstance(item, dict):
            continue
        if not state_context_item_is_usable(item):
            continue
        for content in item.get("message_contents", []) or []:
            text = str(content or "").strip()
            if text and not state_context_text_is_polluted(text):
                messages.append(text)
    return messages[-max(1, limit) :]


def state_context_item_is_usable(
    item: dict[str, Any],
    *,
    text: str = "",
    timestamp_key: str = "processed_at",
    allow_polluted_message_contents: bool = False,
) -> bool:
    timestamp = parse_datetime(str(item.get(timestamp_key) or item.get("processed_at") or item.get("created_at") or ""))
    if timestamp is not None and datetime.now() - timestamp > timedelta(hours=6):
        return False
    if text and state_context_text_is_polluted(text):
        return False
    if allow_polluted_message_contents:
        return True
    for content in item.get("message_contents", []) or []:
        if state_context_text_is_polluted(str(content or "")):
            return False
    return True


def state_context_text_is_polluted(text: str) -> bool:
    if text_has_test_marker(text) or text_has_model_reply_marker(text):
        return True
    return bool(message_learning_exclusion_reason({"content": text, "type": "text"}, source_module="state_context_probe"))


def build_realtime_context_combined(combined: str, target_state: dict[str, Any]) -> str:
    current = str(combined or "").strip()
    recent = recent_customer_message_texts(target_state, limit=5)
    if not current or not recent:
        return current
    if state_context_text_is_polluted(current):
        return current
    clean = re.sub(r"\s+", "", current)
    context_markers = (
        "这个预算",
        "刚才",
        "你刚才",
        "这两台",
        "这几台",
        "这个方向",
        "按我的情况",
        "重新收一下",
        "哪两台",
        "哪台",
        "具体车源",
        "直接挑",
        "挑两台",
        "挑几台",
        "给我两台",
        "给我几台",
        "别再问预算",
        "不用再问预算",
        "按这个",
        "就按这个",
        "按前面",
        "前面说的",
        "这俩",
        "它俩",
        "哪个更适合",
        "哪台更适合",
        "新手停车",
        "停车不熟",
        "父母",
        "老人",
        "异地",
        "置换",
    )
    business_context_markers = context_markers + (
        "车源",
        "推荐",
        "挑",
        "筛",
        "看看",
        "预算",
        "自动挡",
        "倒车影像",
        "影像",
        "雷达",
        "省油",
        "家用",
        "通勤",
        "接娃",
        "老婆",
        "女士",
        "好停",
        "好开",
        "试驾",
        "到店",
        "周末",
    )
    lacks_budget = not re.search(r"\d+(?:\.\d+)?\s*(?:到|-|~|至)?\s*\d*(?:\.\d+)?\s*万", clean)
    needs_context = any(marker in clean for marker in context_markers) or (
        lacks_budget and any(marker in clean for marker in business_context_markers)
    )
    if not needs_context:
        return current
    recent_text = "\n".join(f"- {text}" for text in recent[-4:])
    return f"近期客户需求：\n{recent_text}\n当前客户问题：{current}"


def recent_sent_reply_content_keys(target_state: dict[str, Any], *, limit: int = 30) -> set[str]:
    """Track exact customer-visible replies so File Transfer self-tests do not re-read them as customer input."""
    keys: list[str] = []
    # This is a duplicate-suppression guard, not a context provider. Do not apply
    # the six-hour context freshness filter here, otherwise old visible self
    # replies in File Transfer Assistant can be re-read as new customer input.
    for collection, text_keys in (
        (target_state.get("sent_replies", []) or [], ("reply_text", "raw_reply_text")),
        (target_state.get("handoff_events", []) or [], ("reply_text",)),
        (target_state.get("operator_alerts", []) or [], ("reply_text",)),
    ):
        for item in collection[-max(1, limit) :]:
            if not isinstance(item, dict):
                continue
            for text_key in text_keys:
                key = normalize_reply_content_key(str(item.get(text_key) or ""))
                if key:
                    keys.append(key)
    return set(keys)


def normalize_reply_content_key(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def has_explicit_handoff_phrase(text: str) -> bool:
    clean = re.sub(r"\s+", "", str(text or ""))
    if not clean:
        return False
    return any(re.search(pattern, clean, re.I) for pattern in EXPLICIT_HANDOFF_PATTERNS)


def choose_customer_visible_variant(
    variants: list[str],
    *,
    context: str,
    recent_reply_texts: list[str] | None = None,
) -> str:
    reply, _ = choose_reply_variant(variants, key_text=context, recent_reply_texts=recent_reply_texts)
    return de_template_reply_text(reply, key_text=context, recent_reply_texts=recent_reply_texts)


def new_energy_usage_detail(context: str) -> str:
    clean = re.sub(r"\s+", "", str(context or ""))
    if not clean:
        return "您这个顾虑我先记下"
    patterns = (
        r"(?:一天|每天|平时|通勤|上下班|来回|单程).{0,12}?(\d{1,3})\s*(?:公里|km|KM)",
        r"(\d{1,3})\s*(?:公里|km|KM).{0,12}?(?:一天|每天|平时|通勤|上下班|来回|单程)",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            return f"您说的{match.group(1)}公里这个用车强度我记下了"
    if any(term in clean for term in ("家用", "通勤", "上下班", "代步", "跑高速", "老婆", "孩子")):
        return "您的用车场景我先记下"
    return "您这个顾虑我先记下"


def is_location_contact_context(context: str) -> bool:
    text = str(context or "")
    return any(term in text for term in LOCATION_CONTACT_STRONG_TERMS) and any(
        term in text for term in LOCATION_VISIT_CONTEXT_TERMS
    )


def concealed_handoff_reply(*, combined: str = "", reason: str = "", recent_reply_texts: list[str] | None = None) -> str:
    context = f"{combined} {reason}".strip()
    if is_location_contact_context(context):
        return choose_customer_visible_variant(
            [
                "门店地址和到了找谁我先确认一下，确认好后发您，避免您导航错或到店没人对接。",
                "这个我给您核清楚再发，地址、导航和到店联系人都一起确认好，省得您白跑。",
                "可以，我先确认门店地址和到店对接人，核好后回您，您过去会更稳一点。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in CONTACT_DATA_TERMS) and any(term in context for term in APPOINTMENT_TERMS):
        return choose_customer_visible_variant(
            [
                "可以，姓名、电话和到店时间我记下了。我这边确认一下车源和门店排期，弄清楚后回您，尽量别让您白跑。",
                "可以，联系方式和到店时间我记下，接下来确认车源状态、门店排期和看车安排，核好后回您。",
                "信息我记下了，这边确认车源还在不在、到店时间能不能排上，弄清楚后回您。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in DOCUMENT_TERMS):
        if any(term in context for term in ("少开", "低开", "金额")):
            return choose_customer_visible_variant(
                [
                    "我理解您是想把流程提前问清楚，合同和发票金额这块必须按实际交易和门店流程走，不能随口答应调整。我请负责人确认合同流程和开票要求，核清楚再回复您。",
                    "这个我先帮您问清楚，发票金额和合同信息要按实际交易来确认，不能直接口头定。您稍等，我问下领导后再给您明确说法。",
                    "这块确实要提前确认好，免得后面来回改。合同签署和开票金额都要按流程核实，您稍等一下，我确认清楚后回您。",
                ],
                context=context,
                recent_reply_texts=recent_reply_texts,
            )
        return choose_customer_visible_variant(
            [
                "可以，这块我帮您问清楚。合同和发票需要按门店流程来，我把开票抬头、税号和合同资料要求核清楚后回您，避免后面填错。",
                "这个提前问是对的，我帮您确认合同流程和开票资料要求后再回复您，省得后面资料来回补。",
                "合同和发票这块我先确认一下门店流程。您稍等，我核实好抬头、税号和需要准备的资料后回复您。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in PRICE_HARD_BOUNDARY_TERMS):
        return choose_customer_visible_variant(
            [
                "您想今天定，我理解，价格和金融这块我不能为了促成就随口保证。我先把车源、付款方式和负责人意见确认好，再给您明确答复。",
                "价格我肯定帮您争取，但最低价和贷款结果不能直接口头保证。我核实一下具体车源、成交方式和负责人意见，再回复您。",
                "这个我先帮您往下问，争取归争取，但价格、库存和金融结果都要确认过才稳。我核清楚后再给您准话。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in APPOINTMENT_TERMS):
        return choose_customer_visible_variant(
            [
                "您这个安排我记下了，我这边确认排期，核实后回您。",
                "可以，我把您想看的时间和车型记下，确认一下车源和门店排期再回复您。",
                "到店这块我记一下，再确认排期和车源状态，避免您白跑，确认好就回您。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in NEW_ENERGY_TERMS):
        usage_detail = new_energy_usage_detail(context)
        return choose_customer_visible_variant(
            [
                f"您担心电池和三电很正常，{usage_detail}。这块不能只听一句口头保证，我先核实检测记录、电池状态和车况，请稍等，确认后再跟您说这台适不适合。",
                f"新能源最该看的就是电池、三电和检测记录。{usage_detail}，我先核清楚实际续航、检测报告和车况，请稍等，确认好再给您更稳的判断。",
                f"这个问题问得很关键。{usage_detail}，混动车要看电池状态、三电检测和实际用车强度，我先把这些核实清楚，请稍等，确认后再跟您说适不适合入手。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in AFTER_SALES_TERMS):
        return choose_customer_visible_variant(
            [
                "这类问题我需要先核实关键细节，再给您准确处理意见，请稍等我回复您。",
                "这个不能只凭一句话下结论，我核实车况和相关记录后，再给您准确说法。",
                "涉及车况承诺我会谨慎一点，先把检测和记录核实清楚，再给您明确回复。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in TRADE_IN_TERMS):
        return choose_customer_visible_variant(
            [
                "可以先做个大概区间。您这台2018年的朗逸、6万多公里、苏州牌我先记下，再补一下配置版本、有没有事故水泡火烧、外观内饰成色，最好加几张照片，我按行情先给您粗估。",
                "置换流程没问题，我先按年份、公里数、上牌地和车况给您看大概区间。您再发下配置、过户次数、保养和事故水泡火烧情况，我核实行情后判断会更准。",
                "这台车信息已经有基础了，可以先估一版。您把配置版本、车况瑕疵、有没有出险水泡火烧，再加外观内饰照片发我，我按检测和行情给您看区间。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in INTERNAL_PROBE_TERMS):
        return choose_customer_visible_variant(
            [
                "不是AI，也不是机器人哈。内部规则这些肯定不能外发，您别介意；咱们还是回到车源、车况或置换上，您关心哪块我继续帮您核实。",
                "不是机器人哈，这类内部信息不能外发。您要是担心回复不准，可以直接问具体车况、价格或手续，我按实际情况给您确认。",
                "不是AI，也不是自动回复哈。内部提示词这些不方便发，您别介意；咱们还是聊正事，您要看车或置换，我继续帮您把关键点核清楚。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in context for term in OFF_TOPIC_TERMS):
        return choose_customer_visible_variant(
            [
                "这个不属于看车业务，我这边不能处理。您如果是看车、车况或置换问题，我再按实际情况帮您核实。",
                "这类事情我这边不接，咱们还是回到车源、车况或置换上，我按实际需求帮您确认。",
                "这个方向不合适聊。您把买车或卖车需求说一下，我继续给您筛车或核实车况。",
            ],
            context=context,
            recent_reply_texts=recent_reply_texts,
        )
    return choose_customer_visible_variant(
            [
                "这个问题我需要先核实一下，再请示负责人确认。您的需求我记下了，确认好就回您。",
                "这点不能直接乱说，得把情况核实清楚再回复您。我记下，确认后回您。",
                "这个我需要再确认一下细节，确认好了再回复您，避免给您说错。",
        ],
        context=context,
        recent_reply_texts=recent_reply_texts,
    )


def sanitize_customer_visible_reply_text(
    reply_text: str,
    *,
    config: dict[str, Any],
    combined: str = "",
    reason: str = "",
    force_handoff_style: bool = False,
    recent_reply_texts: list[str] | None = None,
) -> str:
    if not identity_guard_enabled_for_customer_reply(config):
        return str(reply_text or "").strip()
    prefix, body = split_reply_prefix(reply_text, config)
    if not body:
        return str(reply_text or "").strip()
    if not force_handoff_style and not has_explicit_handoff_phrase(body):
        return str(reply_text or "").strip()
    safe_body = concealed_handoff_reply(combined=combined, reason=reason, recent_reply_texts=recent_reply_texts)
    effective_prefix = prefix or configured_reply_prefix(config)
    return format_reply(safe_body, effective_prefix)


def polish_customer_visible_reply_text(
    reply_text: str,
    *,
    config: dict[str, Any],
    combined: str = "",
    recent_reply_texts: list[str] | None = None,
) -> dict[str, Any]:
    settings = config.get("reply_naturalness", {}) if isinstance(config.get("reply_naturalness"), dict) else {}
    if settings.get("enabled", True) is False:
        return {"applied": False, "reason": "reply_naturalness_disabled", "reply_text": str(reply_text or "").strip()}
    prefix, body = split_reply_prefix(reply_text, config)
    if not body:
        return {"applied": False, "reason": "empty_reply", "reply_text": str(reply_text or "").strip()}
    polished = de_template_reply_text(body, key_text=combined, recent_reply_texts=recent_reply_texts)
    polished = normalize_customer_visible_mechanics(polished, combined=combined, recent_reply_texts=recent_reply_texts)
    polished = diversify_similar_customer_visible_reply(polished, combined=combined, recent_reply_texts=recent_reply_texts)
    if not polished or polished.strip() == body.strip():
        return {"applied": False, "reason": "no_naturalness_delta", "reply_text": str(reply_text or "").strip()}
    guard = guard_customer_visible_polish(base_reply=body, polished_reply=polished)
    final_reply = format_reply(polished, prefix or configured_reply_prefix(config)) if guard.get("allowed") else str(reply_text or "").strip()
    return {
        "applied": bool(guard.get("allowed")),
        "reason": "customer_visible_polished" if guard.get("allowed") else str(guard.get("reason") or "polish_guard_rejected"),
        "reply_text": final_reply,
        "raw_reply_text": polished if guard.get("allowed") else body,
        "guard": guard,
    }


def normalize_customer_visible_mechanics(
    reply_text: str,
    *,
    combined: str = "",
    recent_reply_texts: list[str] | None = None,
) -> str:
    text = str(reply_text or "").strip()
    if not text:
        return text
    replacements: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("我会转给销售人工确认", ("我再核一下排期和安排", "这边确认好排期再回您", "我问清楚安排再回您")),
        ("我会转给人工继续处理", ("我需要内部确认后再继续处理", "这块我确认好再往下处理", "我问清楚后再接着处理")),
        ("转接人工客服", ("帮您转给负责的人", "这边安排负责的人跟进", "我帮您把问题递过去")),
        ("销售人工确认", ("负责人确认", "门店确认", "负责的人确认")),
        ("人工确认", ("负责人确认", "内部确认", "核实确认")),
        ("人工核实", ("负责人核实", "内部核实", "核实确认")),
        ("稍后继续处理", ("后面继续跟进", "接下来继续处理", "我这边继续往下跟")),
        ("稍后给您准确回复", ("确认后再回复您", "问清楚后回您", "核完再回您")),
        ("当前无法直接确认", ("现在还不能直接确认", "这点不能直接定", "这个得先核一下")),
        ("我当前无法直接确认", ("我现在还不能直接确认", "这点我不能直接定", "这个我得先核一下")),
        ("这个问题需要", ("这块需要", "这个得", "这点要")),
        ("我会重点看", ("重点看", "我主要看", "这边先核")),
        ("我会优先看", ("优先看", "我主要看", "这边先看")),
        ("我再帮您", ("我再", "这边再", "后面再")),
        ("我这边会", ("这边会", "我会", "先")),
        ("这个需求已经比较明确了", ("条件已经比较清楚了", "这个方向挺明确了", "需求这块已经不算泛了")),
        ("好的，请发我", ("可以，您发我", "行，您把", "您直接发我")),
        ("没问题，您先慢慢看", ("可以，您先看看", "行，您先不急", "没事，您先了解")),
        ("我帮您确认报价", ("我帮您核报价", "我给您核一下报价", "我这边看下报价")),
        ("我帮您核对", ("我帮您看下", "我这边核一下", "我来对一下")),
        ("您这个需求我建议先按", ("您这个需求可以先按", "这类需求重点按", "这种情况先按")),
        ("您把预算和主要用途发我", ("预算和主要用途您发我一下", "您说下预算和主要用途", "预算、主要用途这两点您补一下")),
    )
    for old, variants in replacements:
        if old not in text:
            continue
        replacement, _ = choose_reply_variant(
            list(variants),
            key_text=f"{combined}|naturalness|{old}",
            recent_reply_texts=recent_reply_texts,
        )
        text = text.replace(old, replacement, 1)
    text = re.sub(r"^(收到|好的|可以|没问题)[，,。]\s*(收到|好的|可以|没问题)[，,。]\s*", r"\1，", text)
    return text


def diversify_similar_customer_visible_reply(
    reply_text: str,
    *,
    combined: str = "",
    recent_reply_texts: list[str] | None = None,
) -> str:
    text = str(reply_text or "").strip()
    recent_reply_texts = recent_reply_texts or []
    if not text or not recent_reply_texts:
        return text
    max_similarity = max((reply_similarity(text, recent) for recent in recent_reply_texts[-4:]), default=0.0)
    if max_similarity < 0.72:
        return text
    variants = [
        re.sub(r"^可以[，,]", "行，", text),
        re.sub(r"^收到[，,]", "好，", text),
        text.replace("这个需求已经比较明确了", "条件已经比较清楚了", 1),
        text.replace("按您说的", "照您刚才说的", 1),
        text.replace("您这个需求", "这类需求", 1),
        text.replace("我这边", "这边", 1),
        text.replace("我会", "先", 1),
        text.replace("我帮您", "我来", 1),
    ]
    candidates = [item.strip() for item in variants if item.strip() and item.strip() != text]
    if not candidates:
        return text
    selected, _ = choose_reply_variant(candidates, key_text=f"{combined}|similarity-polish", recent_reply_texts=recent_reply_texts)
    selected_similarity = max((reply_similarity(selected, recent) for recent in recent_reply_texts[-4:]), default=0.0)
    return selected if selected_similarity <= max_similarity else text


def guard_customer_visible_polish(*, base_reply: str, polished_reply: str) -> dict[str, Any]:
    base_numbers = protected_customer_visible_tokens(base_reply)
    polished_numbers = protected_customer_visible_tokens(polished_reply)
    new_numbers = sorted(polished_numbers - base_numbers)
    if new_numbers:
        return {"allowed": False, "reason": "polish_introduced_number", "new_numbers": new_numbers}
    if exposes_ai_identity_in_customer_reply(polished_reply):
        return {"allowed": False, "reason": "polish_exposed_ai_identity"}
    return {"allowed": True}


def protected_customer_visible_tokens(text: str) -> set[str]:
    value = str(text or "")
    tokens = set(re.findall(r"\d+(?:\.\d+)?\s*(?:万|元|块|公里|km|KM|年|天|%|折)", value))
    tokens.update(re.findall(r"1[3-9]\d{9}", value))
    tokens.update(re.findall(r"\b\d{4,}\b", value))
    return {re.sub(r"\s+", "", item) for item in tokens if item}


def exposes_ai_identity_in_customer_reply(text: str) -> bool:
    clean = re.sub(r"\s+", "", str(text or ""))
    if not clean:
        return False
    markers = ("我是AI", "我是ai", "我是机器人", "AI助手", "智能客服", "自动回复系统")
    for marker in markers:
        marker_clean = re.sub(r"\s+", "", marker)
        if marker_clean not in clean:
            continue
        if any(prefix + marker_clean in clean for prefix in ("不是", "并不是", "不算")):
            continue
        return True
    return False


def should_operator_handoff(
    decision: ReplyDecision,
    product_knowledge: dict[str, Any] | None,
    fallback_allowed: bool,
    intent_assist: dict[str, Any] | None = None,
) -> bool:
    if evidence_requires_handoff(intent_assist):
        return True
    # Intent-assist handoff only overrides when no safe rule matched or the
    # handoff reason is an explicit signal (e.g. appointment after data capture).
    if isinstance(intent_assist, dict) and intent_assist.get("needs_handoff"):
        if not decision.matched or decision.need_handoff:
            return True
        reason = str(intent_assist.get("reason") or "")
        if reason == "customer_data_complete_with_appointment":
            return True
    if product_knowledge and product_knowledge.get("auto_reply_allowed") is False:
        return True
    if product_knowledge and product_knowledge.get("needs_handoff"):
        return True
    if decision.need_handoff:
        return True
    if not decision.matched and not fallback_allowed:
        return True
    if decision.reason in {"approval_required", "no_rule_matched"}:
        return True
    return False


def llm_synthesis_explicit_override(config: dict[str, Any]) -> bool:
    settings = config.get("llm_reply_synthesis", {}) or {}
    if not settings.get("enabled", False):
        return False
    if settings.get("force_foreground") is True:
        return True
    return str(settings.get("provider") or "") == "manual_json" and isinstance(settings.get("candidate"), dict)


def build_operator_handoff_reply_text(
    config: dict[str, Any],
    decision: ReplyDecision,
    product_knowledge: dict[str, Any] | None,
    current_reply_text: str,
    intent_assist: dict[str, Any] | None = None,
    combined: str = "",
) -> str:
    if decision.rule_name == "llm_synthesis_handoff" and str(current_reply_text or "").strip():
        return current_reply_text
    if decision.rule_name == "llm_synthesis_reply" and llm_reply_already_handoff_style(current_reply_text):
        return current_reply_text
    if evidence_requires_handoff(intent_assist):
        return format_reply(handoff_acknowledgement_text(config, combined=combined), configured_reply_prefix(config))
    if product_knowledge and product_knowledge.get("auto_reply_allowed") is False:
        return format_reply(handoff_acknowledgement_text(config, combined=combined), configured_reply_prefix(config))
    if product_knowledge and product_knowledge.get("reply_text"):
        return current_reply_text
    return format_reply(handoff_acknowledgement_text(config), configured_reply_prefix(config))


def handoff_acknowledgement_text(config: dict[str, Any], *, combined: str = "") -> str:
    settings = config.get("handoff", {}) or {}
    conceal_handoff = identity_guard_enabled_for_customer_reply(config)
    text = str(
        settings.get("acknowledgement_reply")
        or "这个问题我当前无法直接确认，我把情况记下，问清楚负责人意见后再回复您。"
    )
    if handoff_acknowledgement_is_formulaic(text):
        if "直接按" in str(combined or ""):
            if conceal_handoff:
                return "这类价格我不能直接确认，我问下负责人再跟您说准。"
            return "这类价格我不能直接确认，需要请示上级后才能给准话。"
        if conceal_handoff:
            return "这点我不能直接替您定，我把问题记下，问清楚负责人意见后再回您。"
        return "这点我不能直接替您定，我把问题记下，让负责的同事核实后再回您。"
    return text


def handoff_acknowledgement_is_formulaic(text: str) -> bool:
    formulaic_terms = (
        "收到，我先记录",
        "稍后继续处理",
        "请示上级",
        "这个问题需要销售人工确认，我先帮您记录并提醒同事跟进",
        "我先帮您记录并提醒同事跟进",
        "当前无法直接确认，我先帮您记录",
    )
    return any(term in str(text or "") for term in formulaic_terms)


def llm_reply_already_handoff_style(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    markers = ("人工", "同事", "销售", "核实", "复核", "转接", "联系", "请示", "负责人", "确认后")
    return any(marker in clean for marker in markers)


def handoff_reason(
    decision: ReplyDecision,
    product_knowledge: dict[str, Any] | None,
    intent_assist: dict[str, Any] | None = None,
) -> str:
    evidence_reason = evidence_handoff_reason(intent_assist)
    if evidence_reason:
        return evidence_reason
    if product_knowledge and product_knowledge.get("approval_reason"):
        return str(product_knowledge.get("approval_reason"))
    if product_knowledge and product_knowledge.get("auto_reply_allowed") is False:
        return str(product_knowledge.get("reason") or "auto_reply_disabled")
    if product_knowledge and product_knowledge.get("needs_handoff"):
        return str(product_knowledge.get("reason") or "product_knowledge_requires_handoff")
    return str(decision.reason or "operator_handoff")


def record_operator_alert(
    config: dict[str, Any],
    target_state: dict[str, Any],
    target: TargetConfig,
    batch: list[dict[str, Any]],
    combined: str,
    reason: str,
    reply_text: str,
    product_knowledge: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("operator_alert", {}) or {}
    alert = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": target.name,
        "message_ids": [str(item.get("id") or "") for item in batch],
        "message_contents": [str(item.get("content") or "") for item in batch],
        "combined_content": combined,
        "reason": reason,
        "reply_text": reply_text,
        "product_knowledge": product_knowledge,
        "status": "open",
    }
    if settings.get("enabled", True):
        alert_path = resolve_path(settings.get("alert_log_path") or "runtime/logs/wechat_customer_service/operator_alerts.jsonl")
        append_jsonl(alert_path, alert)
        alert["delivery"] = {"type": "jsonl", "path": str(alert_path), "ok": True}
    else:
        alert["delivery"] = {"type": "disabled", "ok": False}
    alert["case_store"] = create_handoff_case(config, alert)
    target_state.setdefault("operator_alerts", []).append(alert)
    target_state["operator_alerts"] = target_state["operator_alerts"][-MAX_STORED_IDS:]
    return alert


def create_handoff_case(config: dict[str, Any], alert: dict[str, Any]) -> dict[str, Any]:
    settings = config.get("handoff", {}) or {}
    if settings.get("case_store_enabled", True) is False:
        return {"enabled": False}
    try:
        from apps.wechat_ai_customer_service.admin_backend.services.handoff_store import HandoffStore

        case = HandoffStore().create_case(
            {
                "target": alert.get("target"),
                "reason": alert.get("reason"),
                "message_ids": alert.get("message_ids", []),
                "message_contents": alert.get("message_contents", []),
                "reply_text": alert.get("reply_text") or "",
                "operator_alert": alert,
                "product_context": alert.get("product_knowledge", {}) or {},
                "status": "open",
                "priority": 1,
            }
        )
        return {"enabled": True, "ok": True, "case_id": case.get("case_id"), "status": case.get("status")}
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": repr(exc)}


def maybe_capture_customer_data(
    config: dict[str, Any],
    target_state: dict[str, Any],
    target: TargetConfig,
    batch: list[dict[str, Any]],
    combined: str,
    write_data: bool,
    intent_result: IntentRouteResult | None = None,
) -> dict[str, Any]:
    settings = config.get("data_capture", {}) or {}
    if not settings.get("enabled", False):
        return {"enabled": False}

    pending = get_open_pending_customer_data(target_state)
    # Auto-close stale pending (older than 120s) so normal conversation can resume
    if pending:
        updated_at_str = str(pending.get("updated_at") or "")
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            if (datetime.now() - updated_at).total_seconds() > 120:
                close_pending_customer_data(target_state, {
                    "fields": pending.get("fields", {}),
                    "message_ids": pending.get("message_ids", []),
                    "write_result": {"ok": False, "reason": "pending_expired"},
                })
                pending = None
        except Exception:
            pass

    pending_raw_text = str(pending.get("raw_text") or "") if pending else ""
    pending_message_ids = [str(item) for item in pending.get("message_ids", [])] if pending else []
    current_message_ids = [str(item.get("id") or "") for item in batch]

    # If current message itself has no customer-data signal, don't merge with stale pending
    from customer_data_capture import has_customer_data_signal
    current_has_signal = has_customer_data_signal(combined, {})
    if pending and not current_has_signal:
        merged_text = combined
        merged_message_ids = current_message_ids
    else:
        merged_text = "\n".join(item for item in [pending_raw_text, combined] if item.strip())
        merged_message_ids = unique_list([*pending_message_ids, *current_message_ids])

    required_fields = [str(item) for item in settings.get("required_fields", ["name", "phone"])]
    extraction = extract_customer_data(merged_text, required_fields=required_fields)

    # Intent-driven gate: only mark as customer_data when LLM intent says so
    if intent_result is not None:
        is_customer_data = intent_result.intent == "customer_data_provide" and bool(extraction.fields)
    else:
        is_customer_data = extraction.is_customer_data

    result: dict[str, Any] = {
        "enabled": True,
        "is_customer_data": is_customer_data,
        "complete": extraction.complete,
        "fields": extraction.fields,
        "missing_required_fields": extraction.missing_required_fields,
        "missing_required_labels": missing_field_labels(extraction.missing_required_fields),
        "pending_before": copy.deepcopy(pending),
        "message_ids": merged_message_ids,
        "raw_text": merged_text,
        "write_requested": write_data,
    }
    if not is_customer_data:
        return result
    if not extraction.complete:
        result["write_skipped_reason"] = "missing_required_fields"
        return result
    if not write_data:
        result["write_skipped_reason"] = "write_data_not_requested"
        return result

    workbook_path = resolve_path(settings.get("workbook_path"))
    sheet_name = str(settings.get("sheet_name") or "客户线索")
    result["write_result"] = append_customer_row(
        workbook_path=workbook_path,
        sheet_name=sheet_name,
        source_target=target.name,
        message_ids=merged_message_ids,
        raw_text=merged_text,
        fields=extraction.fields,
    )
    return result


def write_customer_data_if_ready(
    config: dict[str, Any],
    target: TargetConfig,
    data_capture: dict[str, Any],
) -> None:
    if not data_capture.get("enabled") or not data_capture.get("is_customer_data"):
        return
    if not data_capture.get("complete"):
        return
    if data_capture.get("write_result", {}).get("ok"):
        return

    settings = config.get("data_capture", {}) or {}
    workbook_path = resolve_path(settings.get("workbook_path"))
    sheet_name = str(settings.get("sheet_name") or "客户线索")
    data_capture["write_requested"] = True
    data_capture.pop("write_skipped_reason", None)
    data_capture["write_result"] = append_customer_row(
        workbook_path=workbook_path,
        sheet_name=sheet_name,
        source_target=target.name,
        message_ids=[str(item) for item in data_capture.get("message_ids", [])],
        raw_text=str(data_capture.get("raw_text") or ""),
        fields=data_capture.get("fields", {}) or {},
    )


def decide_reply_with_data_capture(
    combined: str,
    rules: dict[str, Any],
    config: dict[str, Any],
    data_capture: dict[str, Any],
    product_knowledge: dict[str, Any] | None = None,
) -> ReplyDecision:
    if data_capture.get("is_customer_data"):
        if data_capture.get("complete"):
            reply = data_capture_reply(config, data_capture, complete=True)
            needs_handoff = visible_platform_terms_hit(
                combined,
                settings=config.get("llm_reply_synthesis", {}) or {},
            )
            return ReplyDecision(
                reply_text=reply,
                rule_name="customer_data_capture",
                matched=True,
                need_handoff=needs_handoff,
                reason="customer_data_complete_requires_handoff" if needs_handoff else "customer_data_complete",
            )
        reply = data_capture_reply(config, data_capture, complete=False)
        return ReplyDecision(
            reply_text=reply,
            rule_name="customer_data_incomplete",
            matched=True,
            need_handoff=False,
            reason="customer_data_missing_required_fields",
            )
    if product_knowledge and product_knowledge.get("matched") and product_knowledge.get("reply_text"):
        return ReplyDecision(
            reply_text=str(product_knowledge.get("reply_text") or ""),
            rule_name="product_knowledge",
            matched=True,
            need_handoff=bool(product_knowledge.get("needs_handoff")),
            reason=str(product_knowledge.get("reason") or "product_knowledge_matched"),
        )
    return decide_reply(combined, rules)


def maybe_match_product_knowledge(
    config: dict[str, Any],
    target_state: dict[str, Any],
    combined: str,
    data_capture: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("product_knowledge", {}) or {}
    if not settings.get("enabled", False):
        return {"enabled": False}
    if data_capture.get("is_customer_data"):
        return {"enabled": True, "matched": False, "reason": "skipped_for_customer_data"}
    path = resolve_path(settings.get("path"))
    knowledge = load_product_knowledge(path)
    result = decide_product_knowledge_reply(
        combined,
        knowledge,
        context=target_state.get("conversation_context", {}) or {},
    )
    result["path"] = str(path)
    return result


def apply_local_customer_service_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Overlay Local Console switches onto the workflow config used by the listener."""
    merged = copy.deepcopy(config)
    try:
        settings = CustomerServiceSettings().get()
    except Exception:
        return merged
    merged["_local_customer_service_settings"] = settings
    managed_session_targets = bool(settings.get("session_targets_managed", False))
    respond_all_unread_sessions = bool(settings.get("respond_all_unread_sessions", False))
    configured_targets = [item for item in merged.get("targets", []) or [] if isinstance(item, dict)]
    configured_by_name = {str(item.get("name") or "").strip(): item for item in configured_targets if str(item.get("name") or "").strip()}
    managed_targets = [item for item in settings.get("session_targets", []) or [] if isinstance(item, dict)]
    if managed_session_targets:
        enabled_targets: list[dict[str, Any]] = []
        ignored_names: list[str] = []
        for raw in managed_targets:
            name = str(raw.get("name") or raw.get("target_name") or "").strip()
            if not name:
                continue
            base = configured_by_name.get(name, {})
            enabled = bool(raw.get("enabled", False))
            exact = bool(raw.get("exact", base.get("exact", True)))
            allow_self = bool(base.get("allow_self_for_test", False))
            if allow_self and name != FILE_TRANSFER_ASSISTANT:
                allow_self = False
            try:
                max_batch = int(
                    raw.get("max_batch_messages", base.get("max_batch_messages", default_max_batch_messages(merged)))
                    or default_max_batch_messages(merged)
                )
            except (TypeError, ValueError):
                max_batch = default_max_batch_messages(merged)
            if enabled:
                enabled_targets.append(
                    {
                        "name": name,
                        "enabled": True,
                        "exact": exact,
                        "allow_self_for_test": allow_self,
                        "max_batch_messages": max(1, max_batch),
                    }
                )
            else:
                ignored_names.append(name)
        merged["targets"] = enabled_targets
        merged["_local_customer_service_session_routing"] = {
            "managed": True,
            "respond_all_unread_sessions": respond_all_unread_sessions,
            "ignored_names": ignored_names,
            "enabled_names": [str(item.get("name") or "") for item in enabled_targets if str(item.get("name") or "")],
        }
    else:
        merged["_local_customer_service_session_routing"] = {
            "managed": False,
            "respond_all_unread_sessions": respond_all_unread_sessions,
            "ignored_names": [],
            "enabled_names": [str(item.get("name") or "").strip() for item in configured_targets if str(item.get("name") or "").strip()],
        }
    if respond_all_unread_sessions:
        merged.setdefault("multi_target", {})
        if isinstance(merged.get("multi_target"), dict):
            merged["multi_target"]["enabled"] = True
        routing = merged.get("_local_customer_service_session_routing", {})
        if isinstance(routing, dict):
            enabled_names = {str(item).strip() for item in routing.get("enabled_names", []) or [] if str(item).strip()}
            ignored_names = {
                str(item).strip()
                for item in routing.get("ignored_names", []) or []
                if str(item).strip()
            }
            if FILE_TRANSFER_ASSISTANT not in enabled_names:
                ignored_names.add(FILE_TRANSFER_ASSISTANT)
            routing["ignored_names"] = sorted(ignored_names)
            merged["_local_customer_service_session_routing"] = routing
    use_llm = settings.get("use_llm", True) is not False
    raw_messages = dict(merged.get("raw_messages", {}) or {})
    raw_messages["enabled"] = settings.get("record_messages", True) is not False
    raw_messages["auto_learn"] = settings.get("auto_learn", True) is not False
    raw_messages["use_llm"] = use_llm
    merged["raw_messages"] = raw_messages

    intent_assist = dict(merged.get("intent_assist", {}) or {})
    intent_assist["enabled"] = use_llm
    intent_assist["mode"] = str(intent_assist.get("mode") or "heuristic")
    llm_advisory = dict(intent_assist.get("llm_advisory", {}) or {})
    llm_advisory["enabled"] = use_llm
    if use_llm and str(llm_advisory.get("provider") or "manual_json") == "manual_json" and not str(llm_advisory.get("candidate_json_path") or "").strip():
        llm_advisory["provider"] = "deepseek"
    llm_advisory.setdefault("advisory_only", True)
    llm_advisory.setdefault("apply_to_reply", False)
    intent_assist["llm_advisory"] = llm_advisory
    merged["intent_assist"] = intent_assist

    rag_response = dict(merged.get("rag_response", {}) or {})
    rag_response["enabled"] = settings.get("rag_enabled", True) is not False
    merged["rag_response"] = rag_response

    style_adapter = dict(merged.get("reply_style_adapter", {}) or {})
    style_adapter["enabled"] = settings.get("style_adapter_enabled", True) is not False
    style_adapter.setdefault("mode", "fast_local")
    style_adapter.setdefault("identity_guard_aware", True)
    merged["reply_style_adapter"] = style_adapter

    llm_synthesis = dict(merged.get("llm_reply_synthesis", {}) or {})
    llm_synthesis["enabled"] = use_llm and settings.get("llm_reply_synthesis_enabled", True) is not False
    llm_synthesis["identity_guard_enabled"] = settings.get("identity_guard_enabled", True) is not False
    if use_llm and str(llm_synthesis.get("provider") or "manual_json") == "manual_json" and not str(llm_synthesis.get("candidate_json_path") or "").strip() and not isinstance(llm_synthesis.get("candidate"), dict):
        llm_synthesis["provider"] = "deepseek"
    llm_synthesis.setdefault("mode", "guarded_auto")
    llm_synthesis.setdefault("require_evidence", True)
    llm_synthesis.setdefault("require_structured_for_authority", True)
    llm_synthesis.setdefault("fallback_to_existing_reply", True)
    merged["llm_reply_synthesis"] = llm_synthesis

    data_capture = dict(merged.get("data_capture", {}) or {})
    data_capture["enabled"] = settings.get("data_capture_enabled", True) is not False
    merged["data_capture"] = data_capture

    handoff = dict(merged.get("handoff", {}) or {})
    handoff["enabled"] = settings.get("handoff_enabled", True) is not False
    merged["handoff"] = handoff

    operator_alert = dict(merged.get("operator_alert", {}) or {})
    operator_alert["enabled"] = settings.get("operator_alert_enabled", True) is not False
    merged["operator_alert"] = operator_alert
    return merged


def update_conversation_context(target_state: dict[str, Any], product_knowledge: dict[str, Any] | None) -> None:
    if not product_knowledge:
        return
    if not product_knowledge.get("matched"):
        return
    if product_knowledge.get("match_type") != "product":
        return
    context = dict(target_state.get("conversation_context", {}) or {})
    context["last_product_id"] = product_knowledge.get("product_id")
    context["last_product_name"] = product_knowledge.get("product_name")
    context["last_product_unit"] = product_knowledge.get("product_unit")
    if product_knowledge.get("quantity") not in (None, ""):
        context["last_quantity"] = product_knowledge.get("quantity")
    if product_knowledge.get("shipping_city"):
        context["last_shipping_city"] = product_knowledge.get("shipping_city")
    if product_knowledge.get("unit_price") not in (None, ""):
        context["last_unit_price"] = product_knowledge.get("unit_price")
    if product_knowledge.get("total") not in (None, ""):
        context["last_total"] = product_knowledge.get("total")
    context["updated_at"] = datetime.now().isoformat(timespec="seconds")
    target_state["conversation_context"] = context


def maybe_analyze_intent(
    config: dict[str, Any],
    combined: str,
    decision: ReplyDecision,
    reply_text: str,
    data_capture: dict[str, Any],
    product_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config.get("intent_assist", {}) or {}
    if not settings.get("enabled", False):
        return {"enabled": False}
    mode = str(settings.get("mode") or "heuristic")
    if mode != "heuristic":
        return {
            "enabled": True,
            "mode": mode,
            "ok": False,
            "reason": "unsupported_intent_assist_mode",
        }

    evidence_pack = build_evidence_pack(
        combined,
        context=conversation_context_from_product_result(product_knowledge or {}),
    )
    analysis_context = build_intent_context(
        config,
        data_capture,
        decision,
        product_knowledge or {},
        evidence_pack=evidence_pack,
    )
    result = analyze_intent(combined, context=analysis_context)
    payload = {
        **result.__dict__,
        "ok": True,
        "advisory_only": bool(settings.get("advisory_only", True)),
        "evidence": summarize_evidence_pack(evidence_pack),
        "rule_decision": {
            "rule_name": decision.rule_name,
            "matched": decision.matched,
            "reason": decision.reason,
            "reply_text": reply_text,
        },
    }
    safety = payload.get("evidence", {}).get("safety", {}) or {}
    clear_no_relevant_handoff_after_safe_rule_match(safety, decision, combined=combined, settings=config.get("llm_reply_synthesis", {}) or {})
    if isinstance(safety, dict) and safety.get("must_handoff"):
        reasons = [str(item) for item in safety.get("reasons", []) or [] if str(item)]
        payload["needs_handoff"] = True
        payload["safe_to_auto_send"] = False
        intent_tags = payload.get("evidence", {}).get("intent_tags", []) or []
        payload["recommended_action"] = "handoff_for_approval" if "discount" in intent_tags else "handoff"
        payload["reason"] = "evidence_safety:" + ",".join(reasons) if reasons else "evidence_safety_must_handoff"
    suggested_reply = str(payload.get("suggested_reply") or "")
    payload["would_change_reply"] = bool(suggested_reply and suggested_reply not in reply_text)

    # Run LLM advisory in background so it never blocks the customer reply path.
    llm_settings = settings.get("llm_advisory", {}) or {}
    if llm_settings.get("enabled") and str(llm_settings.get("provider") or "") == "deepseek":
        def _background_advisory(
            settings_param: dict[str, Any],
            combined_param: str,
            context_param: dict[str, Any],
            heuristic_param: Any,
        ) -> None:
            try:
                adv = build_llm_advisory(
                    settings=settings_param,
                    combined=combined_param,
                    context=context_param,
                    heuristic=heuristic_param,
                )
                log_path = resolve_path("runtime/logs/wechat_customer_service/background_advisory.jsonl")
                append_jsonl(
                    log_path,
                    {
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "combined": combined_param,
                        "advisory": adv,
                    },
                )
            except Exception:
                pass

        threading.Thread(
            target=_background_advisory,
            args=(settings, combined, analysis_context, result),
            daemon=True,
        ).start()
        payload["llm_advisory"] = {
            "enabled": True,
            "provider": "deepseek",
            "status": "background_started",
            "reason": "advisory_executed_in_background",
        }
    else:
        payload["llm_advisory"] = build_llm_advisory(
            settings=settings,
            combined=combined,
            context=analysis_context,
            heuristic=result,
        )
    return payload


def clear_no_relevant_handoff_after_safe_rule_match(
    safety: dict[str, Any],
    decision: ReplyDecision,
    *,
    combined: str,
    settings: dict[str, Any],
) -> None:
    if not isinstance(safety, dict) or not safety.get("must_handoff"):
        return
    reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    if not reasons or not reasons <= {"no_relevant_business_evidence", "auto_reply_disabled"}:
        return
    if not decision.matched or decision.need_handoff or not str(decision.reply_text or "").strip():
        return
    if visible_platform_terms_hit(combined, settings=settings):
        return
    safety["must_handoff"] = False
    safety["allowed_auto_reply"] = True
    safety["reasons"] = []
    safety["configured_rule_match_override"] = True


def visible_platform_terms_hit(text: str, *, settings: dict[str, Any]) -> bool:
    platform_rules = load_platform_safety_rules(settings).get("item", {})
    clean = "".join(str(text or "").split())
    groups = (
        "forbidden_reply_terms",
        "appointment_commitment_terms",
        "commitment_terms",
    )
    return any(term and term in clean for group in groups for term in guard_term_set(platform_rules, group))


def build_intent_context(
    config: dict[str, Any],
    data_capture: dict[str, Any],
    decision: ReplyDecision,
    product_knowledge: dict[str, Any],
    evidence_pack: dict[str, Any],
) -> dict[str, Any]:
    llm_synthesis = config.get("llm_reply_synthesis", {}) or {}
    identity_guard_enabled = llm_synthesis.get("identity_guard_enabled", True) is not False
    return {
        "service_profile": config.get("service_profile", {}) or {},
        "answer_policy": {
            "use_known_facts_only": True,
            "unknown_or_authority_required_action": "handoff",
            "never_invent_price_stock_shipping_or_policy": True,
            "identity_guard_enabled": identity_guard_enabled,
        },
        "data_capture": data_capture,
        "product_knowledge": product_knowledge,
        "evidence_pack": evidence_pack,
        "rule_decision": decision.__dict__,
    }


def conversation_context_from_product_result(product_knowledge: dict[str, Any]) -> dict[str, Any]:
    if not product_knowledge:
        return {}
    return {
        "last_product_id": product_knowledge.get("product_id"),
        "last_product_name": product_knowledge.get("product_name"),
        "last_quantity": product_knowledge.get("quantity"),
        "last_unit_price": product_knowledge.get("unit_price"),
        "last_total": product_knowledge.get("total"),
        "last_shipping_city": product_knowledge.get("shipping_city"),
    }


def summarize_evidence_pack(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    evidence = evidence_pack.get("evidence", {}) or {}
    rag = evidence_pack.get("rag_evidence", {}) or {}
    rag_hits = [
        {
            "chunk_id": item.get("chunk_id"),
            "source_id": item.get("source_id"),
            "score": item.get("score"),
            "category": item.get("category"),
            "source_type": item.get("source_type"),
            "product_id": item.get("product_id"),
            "retrieval_mode": item.get("retrieval_mode"),
            "scoring": item.get("scoring", {}),
            "risk_terms": item.get("risk_terms", []),
            "text": str(item.get("text") or "")[:260],
        }
        for item in rag.get("hits", []) or []
        if isinstance(item, dict)
    ]
    return {
        "scope": evidence_pack.get("scope"),
        "intent_tags": evidence_pack.get("intent_tags", []),
        "selected_item_ids": [item.get("id") for item in evidence_pack.get("selected_items", []) or []],
        "product_ids": [item.get("id") for item in evidence.get("products", []) or [] if item.get("id")],
        "faq_intents": [item.get("intent") for item in evidence.get("faq", []) or [] if item.get("intent")],
        "policy_keys": sorted((evidence.get("policies", {}) or {}).keys()),
        "product_scoped_ids": [item.get("id") for item in evidence.get("product_scoped", []) or [] if item.get("id")],
        "style_example_ids": [item.get("id") for item in evidence.get("style_examples", []) or [] if item.get("id")],
        "rag_chunk_ids": [item.get("chunk_id") for item in rag_hits if item.get("chunk_id")],
        "rag_hits": rag_hits,
        "rag_confidence": rag.get("confidence", 0.0),
        "rag_can_authorize": bool(rag.get("rag_can_authorize", False)),
        "rag_structured_priority": bool(rag.get("structured_priority", True)),
        "safety": evidence_pack.get("safety", {}),
    }


def skipped_intent_assist(
    config: dict[str, Any],
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config.get("intent_assist", {}) or {}
    payload: dict[str, Any] = {
        "enabled": bool(settings.get("enabled", False)),
        "skipped": True,
        "reason": reason,
    }
    if settings:
        payload["mode"] = str(settings.get("mode") or "heuristic")
        llm_settings = settings.get("llm_advisory", {}) or {}
        if llm_settings:
            payload["llm_advisory"] = {
                "enabled": bool(llm_settings.get("enabled", False)),
                "skipped": True,
                "reason": reason,
            }
    if extra:
        payload.update(extra)
    return payload


def build_llm_advisory(
    settings: dict[str, Any],
    combined: str,
    context: dict[str, Any],
    heuristic: Any,
) -> dict[str, Any]:
    llm_settings = settings.get("llm_advisory", {}) or {}
    if not llm_settings.get("enabled", False):
        return {"enabled": False}

    provider = resolve_effective_llm_provider(llm_settings.get("provider") or "manual_json")
    prompt_pack = build_llm_prompt_pack(combined, context=context, heuristic=heuristic)
    advisory: dict[str, Any] = {
        "enabled": True,
        "provider": provider,
        "advisory_only": bool(llm_settings.get("advisory_only", True)),
        "schema_version": prompt_pack.get("schema_version"),
        "status": "prompt_pack_ready",
    }
    if llm_settings.get("include_prompt_in_audit", False):
        advisory["prompt_pack"] = prompt_pack

    if provider != "manual_json":
        advisory["status"] = "provider_called"
        advisory["result"] = call_deepseek_advisory(
            combined,
            context=context,
            heuristic=heuristic,
            provider=provider,
            model=str(llm_settings.get("model") or ""),
            base_url=str(llm_settings.get("base_url") or ""),
            timeout=int(llm_settings.get("timeout_seconds", 15)),
        )
        return advisory

    candidate_path_value = str(llm_settings.get("candidate_json_path") or "").strip()
    if not candidate_path_value:
        return advisory

    candidate_path = resolve_path(candidate_path_value)
    advisory["candidate_json_path"] = str(candidate_path)
    if not candidate_path.exists():
        advisory["status"] = "candidate_file_missing"
        return advisory

    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except Exception as exc:
        advisory["status"] = "candidate_file_error"
        advisory["error"] = repr(exc)
        return advisory

    advisory["status"] = "candidate_validated"
    advisory["validation"] = validate_llm_candidate(candidate, heuristic=heuristic)
    return advisory


def maybe_apply_llm_reply(
    config: dict[str, Any],
    decision: ReplyDecision,
    reply_text: str,
    intent_assist: dict[str, Any],
    product_knowledge: dict[str, Any],
    data_capture: dict[str, Any],
) -> dict[str, Any]:
    settings = (config.get("intent_assist", {}) or {}).get("llm_advisory", {}) or {}
    payload: dict[str, Any] = {
        "enabled": bool(settings.get("enabled", False)),
        "apply_to_reply": bool(settings.get("apply_to_reply", False)),
        "applied": False,
    }
    if not payload["enabled"]:
        payload["reason"] = "llm_disabled"
        return payload
    if not payload["apply_to_reply"]:
        payload["reason"] = "apply_to_reply_disabled"
        return payload
    if evidence_requires_handoff(intent_assist) or (product_knowledge and product_knowledge.get("needs_handoff")) or (product_knowledge and product_knowledge.get("auto_reply_allowed") is False):
        payload["reason"] = "handoff_required_before_llm_reply"
        return payload

    candidate = llm_candidate_from_intent_assist(intent_assist)
    if not candidate:
        payload["reason"] = "llm_candidate_unavailable"
        payload["llm_status"] = llm_status(intent_assist)
        return payload
    payload["candidate"] = {
        "intent": candidate.get("intent"),
        "confidence": candidate.get("confidence"),
        "recommended_action": candidate.get("recommended_action"),
        "safe_to_auto_send": candidate.get("safe_to_auto_send"),
        "needs_handoff": candidate.get("needs_handoff"),
        "reason": candidate.get("reason"),
    }

    if candidate.get("needs_handoff"):
        if not settings.get("allow_llm_handoff", True):
            payload["reason"] = "llm_handoff_not_allowed"
            return payload
        payload.update(
            {
                "applied": True,
                "rule_name": "llm_boundary_handoff",
                "reason": str(candidate.get("reason") or "llm_boundary_handoff"),
                "needs_handoff": True,
                "raw_reply_text": handoff_acknowledgement_text(config),
                "reply_text": format_reply(handoff_acknowledgement_text(config), configured_reply_prefix(config)),
            }
        )
        return payload

    if not candidate.get("safe_to_auto_send"):
        payload["reason"] = "llm_candidate_not_safe_to_auto_send"
        return payload
    try:
        confidence = float(candidate.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    min_confidence = float(settings.get("min_apply_confidence", 0.62) or 0.62)
    if confidence < min_confidence:
        payload["reason"] = "llm_confidence_below_threshold"
        payload["min_confidence"] = min_confidence
        return payload

    suggested_reply = str(candidate.get("suggested_reply") or "").strip()
    if not suggested_reply:
        payload["reason"] = "llm_candidate_empty_reply"
        return payload
    if not llm_reply_allowed_for_decision(settings, candidate, decision, product_knowledge, intent_assist):
        payload["reason"] = "llm_candidate_not_allowed_for_decision"
        return payload

    payload.update(
        {
            "applied": True,
            "rule_name": "llm_boundary_reply",
            "reason": str(candidate.get("reason") or "llm_boundary_auto_reply"),
            "needs_handoff": False,
            "raw_reply_text": suggested_reply,
            "reply_text": format_reply(suggested_reply, configured_reply_prefix(config)),
        }
    )
    return payload


def llm_candidate_from_intent_assist(intent_assist: dict[str, Any]) -> dict[str, Any] | None:
    advisory = intent_assist.get("llm_advisory", {}) or {}
    result = advisory.get("result", {}) or {}
    validation = result.get("validation", {}) or advisory.get("validation", {}) or {}
    if not validation.get("ok"):
        return None
    candidate = validation.get("candidate", {}) or {}
    return candidate if isinstance(candidate, dict) else None


def llm_status(intent_assist: dict[str, Any]) -> dict[str, Any]:
    advisory = intent_assist.get("llm_advisory", {}) or {}
    result = advisory.get("result", {}) or {}
    return {
        "advisory_status": advisory.get("status"),
        "provider": advisory.get("provider"),
        "result_ok": result.get("ok"),
        "result_error": result.get("error"),
        "validation_errors": (result.get("validation", {}) or {}).get("errors", []),
    }


def llm_reply_allowed_for_decision(
    settings: dict[str, Any],
    candidate: dict[str, Any],
    decision: ReplyDecision,
    product_knowledge: dict[str, Any],
    intent_assist: dict[str, Any],
) -> bool:
    if decision.rule_name in {"customer_data_capture", "customer_data_incomplete"}:
        return False
    action = str(candidate.get("recommended_action") or "")
    intent = str(candidate.get("intent") or "")

    if not business_evidence_available(intent_assist, product_knowledge):
        small_talk_actions = {"reply_greeting", "reply_small_talk", "review_or_default_reply"}
        if settings.get("apply_to_small_talk", True) and action in small_talk_actions and intent in {"greeting", "small_talk", "unknown"}:
            return True
        return False

    if not decision.matched or decision.reason == "no_rule_matched":
        return True
    if product_knowledge and product_knowledge.get("matched") and settings.get("apply_to_matched_product", False):
        return True
    policy_actions = {
        "answer_company_info",
        "answer_invoice_policy",
        "answer_payment_policy",
        "answer_logistics_policy",
        "answer_after_sales_policy",
    }
    if action in policy_actions and settings.get("apply_to_policy_reply", False):
        return True
    return False


def business_evidence_available(intent_assist: dict[str, Any], product_knowledge: dict[str, Any] | None) -> bool:
    if product_knowledge and product_knowledge.get("matched"):
        return True
    evidence = intent_assist.get("evidence", {}) or {}
    return bool(
        evidence.get("product_ids")
        or evidence.get("faq_intents")
        or evidence.get("policy_keys")
    )


def data_capture_reply(config: dict[str, Any], data_capture: dict[str, Any], complete: bool) -> str:
    settings = config.get("data_capture", {}) or {}
    if complete:
        return str(settings.get("success_reply") or "资料我收到了，后面按这个继续跟进。")
    missing = "、".join(data_capture.get("missing_required_labels", []) or data_capture.get("missing_required_fields", []) or [])
    template = str(
        settings.get("incomplete_reply")
        or "好的，这块我记下了。另外还需要您的{missing_fields}，方便后续跟进，您发我一下就好~"
    )
    return template.format(missing_fields=missing)


def finalize_data_capture_state(target_state: dict[str, Any], data_capture: dict[str, Any]) -> None:
    if not data_capture.get("enabled") or not data_capture.get("is_customer_data"):
        return
    if data_capture.get("complete") and data_capture.get("write_result", {}).get("ok"):
        close_pending_customer_data(target_state, data_capture)
    elif not data_capture.get("complete"):
        upsert_pending_customer_data(target_state, data_capture)


def get_open_pending_customer_data(target_state: dict[str, Any]) -> dict[str, Any] | None:
    pending_items = target_state.get("pending_customer_data", []) or []
    for item in reversed(pending_items):
        if item.get("status") == "waiting_for_fields":
            return item
    return None


def upsert_pending_customer_data(target_state: dict[str, Any], data_capture: dict[str, Any]) -> None:
    pending_items = list(target_state.get("pending_customer_data", []) or [])
    pending = get_open_pending_customer_data(target_state)
    entry = {
        "status": "waiting_for_fields",
        "fields": data_capture.get("fields", {}),
        "missing_required_fields": data_capture.get("missing_required_fields", []),
        "missing_required_labels": data_capture.get("missing_required_labels", []),
        "message_ids": data_capture.get("message_ids", []),
        "raw_text": data_capture.get("raw_text", ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if pending:
        entry["created_at"] = pending.get("created_at") or entry["updated_at"]
        for index, item in enumerate(pending_items):
            if item is pending:
                pending_items[index] = entry
                break
        else:
            pending_items.append(entry)
    else:
        entry["created_at"] = entry["updated_at"]
        pending_items.append(entry)
    target_state["pending_customer_data"] = pending_items[-MAX_STORED_IDS:]


def close_pending_customer_data(target_state: dict[str, Any], data_capture: dict[str, Any]) -> None:
    pending_items = list(target_state.get("pending_customer_data", []) or [])
    now = datetime.now().isoformat(timespec="seconds")
    for item in reversed(pending_items):
        if item.get("status") == "waiting_for_fields":
            item["status"] = "completed"
            item["completed_at"] = now
            item["completed_message_ids"] = data_capture.get("message_ids", [])
            item["write_result"] = data_capture.get("write_result")
            break
    target_state["pending_customer_data"] = pending_items[-MAX_STORED_IDS:]


def missing_field_labels(fields: list[str]) -> list[str]:
    labels = {
        "name": "姓名",
        "phone": "电话",
        "address": "地址",
        "product": "产品",
        "quantity": "数量",
        "spec": "规格",
        "budget": "预算",
        "note": "备注",
    }
    return [labels.get(field, field) for field in fields]


def unique_list(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def configured_reply_prefix(config: dict[str, Any]) -> str:
    return str(config.get("reply", {}).get("prefix", BOT_PREFIX + " "))


def bot_reply_prefixes(config: dict[str, Any] | None = None) -> list[str]:
    prefixes = [BOT_PREFIX, BOT_PREFIX + " "]
    if config:
        configured = configured_reply_prefix(config)
        prefixes.extend([configured, configured.rstrip()])
    return unique_list([prefix for prefix in prefixes if prefix])


def is_bot_reply_content(content: str, config: dict[str, Any] | None = None) -> bool:
    stripped = str(content or "").strip()
    if not stripped:
        return False
    if stripped.startswith("[OmniAuto"):
        return True
    return any(stripped.startswith(prefix.strip()) for prefix in bot_reply_prefixes(config))


def evidence_safety(intent_assist: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent_assist, dict):
        return {}
    evidence = intent_assist.get("evidence", {}) or {}
    if not isinstance(evidence, dict):
        return {}
    safety = evidence.get("safety", {}) or {}
    return safety if isinstance(safety, dict) else {}


def evidence_requires_handoff(intent_assist: dict[str, Any] | None) -> bool:
    return bool(evidence_safety(intent_assist).get("must_handoff"))


def customer_data_write_allowed_before_handoff(intent_assist: dict[str, Any] | None) -> bool:
    """Allow lead capture before handoff only when the handoff is not approval/risk driven."""
    safety = evidence_safety(intent_assist)
    reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    soft_handoff_reasons = {"no_relevant_business_evidence"}
    if safety.get("must_handoff") and not (reasons and reasons <= soft_handoff_reasons):
        return False
    discount_check = safety.get("discount_check", {}) or {}
    if isinstance(discount_check, dict) and discount_check.get("needs_handoff"):
        return False
    blocking_fragments = ("discount", "approval", "below_public_tier", "price_or_policy")
    return not any(fragment in reason for reason in reasons for fragment in blocking_fragments)


def evidence_handoff_reason(intent_assist: dict[str, Any] | None) -> str:
    safety = evidence_safety(intent_assist)
    if not safety.get("must_handoff"):
        return ""
    reasons = [str(item) for item in safety.get("reasons", []) or [] if str(item)]
    if reasons:
        return "evidence_safety:" + ",".join(reasons)
    return "evidence_safety_must_handoff"


def clear_no_relevant_handoff_after_safe_synthesis(
    intent_assist: dict[str, Any] | None,
    llm_synthesis: dict[str, Any],
) -> None:
    if not isinstance(intent_assist, dict):
        return
    if not llm_synthesis.get("applied") or llm_synthesis.get("needs_handoff"):
        return
    guard = llm_synthesis.get("guard", {}) or {}
    if guard.get("action") != "send_reply" or guard.get("reason") not in {"guard_passed", "llm_soft_handoff_downgraded"}:
        return
    summary = llm_synthesis.get("evidence_summary", {}) or {}
    if int(summary.get("structured_evidence_count") or 0) <= 0 and int(summary.get("rag_hit_count") or 0) <= 0:
        return
    safety = evidence_safety(intent_assist)
    reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    if not reasons or not reasons <= {"no_relevant_business_evidence", "auto_reply_disabled"}:
        return
    safety["must_handoff"] = False
    safety["allowed_auto_reply"] = True
    safety["reasons"] = []
    safety["llm_synthesis_soft_evidence_override"] = True


def clear_no_relevant_handoff_after_safe_realtime_reply(
    intent_assist: dict[str, Any] | None,
    realtime_reply: dict[str, Any],
) -> None:
    if not isinstance(intent_assist, dict) or not realtime_reply.get("applied"):
        return
    safety = evidence_safety(intent_assist)
    reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    safe_rule_names = {
        "realtime_vehicle_compare_guidance",
        "realtime_vehicle_type_guidance",
        "realtime_maintenance_cost_guidance",
        "realtime_inspection_guidance",
        "realtime_feature_guidance",
        "realtime_comfort_highway_guidance",
        "realtime_finance_guidance",
        "realtime_fee_guidance",
        "realtime_testdrive_materials",
        "realtime_visit_timing",
        "realtime_no_deposit_visit_guidance",
        "realtime_price_negotiation",
        "realtime_warranty_guidance",
        "realtime_trade_in_collect",
        "realtime_value_retention_followup",
        "realtime_new_energy_check",
        "realtime_local_recommendation",
    }
    rule_name = str(realtime_reply.get("rule_name") or "")
    if rule_name in safe_rule_names:
        safety["must_handoff"] = False
        safety["allowed_auto_reply"] = True
        safety["reasons"] = []
        safety["realtime_reply_safe_rule_override"] = rule_name
        return
    if not reasons or not reasons <= {"no_relevant_business_evidence", "auto_reply_disabled"}:
        return
    safety["must_handoff"] = False
    safety["allowed_auto_reply"] = True
    safety["reasons"] = []
    safety["realtime_reply_soft_evidence_override"] = True


def maybe_enrich_messages_with_history(
    *,
    connector: WeChatConnector,
    target: TargetConfig,
    config: dict[str, Any],
    payload: dict[str, Any],
    target_state: dict[str, Any],
) -> dict[str, Any]:
    settings = history_backfill_settings(config)
    if not settings.get("enabled"):
        enriched = dict(payload)
        enriched["_history_backfill"] = {"enabled": False, "applied": False, "reason": "disabled"}
        return enriched

    messages = payload.get("messages", []) or []
    initial_selection = select_batch_details(
        messages,
        target_state=target_state,
        allow_self_for_test=target.allow_self_for_test,
        max_batch_messages=target.max_batch_messages,
        config=config,
    )
    trigger_reasons: list[str] = []
    trigger_count = positive_int(settings.get("trigger_visible_unprocessed_count"), 6)
    saturated_count = positive_int(settings.get("trigger_visible_saturated_count"), 5)
    if initial_selection.eligible_count >= trigger_count:
        trigger_reasons.append("visible_unprocessed_threshold")
    elif initial_selection.eligible_count >= saturated_count and len(messages) <= saturated_count + 1:
        trigger_reasons.append("visible_window_saturated")
    if initial_selection.truncated:
        trigger_reasons.append("batch_truncated")
    if not trigger_reasons:
        enriched = dict(payload)
        enriched["_history_backfill"] = {
            "enabled": True,
            "applied": False,
            "reason": "trigger_not_met",
            "eligible_count": initial_selection.eligible_count,
            "trigger_visible_unprocessed_count": trigger_count,
            "trigger_visible_saturated_count": saturated_count,
        }
        return enriched

    load_times = bounded_positive_int(
        settings.get("load_times"),
        default=2,
        maximum=positive_int(settings.get("max_load_times"), 5),
    )
    if load_times <= 0:
        enriched = dict(payload)
        enriched["_history_backfill"] = {
            "enabled": True,
            "applied": False,
            "reason": "load_times_zero",
            "trigger_reasons": trigger_reasons,
        }
        return enriched

    try:
        loaded = connector.get_messages(target.name, exact=target.exact, history_load_times=load_times)
    except Exception as exc:
        enriched = dict(payload)
        enriched["_history_backfill"] = {
            "enabled": True,
            "applied": False,
            "reason": "history_load_exception",
            "error": repr(exc),
            "trigger_reasons": trigger_reasons,
            "load_times": load_times,
        }
        return enriched

    if not loaded.get("ok"):
        enriched = dict(payload)
        enriched["_history_backfill"] = {
            "enabled": True,
            "applied": False,
            "reason": "history_load_failed",
            "result": loaded,
            "trigger_reasons": trigger_reasons,
            "load_times": load_times,
        }
        return enriched
    sidecar_history_load = loaded.get("history_load") if isinstance(loaded.get("history_load"), dict) else {}
    if sidecar_history_load and sidecar_history_load.get("ok") is False:
        enriched = dict(payload)
        enriched["_history_backfill"] = {
            "enabled": True,
            "applied": False,
            "reason": "history_load_failed",
            "trigger_reasons": trigger_reasons,
            "load_times": load_times,
            "sidecar_history_load": sidecar_history_load,
        }
        return enriched

    max_messages = positive_int(settings.get("max_messages_after_load"), 80)
    merged_messages = merge_message_windows(
        loaded.get("messages", []) or [],
        messages,
        max_messages=max_messages,
    )
    enriched = dict(loaded)
    enriched["messages"] = merged_messages
    enriched["_history_backfill"] = {
        "enabled": True,
        "applied": True,
        "mechanism": str(sidecar_history_load.get("mechanism") or "wxauto4.history_load"),
        "trigger_reasons": trigger_reasons,
        "load_times": load_times,
        "initial_message_count": len(messages),
        "loaded_message_count": len(loaded.get("messages", []) or []),
        "final_message_count": len(merged_messages),
        "sidecar_history_load": sidecar_history_load,
    }
    return enriched


def history_backfill_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    settings = dict(cfg.get("history_backfill", {}) or {})
    settings.setdefault("enabled", True)
    settings.setdefault("load_times", 2)
    settings.setdefault("max_load_times", 5)
    settings.setdefault("trigger_visible_unprocessed_count", 6)
    settings.setdefault("trigger_visible_saturated_count", 5)
    settings.setdefault("max_messages_after_load", 80)
    settings.setdefault("freshness_load_times", settings.get("load_times", 2))
    return settings


def merge_message_windows(*windows: list[dict[str, Any]], max_messages: int = 80) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for window in windows:
        for item in window or []:
            if not isinstance(item, dict):
                continue
            key = message_dedupe_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    if max_messages > 0 and len(merged) > max_messages:
        return merged[-max_messages:]
    return merged


def message_dedupe_key(message: dict[str, Any]) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id:
        return f"id:{message_id}"
    return "fallback:" + hashlib.sha256(
        json.dumps(
            {
                "sender": message.get("sender"),
                "type": message.get("type"),
                "time": message.get("time"),
                "content": message.get("content"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]


def positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def bounded_positive_int(value: Any, *, default: int, maximum: int) -> int:
    parsed = positive_int(value, default)
    return max(0, min(maximum, parsed))


def bootstrap_target(
    connector: WeChatConnector,
    target: TargetConfig,
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    target_state = state.setdefault("targets", {}).setdefault(
        target.name,
        {
            "processed_message_ids": [],
            "handoff_message_ids": [],
            "sent_replies": [],
            "reply_timestamps": [],
        },
    )
    payload = connector.get_messages(target.name, exact=target.exact)
    if not payload.get("ok"):
        return base_event(target, "error", {"messages": payload})

    processed = list(target_state.get("processed_message_ids", []))
    added = []
    for message in payload.get("messages", []) or []:
        message_id = str(message.get("id") or "")
        content = str(message.get("content") or "").strip()
        if not message_id or not content or message.get("type") != "text":
            continue
        if is_bot_reply_content(content, config):
            continue
        if message_id not in processed:
            processed.append(message_id)
            added.append(message_id)
    target_state["processed_message_ids"] = processed[-MAX_STORED_IDS:]
    target_state.setdefault("bootstrap_events", []).append(
        {
            "message_ids": added,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return base_event(
        target,
        "bootstrapped",
        {"marked_message_ids": added, "marked_count": len(added)},
    )


def select_batch(
    messages: list[dict[str, Any]],
    target_state: dict[str, Any],
    allow_self_for_test: bool,
    max_batch_messages: int,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return select_batch_details(
        messages,
        target_state=target_state,
        allow_self_for_test=allow_self_for_test,
        max_batch_messages=max_batch_messages,
        config=config,
    ).batch


def select_batch_details(
    messages: list[dict[str, Any]],
    target_state: dict[str, Any],
    allow_self_for_test: bool,
    max_batch_messages: int,
    config: dict[str, Any] | None = None,
) -> BatchSelection:
    processed = set(target_state.get("processed_message_ids", []))
    handoff = set(target_state.get("handoff_message_ids", []))
    sent_reply_content_keys = recent_sent_reply_content_keys(target_state)
    selected: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    try:
        limit = max(1, int(max_batch_messages or DEFAULT_MAX_BATCH_MESSAGES))
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_BATCH_MESSAGES
    for message in reversed(messages):
        if not message_is_reply_candidate(
            message,
            processed=processed,
            handoff=handoff,
            allow_self_for_test=allow_self_for_test,
            config=config,
            sent_reply_content_keys=sent_reply_content_keys,
        ):
            if selected or overflow:
                break
            continue
        if len(selected) < limit:
            selected.append(message)
        else:
            overflow.append(message)
    batch = list(reversed(selected))
    overflow_messages = list(reversed(overflow))
    return BatchSelection(
        batch=batch,
        overflow_messages=overflow_messages,
        eligible_count=len(batch) + len(overflow_messages),
        max_batch_messages=limit,
    )


def message_is_reply_candidate(
    message: dict[str, Any],
    *,
    processed: set[str],
    handoff: set[str],
    allow_self_for_test: bool,
    config: dict[str, Any] | None = None,
    sent_reply_content_keys: set[str] | None = None,
) -> bool:
    message_id = str(message.get("id") or "")
    content = str(message.get("content") or "").strip()
    sender = str(message.get("sender") or "")
    if not message_id or message_id in processed or message_id in handoff:
        return False
    if message.get("type") != "text" or not content:
        return False
    if is_bot_reply_content(content, config):
        return False
    if sender == "self" and not allow_self_for_test:
        return False
    if sender == "self" and allow_self_for_test and sent_reply_content_keys:
        if normalize_reply_content_key(content) in sent_reply_content_keys:
            return False
    return True


def batch_selection_payload(selection: BatchSelection) -> dict[str, Any]:
    overflow = selection.overflow_messages
    return {
        "message_ids": [str(item.get("id") or "") for item in selection.batch],
        "overflow_message_ids": [str(item.get("id") or "") for item in overflow],
        "overflow_count": len(overflow),
        "eligible_count": selection.eligible_count,
        "max_batch_messages": selection.max_batch_messages,
        "truncated": selection.truncated,
    }


def plan_message_batch_semantics(batch: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = semantic_batch_settings(config)
    texts = [str(item.get("content") or "").strip() for item in batch if str(item.get("content") or "").strip()]
    if not texts:
        return {
            "enabled": bool(settings.get("enabled")),
            "kind": "empty",
            "reply_strategy": "skip",
            "risk_level": "normal",
            "combined_text": "",
            "segments": [],
        }
    if not settings.get("enabled") or len(texts) == 1:
        text = texts[0] if len(texts) == 1 else "\n".join(texts)
        return {
            "enabled": bool(settings.get("enabled")),
            "kind": "single_event",
            "reply_strategy": "answer_as_one_need",
            "risk_level": "normal",
            "combined_text": text,
            "segments": build_semantic_segments(texts),
        }

    max_messages = positive_int(settings.get("max_messages"), 12)
    considered = texts[-max_messages:]
    segments = build_semantic_segments(considered)
    categories = {category for segment in segments for category in segment.get("categories", [])}
    risk_categories = categories & {"document_boundary", "identity_probe", "off_topic", "after_sales_dispute", "price_approval"}

    if looks_like_spam_or_noise(considered, threshold=float(settings.get("spam_repeat_threshold", 0.72) or 0.72)):
        kind = "spam_or_noise"
        strategy = "short_stabilize_and_do_not_answer_every_line"
        risk_level = "attention"
    elif risk_categories and len(categories - risk_categories) > 0:
        kind = "multi_question_mixed_risk"
        strategy = "answer_safe_parts_and_defer_risk_parts"
        risk_level = "boundary"
    elif is_single_need_fragment_batch(segments):
        kind = "single_event"
        strategy = "answer_as_one_need"
        risk_level = "normal"
    elif len(categories) > 1:
        kind = "multi_question_same_scene"
        strategy = "answer_in_natural_points"
        risk_level = "normal" if not risk_categories else "boundary"
    else:
        kind = "single_event"
        strategy = "answer_as_one_need"
        risk_level = "normal"

    return {
        "enabled": True,
        "kind": kind,
        "reply_strategy": strategy,
        "risk_level": risk_level,
        "combined_text": build_semantic_combined_text(kind, considered),
        "segments": segments,
        "message_count": len(texts),
        "considered_count": len(considered),
    }


def semantic_batch_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    settings = dict(cfg.get("semantic_batch_planner", {}) or {})
    settings.setdefault("enabled", True)
    settings.setdefault("max_messages", 12)
    settings.setdefault("spam_repeat_threshold", 0.72)
    return settings


def build_semantic_segments(texts: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "index": index + 1,
            "text": text,
            "categories": sorted(classify_message_semantics(text)),
            "question_like": is_question_like(text),
        }
        for index, text in enumerate(texts)
    ]


def classify_message_semantics(text: str) -> set[str]:
    clean = normalize_semantic_text(text)
    categories: set[str] = set()
    if any(term in clean for term in ("预算", "万", "价格", "价位", "左右")):
        categories.add("budget_or_price")
    if any(term in clean for term in ("推荐", "怎么选", "适合", "家用", "通勤", "省油", "自动挡", "代步")):
        categories.add("selection_need")
    if any(term in clean for term in ("有车", "现车", "车源", "车型", "公里", "年份", "车况")):
        categories.add("vehicle_source")
    if any(term in clean for term in ("分期", "贷款", "首付", "月供", "金融")):
        categories.add("finance")
    if any(term in clean for term in APPOINTMENT_TERMS):
        categories.add("appointment")
    if any(term in clean for term in TRADE_IN_TERMS):
        categories.add("trade_in")
    if any(term in clean for term in DOCUMENT_TERMS):
        categories.add("document_boundary")
    if any(term in clean for term in INTERNAL_PROBE_TERMS):
        categories.add("identity_probe")
    if any(term in clean for term in OFF_TOPIC_TERMS):
        categories.add("off_topic")
    if any(term in clean for term in AFTER_SALES_TERMS):
        categories.add("after_sales_dispute")
    if any(term in clean for term in ("最低", "优惠", "折扣", "少点", "便宜点", "还能便宜")):
        categories.add("price_approval")
    if not categories:
        categories.add("general")
    return categories


def normalize_semantic_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def is_question_like(text: str) -> bool:
    clean = str(text or "").strip()
    return any(marker in clean for marker in ("?", "？", "吗", "么", "怎么", "多少", "能不能", "有没有", "可不可以"))


def is_single_need_fragment_batch(segments: list[dict[str, Any]]) -> bool:
    if len(segments) <= 1:
        return True
    categories = {category for segment in segments for category in segment.get("categories", [])}
    complementary = {"budget_or_price", "selection_need", "vehicle_source", "trade_in", "general"}
    if categories <= complementary:
        question_count = sum(1 for segment in segments if segment.get("question_like"))
        short_count = sum(1 for segment in segments if len(str(segment.get("text") or "")) <= 18)
        return question_count <= 1 or short_count >= max(1, len(segments) - 1)
    return False


def looks_like_spam_or_noise(texts: list[str], *, threshold: float) -> bool:
    if len(texts) < 8:
        return False
    normalized = [normalize_semantic_text(text) for text in texts if normalize_semantic_text(text)]
    if not normalized:
        return True
    unique_ratio = len(set(normalized)) / max(1, len(normalized))
    if unique_ratio <= max(0.1, 1.0 - threshold):
        return True
    short_noise = sum(1 for text in normalized if len(text) <= 3)
    return short_noise >= max(6, int(len(normalized) * 0.7))


def build_semantic_combined_text(kind: str, texts: list[str]) -> str:
    if kind == "single_event":
        return "客户连续补充同一个需求：\n" + "\n".join(f"- {text}" for text in texts)
    if kind == "multi_question_mixed_risk":
        return "客户连续发来多个问题，其中包含需要请示确认的边界问题：\n" + "\n".join(
            f"{index}. {text}" for index, text in enumerate(texts, 1)
        )
    if kind == "spam_or_noise":
        return "客户连续发送了多条重复或较碎的信息，请结合最新有效信息简短回应：\n" + "\n".join(
            f"- {text}" for text in texts[-8:]
        )
    return "客户连续问了几个相关问题：\n" + "\n".join(f"{index}. {text}" for index, text in enumerate(texts, 1))


def detect_newer_messages_before_send(
    *,
    connector: WeChatConnector,
    target: TargetConfig,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prevent sending a stale LLM reply when the customer talks during thinking."""
    original_ids = [str(item.get("id") or "") for item in batch if str(item.get("id") or "")]
    original_content_keys = {
        key
        for key in (message_stable_content_key(item) for item in batch)
        if key
    }
    if not original_ids:
        return {"ok": True, "has_newer_messages": False, "reason": "empty_batch"}
    payload = connector.get_messages(target.name, exact=target.exact)
    if not payload.get("ok"):
        return {"ok": False, "has_newer_messages": False, "reason": "latest_read_failed", "messages": payload}
    messages = payload.get("messages", []) or []
    history_meta: dict[str, Any] = {"applied": False}
    latest_original_index = -1
    original_set = set(original_ids)
    for index, message in enumerate(messages):
        if message_matches_original_batch(message, original_set, original_content_keys):
            latest_original_index = max(latest_original_index, index)
    if latest_original_index < 0:
        settings = history_backfill_settings(config)
        load_times = bounded_positive_int(
            settings.get("freshness_load_times"),
            default=0,
            maximum=positive_int(settings.get("max_load_times"), 5),
        )
        if settings.get("enabled") and load_times > 0:
            try:
                loaded = connector.get_messages(target.name, exact=target.exact, history_load_times=load_times)
            except Exception as exc:
                loaded = {"ok": False, "error": repr(exc)}
            history_meta = {
                "applied": bool(loaded.get("ok")),
                "mechanism": str((loaded.get("history_load") or {}).get("mechanism") or "wxauto4.history_load"),
                "load_times": load_times,
                "result_ok": bool(loaded.get("ok")),
                "error": loaded.get("error"),
                "sidecar_history_load": loaded.get("history_load"),
            }
            if loaded.get("ok"):
                messages = merge_message_windows(
                    loaded.get("messages", []) or [],
                    messages,
                    max_messages=positive_int(settings.get("max_messages_after_load"), 80),
                )
                latest_original_index = -1
                for index, message in enumerate(messages):
                    if message_matches_original_batch(message, original_set, original_content_keys):
                        latest_original_index = max(latest_original_index, index)
        if latest_original_index >= 0:
            history_meta["original_batch_found_after_history_load"] = True
        else:
            history_meta["original_batch_found_after_history_load"] = False
    if latest_original_index < 0:
        processed = set(target_state.get("processed_message_ids", []))
        handoff = set(target_state.get("handoff_message_ids", []))
        sent_reply_content_keys = recent_sent_reply_content_keys(target_state)
        visible_unprocessed = [
            {
                "id": str(message.get("id") or ""),
                "content": str(message.get("content") or "").strip()[:220],
                "sender": str(message.get("sender") or ""),
            }
            for message in messages
            if message_is_reply_candidate(
                message,
                processed=processed,
                handoff=handoff,
                allow_self_for_test=target.allow_self_for_test,
                config=config,
                sent_reply_content_keys=sent_reply_content_keys,
            )
            and not message_matches_original_batch(message, original_set, original_content_keys)
        ]
        return {
            "ok": True,
            "has_newer_messages": bool(visible_unprocessed),
            "reason": (
                "original_batch_not_visible_assume_stale"
                if visible_unprocessed
                else "original_batch_not_found_no_visible_unprocessed"
            ),
            "newer_message_ids": [item["id"] for item in visible_unprocessed],
            "newer_messages": visible_unprocessed[:5],
            "history_backfill": history_meta,
        }
    processed = set(target_state.get("processed_message_ids", []))
    handoff = set(target_state.get("handoff_message_ids", []))
    sent_reply_content_keys = recent_sent_reply_content_keys(target_state)
    newer: list[dict[str, Any]] = []
    for message in messages[latest_original_index + 1 :]:
        if not message_is_reply_candidate(
            message,
            processed=processed,
            handoff=handoff,
            allow_self_for_test=target.allow_self_for_test,
            config=config,
            sent_reply_content_keys=sent_reply_content_keys,
        ):
            continue
        message_id = str(message.get("id") or "")
        content = str(message.get("content") or "").strip()
        sender = str(message.get("sender") or "")
        if message_matches_original_batch(message, original_set, original_content_keys):
            continue
        newer.append({"id": message_id, "content": content[:220], "sender": sender})
    return {
        "ok": True,
        "has_newer_messages": bool(newer),
        "newer_message_ids": [item["id"] for item in newer],
        "newer_messages": newer[:5],
        "history_backfill": history_meta,
    }


def message_matches_original_batch(
    message: dict[str, Any],
    original_ids: set[str],
    original_content_keys: set[str],
) -> bool:
    message_id = str(message.get("id") or "")
    if message_id and message_id in original_ids:
        return True
    stable_key = message_stable_content_key(message)
    return bool(stable_key and stable_key in original_content_keys)


def message_stable_content_key(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    if not content:
        return ""
    return "\x1f".join(
        [
            str(message.get("sender") or "").strip(),
            str(message.get("type") or "").strip(),
            content,
        ]
    )


def check_rate_limit(target_state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    limits = config.get("rate_limits", {}) or {}
    min_seconds = int(limits.get("min_seconds_between_replies", 0))
    max_per_10_minutes = int(limits.get("max_replies_per_10_minutes", 20))
    max_per_hour = int(limits.get("max_replies_per_hour", 100))
    now = datetime.now()
    timestamps = [
        parsed
        for parsed in (parse_datetime(item) for item in target_state.get("reply_timestamps", []))
        if parsed is not None
    ]
    blocks = []
    if timestamps and min_seconds > 0 and (now - max(timestamps)).total_seconds() < min_seconds:
        retry_after_at = max(timestamps) + timedelta(seconds=min_seconds)
        blocks.append(rate_limit_blocked("min_seconds_between_replies", now, retry_after_at))
    for reason, window_seconds, max_count in [
        ("max_replies_per_10_minutes", 10 * 60, max_per_10_minutes),
        ("max_replies_per_hour", 60 * 60, max_per_hour),
    ]:
        block = check_window_rate_limit(timestamps, now, reason, window_seconds, max_count)
        if block:
            blocks.append(block)
    if blocks:
        return max(blocks, key=lambda item: parse_datetime(str(item.get("retry_after_at") or "")) or now)
    return {"allowed": True, "reason": "ok"}


def check_window_rate_limit(
    timestamps: list[datetime],
    now: datetime,
    reason: str,
    window_seconds: int,
    max_count: int,
) -> dict[str, Any] | None:
    if max_count <= 0:
        return None
    window = timedelta(seconds=window_seconds)
    recent = sorted(item for item in timestamps if now - item <= window)
    if len(recent) < max_count:
        return None
    release_index = max(0, len(recent) - max_count)
    retry_after_at = recent[release_index] + window + timedelta(seconds=1)
    return rate_limit_blocked(reason, now, retry_after_at, window_seconds=window_seconds, max_count=max_count)


def rate_limit_blocked(
    reason: str,
    now: datetime,
    retry_after_at: datetime,
    window_seconds: int | None = None,
    max_count: int | None = None,
) -> dict[str, Any]:
    retry_after_seconds = max(1, int((retry_after_at - now).total_seconds()))
    payload = {
        "allowed": False,
        "reason": reason,
        "retry_after_at": retry_after_at.isoformat(timespec="seconds"),
        "retry_after_seconds": retry_after_seconds,
    }
    if window_seconds is not None:
        payload["window_seconds"] = window_seconds
    if max_count is not None:
        payload["max_count"] = max_count
    return payload


def get_rate_limit_backoff(target_state: dict[str, Any], message_ids: list[str]) -> dict[str, Any] | None:
    backoff = target_state.get("rate_limit_backoff")
    if not isinstance(backoff, dict):
        return None
    retry_after_at = parse_datetime(str(backoff.get("retry_after_at") or ""))
    if retry_after_at is None:
        return None
    if datetime.now() >= retry_after_at:
        target_state.pop("rate_limit_backoff", None)
        return None
    backoff["observed_message_ids"] = unique_list(
        [*[str(item) for item in backoff.get("observed_message_ids", [])], *message_ids]
    )
    return backoff


def record_rate_limit_backoff(
    target_state: dict[str, Any],
    message_ids: list[str],
    rate_check: dict[str, Any],
) -> None:
    existing = target_state.get("rate_limit_backoff")
    attempts = int(existing.get("attempts", 0)) + 1 if isinstance(existing, dict) else 1
    target_state["rate_limit_backoff"] = {
        "message_ids": message_ids,
        "observed_message_ids": message_ids,
        "reason": rate_check.get("reason"),
        "retry_after_at": rate_check.get("retry_after_at"),
        "retry_after_seconds": rate_check.get("retry_after_seconds"),
        "attempts": attempts,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def clear_rate_limit_backoff(target_state: dict[str, Any], message_ids: list[str]) -> None:
    backoff = target_state.get("rate_limit_backoff")
    if not isinstance(backoff, dict):
        return
    target_state.pop("rate_limit_backoff", None)


def should_send_rate_limit_notice(
    target_state: dict[str, Any],
    config: dict[str, Any],
    rate_check: dict[str, Any],
) -> bool:
    settings = config.get("rate_limits", {}) or {}
    if not settings.get("notice_customer", True):
        return False
    retry_after_at = str(rate_check.get("retry_after_at") or "")
    if not retry_after_at:
        return False
    notices = target_state.get("rate_limit_notices", []) or []
    if not notices:
        return True
    latest = notices[-1]
    if latest.get("retry_after_at") == retry_after_at:
        return False
    min_interval = int(settings.get("notice_min_interval_seconds", 300))
    latest_at = parse_datetime(str(latest.get("sent_at") or ""))
    if latest_at and (datetime.now() - latest_at).total_seconds() < min_interval:
        return False
    return True


def build_rate_limit_notice_text(config: dict[str, Any], rate_check: dict[str, Any]) -> str:
    settings = config.get("rate_limits", {}) or {}
    retry_after_seconds = int(rate_check.get("retry_after_seconds") or 60)
    retry_after_minutes = max(1, int((retry_after_seconds + 59) / 60))
    reason_label = {
        "min_seconds_between_replies": "回复过快",
        "max_replies_per_10_minutes": "10分钟回复额度",
        "max_replies_per_hour": "1小时回复额度",
    }.get(str(rate_check.get("reason") or ""), "回复额度")
    template = str(
        settings.get("notice_reply")
        or "当前消息较多，已达到{reason_label}上限，请稍等约 {retry_after_minutes} 分钟，我会继续处理您的消息。"
    )
    return template.format(
        reason_label=reason_label,
        retry_after_minutes=retry_after_minutes,
        retry_after_at=rate_check.get("retry_after_at") or "",
    )


def record_rate_limit_notice(
    target_state: dict[str, Any],
    message_ids: list[str],
    rate_check: dict[str, Any],
    notice_text: str,
) -> None:
    notices = list(target_state.get("rate_limit_notices", []) or [])
    notices.append(
        {
            "message_ids": message_ids,
            "reason": rate_check.get("reason"),
            "retry_after_at": rate_check.get("retry_after_at"),
            "notice_text": notice_text,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    target_state["rate_limit_notices"] = notices[-MAX_STORED_IDS:]


def record_reply_timestamp(target_state: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    timestamps = list(target_state.get("reply_timestamps", []))
    timestamps.append(now)
    target_state["reply_timestamps"] = timestamps[-MAX_STORED_IDS:]


def build_reply_trace_id(target_name: str, batch: list[dict[str, Any]], reply_text: str) -> str:
    message_ids = [str(item.get("id") or "") for item in batch if str(item.get("id") or "")]
    seed = json.dumps(
        {
            "target": target_name,
            "message_ids": message_ids,
            "reply_text": str(reply_text or ""),
            "question": [str(item.get("content") or "") for item in batch],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "reply_trace_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def mark_processed(
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    reply_text: str,
    *,
    reply_trace_id: str = "",
    send_result: dict[str, Any] | None = None,
) -> None:
    processed = list(target_state.get("processed_message_ids", []))
    for message in batch:
        message_id = str(message.get("id") or "")
        if message_id and message_id not in processed:
            processed.append(message_id)
    target_state["processed_message_ids"] = processed[-MAX_STORED_IDS:]
    entry = {
        "reply_trace_id": reply_trace_id or build_reply_trace_id("", batch, reply_text),
        "message_ids": [item.get("id") for item in batch],
        "message_contents": [item.get("content") for item in batch],
        "reply_text": reply_text,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }
    if send_result:
        entry["send_verified"] = bool(send_result.get("verified"))
    target_state.setdefault("sent_replies", []).append(entry)


def mark_coalesced_messages(
    target_state: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    reply_trace_id: str = "",
    reply_text: str = "",
    reason: str = "overflow_coalesced",
) -> None:
    if not messages:
        return
    processed = list(target_state.get("processed_message_ids", []))
    message_ids: list[str] = []
    for message in messages:
        message_id = str(message.get("id") or "")
        if not message_id:
            continue
        message_ids.append(message_id)
        if message_id not in processed:
            processed.append(message_id)
    if not message_ids:
        return
    target_state["processed_message_ids"] = processed[-MAX_STORED_IDS:]
    target_state.setdefault("coalesced_message_batches", []).append(
        {
            "reply_trace_id": reply_trace_id,
            "message_ids": message_ids,
            "message_contents": [item.get("content") for item in messages],
            "reply_text": reply_text,
            "reason": reason,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    target_state["coalesced_message_batches"] = target_state["coalesced_message_batches"][-MAX_STORED_IDS:]


def mark_handoff(
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    reason: str,
    status: str = "open",
    operator_alert: dict[str, Any] | None = None,
    reply_trace_id: str = "",
    reply_text: str = "",
) -> None:
    handoff = list(target_state.get("handoff_message_ids", []))
    for message in batch:
        message_id = str(message.get("id") or "")
        if message_id and message_id not in handoff:
            handoff.append(message_id)
    target_state["handoff_message_ids"] = handoff[-MAX_STORED_IDS:]
    event = {
        "reply_trace_id": reply_trace_id or build_reply_trace_id("", batch, reply_text),
        "message_ids": [item.get("id") for item in batch],
        "message_contents": [item.get("content") for item in batch],
        "reply_text": reply_text,
        "reason": reason,
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if operator_alert:
        event["operator_alert"] = operator_alert
    target_state.setdefault("handoff_events", []).append(event)


def base_event(target: TargetConfig, action: str, extra: dict[str, Any]) -> dict[str, Any]:
    event = {
        "ok": action != "error",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": target.name,
        "action": action,
    }
    event.update(extra)
    return event


LEADING_CUSTOMER_GREETING_RE = re.compile(
    r"^\s*((?:[\u4e00-\u9fff]{1,2}(?:先生您好|女士您好|哥|姐|先生|女士))|哥|姐|老板|老师|您好|你好|亲|Hi|Hello)[，,]\s*(.*)$",
    re.I | re.S,
)
RECENT_CUSTOMER_GREETING_RE = re.compile(
    r"(?:^|[\s。！？!?，,])(?:[\u4e00-\u9fff]{0,2}(?:先生您好|女士您好|哥|姐|先生|女士)|哥|姐|老板|老师|您好|你好)[，,]"
)
NEW_TOPIC_GREETING_TERMS = (
    "另外",
    "还有",
    "再问",
    "再咨询",
    "换个",
    "换一台",
    "顺便",
    "那贷款",
    "那保险",
    "那过户",
    "合同",
    "发票",
    "置换",
    "试驾",
    "到店",
)
FOLLOWUP_LIKE_GREETING_OPENERS = (
    "那",
    "如果",
    "这",
    "这个",
    "这台",
    "刚才",
    "还有",
    "我还有",
    "最后",
    "行",
    "你先",
    "你别",
    "要是",
)
INITIAL_GREETING_LEAD_TERMS = (
    "你好",
    "您好",
    "在吗",
    "有人吗",
    "我想",
    "想买",
    "买台",
    "买辆",
    "帮我看",
    "推荐",
    "预算",
    "家用",
    "通勤",
    "练手",
)
NON_PERSON_DISPLAY_NAME_TERMS = (
    FILE_TRANSFER_ASSISTANT,
    "文件传输",
    "助手",
    "客服",
    "机器人",
    "测试",
    "群",
    "车行",
    "二手车",
    "汽车",
    "公司",
    "门店",
    "销售",
    "顾问",
)
COMMON_COMPOUND_SURNAMES = (
    "欧阳",
    "上官",
    "司马",
    "诸葛",
    "东方",
    "南宫",
    "夏侯",
    "皇甫",
    "尉迟",
    "公孙",
    "慕容",
    "司徒",
    "令狐",
)


def _apply_greeting(
    reply_text: str,
    profile: dict[str, Any] | None,
    config: dict[str, Any],
    *,
    target_state: dict[str, Any] | None = None,
    combined: str = "",
    recent_reply_texts: list[str] | None = None,
) -> str:
    """Apply human-like customer honorifics only when the dialogue stage needs one."""
    text = str(reply_text or "").strip()
    if not text or not profile:
        return reply_text
    cfg = config.get("customer_profiles") or {}
    greeting_cfg = cfg.get("greeting") if isinstance(cfg, dict) else {}
    if not greeting_cfg or not greeting_cfg.get("enabled", True):
        return reply_text

    recent = list(recent_reply_texts or recent_customer_visible_reply_texts(target_state or {}))
    existing_greeting, body = _split_leading_customer_greeting(text)
    body = body.strip() if body else text
    should_use = _should_use_contextual_greeting(
        reply_text=body,
        combined=combined,
        recent_reply_texts=recent,
    )

    if existing_greeting and not should_use:
        return body

    if not should_use:
        return text

    selected = _select_contextual_honorific(
        profile=profile,
        combined=combined,
        reply_text=body,
        recent_reply_texts=recent,
    )
    if not selected:
        return text
    if existing_greeting:
        return f"{selected}，{body}"
    return f"{selected}，{text}"


def _split_leading_customer_greeting(text: str) -> tuple[str, str]:
    match = LEADING_CUSTOMER_GREETING_RE.match(str(text or "").strip())
    if not match:
        return "", str(text or "").strip()
    return str(match.group(1) or "").strip(), str(match.group(2) or "").strip()


def _should_use_contextual_greeting(
    *,
    reply_text: str,
    combined: str,
    recent_reply_texts: list[str],
) -> bool:
    if not recent_reply_texts:
        return _looks_like_initial_greeting_context(combined)
    if _recent_has_customer_greeting(recent_reply_texts, limit=4):
        return False
    if not _looks_like_new_topic(combined):
        return False
    seed = f"{combined}|{reply_text}|contextual-greeting"
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:2], 16) % 3 == 0


def _recent_has_customer_greeting(recent_reply_texts: list[str], *, limit: int = 4) -> bool:
    recent = " ".join(str(item or "") for item in recent_reply_texts[-max(1, limit) :])
    return bool(RECENT_CUSTOMER_GREETING_RE.search(recent))


def _looks_like_new_topic(text: str) -> bool:
    clean = re.sub(r"\s+", "", str(text or ""))
    return any(term in clean for term in NEW_TOPIC_GREETING_TERMS)


def _looks_like_initial_greeting_context(text: str) -> bool:
    clean = re.sub(r"\s+", "", str(text or ""))
    if not clean:
        return False
    if any(clean.startswith(term) for term in FOLLOWUP_LIKE_GREETING_OPENERS):
        return False
    return any(term in clean for term in INITIAL_GREETING_LEAD_TERMS)


def _select_contextual_honorific(
    *,
    profile: dict[str, Any],
    combined: str,
    reply_text: str,
    recent_reply_texts: list[str],
) -> str:
    basic = profile.get("basic_info") if isinstance(profile.get("basic_info"), dict) else {}
    gender = str(basic.get("gender") or "").strip().lower()
    try:
        confidence = float(basic.get("gender_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    surname = _safe_customer_surname(profile)

    candidates: list[str] = []
    if confidence >= 0.7 and gender == "male":
        if surname:
            candidates.append(f"{surname}哥")
        candidates.extend(["哥", "老板"])
    elif confidence >= 0.7 and gender == "female":
        if surname:
            candidates.append(f"{surname}姐")
        candidates.append("姐")
    elif confidence >= 0.5:
        candidates.append("您好")

    deduped = list(dict.fromkeys(item for item in candidates if item))
    if not deduped:
        return ""
    selected, _ = choose_reply_variant(
        deduped,
        key_text=f"{combined}|{reply_text}|honorific",
        recent_reply_texts=recent_reply_texts,
    )
    return selected


def _safe_customer_surname(profile: dict[str, Any]) -> str:
    display_name = str(profile.get("display_name") or profile.get("target_name") or "").strip()
    if not display_name:
        return ""
    if any(term and term in display_name for term in NON_PERSON_DISPLAY_NAME_TERMS):
        return ""
    name = re.sub(r"[\s_@#\-—~·.。]+", "", display_name)
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", name):
        return ""
    for surname in COMMON_COMPOUND_SURNAMES:
        if name.startswith(surname):
            return surname
    return name[0]


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "targets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_audit(path: Path, event: dict[str, Any]) -> None:
    append_jsonl(path, event)


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def default_max_batch_messages(config: dict[str, Any] | None = None) -> int:
    cfg = config if isinstance(config, dict) else {}
    batching = cfg.get("batching", {}) if isinstance(cfg.get("batching"), dict) else {}
    multi_target = cfg.get("multi_target", {}) if isinstance(cfg.get("multi_target"), dict) else {}
    for value in (
        batching.get("max_batch_messages"),
        multi_target.get("default_max_batch_messages"),
        DEFAULT_MAX_BATCH_MESSAGES,
    ):
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return DEFAULT_MAX_BATCH_MESSAGES


def parse_targets(config: dict[str, Any], *, allow_empty: bool = False) -> list[TargetConfig]:
    targets = []
    default_batch = default_max_batch_messages(config)
    for item in config.get("targets", []) or []:
        if not item.get("enabled", False):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        allow_self = bool(item.get("allow_self_for_test", False))
        if allow_self and name != FILE_TRANSFER_ASSISTANT:
            raise ValueError("allow_self_for_test is only allowed for File Transfer Assistant")
        targets.append(
            TargetConfig(
                name=name,
                enabled=True,
                exact=bool(item.get("exact", True)),
                allow_self_for_test=allow_self,
                max_batch_messages=int(item.get("max_batch_messages", default_batch) or default_batch),
            )
        )
    if not targets and not allow_empty:
        raise ValueError("No enabled targets in config")
    return targets


def parse_runtime_targets(values: list[str], config_targets: list[TargetConfig]) -> list[TargetConfig]:
    config_by_name = {target.name: target for target in config_targets}
    targets = []
    for value in values:
        name = str(value or "").strip()
        if not name:
            continue
        if name in config_by_name:
            targets.append(config_by_name[name])
            continue
        targets.append(
            TargetConfig(
                name=name,
                enabled=True,
                exact=True,
                allow_self_for_test=False,
                max_batch_messages=DEFAULT_MAX_BATCH_MESSAGES,
            )
        )
    if not targets:
        raise ValueError("No runtime targets were provided")
    return targets


def build_iteration_targets(
    *,
    config_targets: list[TargetConfig],
    active_targets: list[Any],
    multi_target_cfg: dict[str, Any] | None,
    allow_dynamic_active_targets: bool = False,
    blocked_names: set[str] | None = None,
) -> list[TargetConfig]:
    """Build per-iteration target list: active sessions first, then full whitelist scan."""
    cfg = multi_target_cfg or {}
    prioritize_active = cfg.get("prioritize_active_sessions", True) is not False
    # By default we scan all configured targets each iteration so no whitelist target is missed.
    scan_all = cfg.get("scan_all_whitelist_each_iteration", True) is not False
    try:
        active_limit = int(cfg.get("max_targets_per_iteration", 5) or 5)
    except (TypeError, ValueError):
        active_limit = 5
    try:
        scan_limit = int(cfg.get("max_scan_targets_per_iteration", 0) or 0)
    except (TypeError, ValueError):
        scan_limit = 0
    try:
        dynamic_max_batch = int(
            cfg.get("dynamic_max_batch_messages")
            or cfg.get("default_max_batch_messages")
            or DEFAULT_MAX_BATCH_MESSAGES
        )
    except (TypeError, ValueError):
        dynamic_max_batch = DEFAULT_MAX_BATCH_MESSAGES

    config_by_name = {target.name: target for target in config_targets}
    ordered: list[TargetConfig] = []
    seen: set[str] = set()
    blocked = blocked_names or set()

    def push(target: TargetConfig) -> None:
        if target.name in blocked:
            return
        if target.name in seen:
            return
        seen.add(target.name)
        ordered.append(target)

    active_candidates = list(active_targets or [])
    if active_limit > 0:
        active_candidates = active_candidates[:active_limit]

    if prioritize_active:
        for item in active_candidates:
            name = str(getattr(item, "name", "") or "")
            base = config_by_name.get(name)
            if base is not None:
                push(base)
                continue
            if allow_dynamic_active_targets and name and name not in blocked:
                push(
                    TargetConfig(
                        name=name,
                        enabled=True,
                        exact=True,
                        allow_self_for_test=False,
                        max_batch_messages=max(1, dynamic_max_batch),
                    )
                )

    if scan_all:
        for base in config_targets:
            push(base)
    elif not prioritize_active:
        for item in active_candidates:
            name = str(getattr(item, "name", "") or "")
            base = config_by_name.get(name)
            if base is not None:
                push(base)
                continue
            if allow_dynamic_active_targets and name and name not in blocked:
                push(
                    TargetConfig(
                        name=name,
                        enabled=True,
                        exact=True,
                        allow_self_for_test=False,
                        max_batch_messages=max(1, dynamic_max_batch),
                    )
                )

    if not ordered:
        for base in config_targets:
            push(base)

    if scan_limit > 0:
        return ordered[:scan_limit]
    return ordered


def resolve_iterations(args: argparse.Namespace, config: dict[str, Any]) -> int:
    if args.once:
        return 1
    if args.iterations is not None:
        return max(1, args.iterations)
    return max(1, int(config.get("poll", {}).get("iterations", 1)))


def resolve_path(value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return ROOT / path


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
