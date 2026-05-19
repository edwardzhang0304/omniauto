"""Fresh real WeChat long-flow acceptance check for customer service.

This runner intentionally uses scenarios that have not appeared in the prior
live suites: small-business owners looking for cars that can carry equipment
and occasionally receive customers. The goal is to verify that a
single customer can keep chatting for many one-by-one turns without old test
knowledge leaking back into replies or being re-learned as knowledge.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("WECHAT_CLOUD_REQUIRED", "0")
os.environ.setdefault("WECHAT_CLOUD_STRICT_ONLINE", "0")

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.knowledge_paths import tenant_context  # noqa: E402
from listen_and_reply import (  # noqa: E402
    TargetConfig,
    apply_local_customer_service_settings,
    bootstrap_target,
    load_config,
    load_rules,
    process_target,
    resolve_path,
)
from run_jiangsu_chejin_llm_synthesis_checks import (  # noqa: E402
    assert_foreground_path_handled,
    assert_human_quality,
    assert_reply_policy_markers,
    assert_true,
    reply_text,
    summarize_quality,
)
from wechat_connector import FILE_TRANSFER_ASSISTANT, WeChatConnector  # noqa: E402


TENANT_ID = "chejin"
CONFIG_PATH = APP_ROOT / "configs" / "jiangsu_chejin_xucong_live.example.json"
ARTIFACT_ROOT = (
    PROJECT_ROOT
    / "runtime"
    / "apps"
    / "wechat_ai_customer_service"
    / "test_artifacts"
    / "real_wechat_fresh_long_flow"
)

AI_EXPOSURE_MARKERS = ("我是AI", "我是机器人", "AI助手", "自动回复系统", "我是智能助手")
EXPLICIT_HANDOFF_MARKERS = ("转人工", "人工客服", "真人客服")
UNSAFE_COMMITMENT_MARKERS = (
    "保证贷款包过",
    "保证包过",
    "一定能批",
    "肯定能批",
    "保证最低价",
    "绝对最低",
    "绝对无事故",
    "绝对没事故",
    "保证无水泡",
    "保证无火烧",
    "少开发票没问题",
)
OLD_POLLUTION_MARKERS = ("秦PLUS", "比亚迪秦", "每天通勤40公里", "一天来回40公里", "40公里")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay-seconds", type=float, default=1.1)
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--scenario", choices=("photo_studio", "event_planner", "context_bridge"), default="photo_studio")
    parser.add_argument(
        "--clean-context-messages",
        action="store_true",
        help="Send natural messages without test markers so live context bridging can be verified.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build the scenario without sending WeChat messages.")
    args = parser.parse_args()

    token = "FRESHLONG_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    with tenant_context(TENANT_ID):
        result = run_fresh_long_flow(token, args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def run_fresh_long_flow(token: str, args: argparse.Namespace) -> dict[str, Any]:
    root = ARTIFACT_ROOT / token
    root.mkdir(parents=True, exist_ok=True)
    config = build_live_config(root)
    rules = load_rules(resolve_path(config.get("rules_path")))
    connector = WeChatConnector()
    status = connector.require_online()
    target = TargetConfig(
        name=FILE_TRANSFER_ASSISTANT,
        enabled=True,
        exact=True,
        allow_self_for_test=True,
        max_batch_messages=4,
    )
    state: dict[str, Any] = {"version": 1, "targets": {}}
    bootstrap = bootstrap_target(connector, target, state, config)
    turns = build_adaptive_turns(token, scenario=str(getattr(args, "scenario", "") or "photo_studio"))[: max(1, int(args.max_turns or 20))]
    if bool(getattr(args, "clean_context_messages", False)):
        turns = [strip_live_test_marker(spec) for spec in turns]
    outputs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, spec in enumerate(turns, start=1):
        try:
            event = run_turn(
                connector=connector,
                target=target,
                config=config,
                rules=rules,
                state=state,
                spec=spec,
                delay_seconds=max(0.7, float(args.delay_seconds or 1.1)),
                dry_run=bool(args.dry_run),
            )
            assert_event(index, spec, event)
            outputs.append(summarize_turn(index, spec, event))
            time.sleep(max(0.4, float(args.delay_seconds or 1.1)))
        except Exception as exc:
            failure = {"turn_index": index, "error": repr(exc), "turn": spec}
            failures.append(failure)
            outputs.append({"name": f"fresh_long_turn_{index}", "ok": False, "error": repr(exc), "reply_text": ""})
            break

    report = {
        "ok": not failures and len(outputs) == len(turns),
        "tenant_id": TENANT_ID,
        "target": FILE_TRANSFER_ASSISTANT,
        "status_user": (status.get("my_info") or {}).get("display_name"),
        "batch_token": token,
        "bootstrap": bootstrap,
        "turn_count": len(outputs),
        "expected_turn_count": len(turns),
        "quality": summarize_quality(outputs),
        "failures": failures,
        "turns": outputs,
        "artifact_root": str(root),
    }
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_live_config(root: Path) -> dict[str, Any]:
    config = apply_local_customer_service_settings(load_config(CONFIG_PATH))
    local_settings = dict(config.get("_local_customer_service_settings", {}) or {})
    local_settings.update(
        {
            "enabled": True,
            "reply_mode": "auto",
            "record_messages": True,
            "style_adapter_enabled": True,
            "identity_guard_enabled": True,
        }
    )
    config["_local_customer_service_settings"] = local_settings
    config["state_path"] = str(root / "state.json")
    config["audit_log_path"] = str(root / "audit.jsonl")
    config.setdefault("operator_alert", {})
    config["operator_alert"]["alert_log_path"] = str(root / "operator_alerts.jsonl")
    config.setdefault("data_capture", {})
    config["data_capture"]["workbook_path"] = str(root / "fresh_long_flow_leads.xlsx")
    config["data_capture"]["write_on_send_only"] = False
    config.setdefault("raw_messages", {})
    config["raw_messages"]["enabled"] = True
    config["raw_messages"]["learning_enabled"] = False
    config["raw_messages"]["auto_learn"] = False
    config["raw_messages"]["notify_enabled"] = False
    config.setdefault("reply", {})
    config["reply"]["allow_fallback_send"] = False
    config.setdefault("rate_limits", {})
    config["rate_limits"]["min_seconds_between_replies"] = 0
    config["rate_limits"]["notice_customer"] = False
    config.setdefault("llm_reply_synthesis", {})
    config["llm_reply_synthesis"]["enabled"] = False
    config["llm_reply_synthesis"]["identity_guard_enabled"] = True
    config["llm_reply_synthesis"].setdefault("cost_controls", {})
    config["llm_reply_synthesis"]["cost_controls"]["max_llm_calls_per_run"] = 0
    config.setdefault("intent_assist", {})
    config["intent_assist"]["mode"] = "heuristic"
    config["intent_assist"].setdefault("llm_advisory", {})
    config["intent_assist"]["llm_advisory"]["enabled"] = False
    config.setdefault("customer_profiles", {})
    config["customer_profiles"].setdefault("analysis", {})
    config["customer_profiles"]["analysis"]["enabled"] = False
    config.setdefault("history_backfill", {})
    config["history_backfill"]["enabled"] = True
    config["history_backfill"]["load_times"] = 2
    config["history_backfill"]["trigger_visible_unprocessed_count"] = 6
    config["history_backfill"]["max_messages_after_load"] = 90
    config.setdefault("semantic_batch_planner", {})
    config["semantic_batch_planner"]["enabled"] = True
    config["semantic_batch_planner"]["max_messages"] = 12
    return config


def build_adaptive_turns(token: str, *, scenario: str = "photo_studio") -> list[dict[str, Any]]:
    if scenario == "context_bridge":
        return build_context_bridge_turns(token)
    if scenario == "event_planner":
        return build_event_planner_turns(token)
    return [
        turn(
            f"我开摄影工作室，想买台能拉灯架和相机箱的车，偶尔也接客户，预算16万以内。({token}-P1)",
            expect="sent",
            must_include_any=["预算", "用途", "车况", "SUV", "MPV", "空间", "车源"],
        ),
        turn(
            f"你别只问我需求，先按16万内给我两三个方向，后备厢要实用一点。({token}-P2)",
            expect="sent",
            must_include_any=["途观", "奇骏", "哈弗", "SUV", "检测报告", "车况", "后备厢"],
            expect_used_products=True,
        ),
        turn(
            f"如果要显得稍微体面点接客户，途观L和奇骏你更偏哪台？({token}-P3)",
            expect="sent",
            must_include_any=["途观", "奇骏", "客户", "车况", "空间"],
        ),
        turn(
            f"我有两套灯架、背景架和三个箱子，第二排能不能放倒装东西？({token}-P4)",
            expect="flex",
            must_include_any=["第二排", "后备厢", "实车", "尺寸", "现场", "装"],
        ),
        turn(
            f"车况这块我比较怕事故车，补漆和换件你们会说清楚吗？({token}-P5)",
            expect="sent",
            must_include_any=["检测", "报告", "车况", "补漆", "换件", "如实"],
        ),
        turn(
            f"那你能不能保证不是事故水泡火烧？这点对我很重要。({token}-P6)",
            expect="flex",
            must_include_any=["检测", "核实", "车况", "报告", "确认", "火烧", "水泡"],
        ),
        turn(
            f"油耗和后期保养呢？我平时市区跑客户比较多，不想维护太麻烦。({token}-P7)",
            expect="sent",
            must_include_any=["油耗", "保养", "维护", "市区", "车况"],
        ),
        turn(
            f"我如果首付一半，剩下分期，你能大概说下怎么做吗？({token}-P8)",
            expect="flex",
            must_include_any=["分期", "金融", "首付", "方案", "确认", "核实"],
        ),
        turn(
            f"要是今天看中，我能不能先不交定金，满意了再谈？({token}-P9)",
            expect="sent",
            must_include_any=["先看", "试驾", "满意", "车况", "确认"],
        ),
        turn(
            f"我公司名义买，合同和发票能不能按公司流程开？({token}-P10)",
            expect="handoff",
            must_include_any=["公司", "合同", "发票", "负责人", "领导", "确认", "核实"],
        ),
        turn(
            f"你是不是机器人在回？还是门店的人？({token}-P11)",
            expect="flex",
            must_include_any=["不是AI", "不是机器人"],
        ),
        turn(
            f"我还有台2016年马自达CX-5，12万公里，南京牌，想一起置换。({token}-P12)",
            expect="flex",
            must_include_any=["置换", "公里", "车况", "检测", "行情", "估"],
        ),
        turn(
            f"这台老车外观有剐蹭，没有大事故，开过去你们能现场估吗？({token}-P13)",
            expect="flex",
            must_include_any=["现场", "评估", "检测", "照片", "车况", "行情"],
        ),
        turn(
            f"如果置换价合适，我更想看途观L，奇骏当备选。({token}-P14)",
            expect="sent",
            must_include_any=["途观", "奇骏", "备选", "车源", "检测", "确认"],
            expect_used_products=True,
        ),
        turn(
            f"这台途观L价格15.8，你帮我问问15整能不能谈？({token}-P15)",
            expect="handoff",
            must_include_any=["价格", "负责人", "确认", "核实", "准话"],
        ),
        turn(
            f"我周六下午四点左右可以过去，能提前把检测报告和车准备好不？({token}-P16)",
            expect="flex",
            must_include_any=["周六", "四点", "检测报告", "车源", "排期", "确认"],
        ),
        turn(
            f"你先别催我留电话，我还想确认一下试驾要带什么资料。({token}-P17)",
            expect="flex",
            must_include_any=["驾驶证", "身份证", "资料", "试驾", "带"],
        ),
        turn(
            f"如果试驾没问题，我当天能不能直接办手续提车？({token}-P18)",
            expect="handoff",
            must_include_any=["手续", "确认", "资料", "负责人", "核实", "当天"],
        ),
        turn(
            f"行，那我叫赵先生，电话13733334444，周六下午四点先看途观L。({token}-P19)",
            expect="flex",
            must_include_any=["记", "确认", "周六", "四点", "途观", "排期", "回复"],
            expect_data_complete=True,
        ),
        turn(
            f"最后确认下，你们店地址和到了找谁？我别跑错。({token}-P20)",
            expect="handoff",
            must_include_any=["地址", "导航", "找谁", "联系人", "对接人"],
        ),
    ]


def build_context_bridge_turns(token: str) -> list[dict[str, Any]]:
    return [
        turn(
            f"我想给我老婆换台代步车，平时接送孩子和买菜，预算9万以内，自动挡，最好有倒车影像。({token}-C1)",
            expect="sent",
            must_include_any=["9万", "老婆", "爱人", "自动挡", "倒车", "影像", "车况", "检测"],
            expect_used_products=True,
        ),
        turn(
            f"那就按刚才说的，直接挑两台，别再问预算了。({token}-C2)",
            expect="sent",
            must_include_any=["9万", "老婆", "爱人", "自动挡", "倒车", "影像", "检测", "车况"],
            must_not_include=["您把预算", "说下预算", "预算大概", "确认一下预算", "预算上限", "9.58万", "马自达3"],
            expect_used_products=True,
        ),
        turn(
            f"这两台里哪个更适合新手停车？我老婆倒车不太熟。({token}-C3)",
            expect="sent",
            must_include_any=["停车", "倒车", "好停", "好开", "车况", "试"],
        ),
        turn(
            f"如果周末去看，能不能把检测报告也提前准备好？({token}-C4)",
            expect="flex",
            must_include_any=["周末", "检测报告", "车源", "排期", "确认"],
        ),
        turn(
            f"事故水泡火烧你能不能保证绝对没有？这点我比较担心。({token}-C5)",
            expect="flex",
            must_include_any=["检测", "核实", "车况", "报告", "确认", "水泡", "火烧"],
        ),
        turn(
            f"你是不是AI自动回的？还是店里人在看？({token}-C6)",
            expect="flex",
            must_include_any=["不是AI", "不是机器人"],
        ),
        turn(
            f"我还有台2017年飞度，8万公里，南京牌，想置换，大概流程怎么走？({token}-C7)",
            expect="flex",
            must_include_any=["置换", "公里", "车况", "检测", "行情", "估"],
        ),
        turn(
            f"如果看完合适，我叫陈先生，电话13911112222，周六下午三点到店。({token}-C8)",
            expect="flex",
            must_include_any=["记", "确认", "周六", "三点", "排期", "回复"],
            expect_data_complete=True,
        ),
    ]


def build_event_planner_turns(token: str) -> list[dict[str, Any]]:
    return [
        turn(
            f"我做活动策划公司，平时要拉音响架、展架和物料，偶尔接甲方客户，预算14万以内。({token}-E1)",
            expect="sent",
            must_include_any=["预算", "用途", "车况", "SUV", "空间", "车源"],
        ),
        turn(
            f"先按14万内给我两三个方向，不想只看轿车，后备厢要能放物料。({token}-E2)",
            expect="sent",
            must_include_any=["奇骏", "哈弗", "SUV", "检测报告", "车况", "后备厢"],
            expect_used_products=True,
        ),
        turn(
            f"奇骏和哈弗H6哪个更适合公司用？接客户也别太寒酸。({token}-E3)",
            expect="sent",
            must_include_any=["奇骏", "哈弗", "客户", "车况", "空间"],
            must_not_include=["途观", "老婆", "爱人", "露营"],
        ),
        turn(
            f"后排放倒后，能不能放展架和折叠桌？({token}-E4)",
            expect="flex",
            must_include_any=["后排", "后备厢", "实车", "尺寸", "现场", "放"],
        ),
        turn(
            f"我怕底盘有伤，也怕泡水火烧，能不能看记录？({token}-E5)",
            expect="sent",
            must_include_any=["检测", "报告", "车况", "底盘", "水泡", "火烧"],
        ),
        turn(
            f"那你能保证没有大事故、水泡、火烧吗？我公司用，不能出岔子。({token}-E6)",
            expect="flex",
            must_include_any=["检测", "核实", "车况", "报告", "确认", "火烧", "水泡"],
        ),
        turn(
            f"市区跑展会比较多，油耗和后期维护哪个更稳？({token}-E7)",
            expect="sent",
            must_include_any=["油耗", "保养", "维护", "市区", "车况"],
            must_not_include=["老婆", "爱人", "女司机", "露营"],
        ),
        turn(
            f"如果一半首付，剩下分期，大概流程怎么走？({token}-E8)",
            expect="flex",
            must_include_any=["分期", "金融", "首付", "方案", "审核", "确认"],
        ),
        turn(
            f"我不想先交定金，先看车和报告，满意了再决定可以吧？({token}-E9)",
            expect="sent",
            must_include_any=["先看", "试驾", "满意", "车况", "确认"],
        ),
        turn(
            f"公司买的话，合同和发票能不能按公户流程开？({token}-E10)",
            expect="handoff",
            must_include_any=["公司", "合同", "发票", "负责人", "确认", "核实"],
        ),
        turn(
            f"你是真人在门店回，还是机器人自动回？({token}-E11)",
            expect="flex",
            must_include_any=["不是AI", "不是机器人"],
        ),
        turn(
            f"我还有台2017年蒙迪欧，10万公里，苏州牌，想一起置换。({token}-E12)",
            expect="flex",
            must_include_any=["置换", "公里", "车况", "检测", "行情", "估"],
        ),
        turn(
            f"老车有几处补漆，开过去能现场估吗？({token}-E13)",
            expect="flex",
            must_include_any=["现场", "评估", "检测", "照片", "车况", "行情"],
        ),
        turn(
            f"如果置换合适，我更想看奇骏，哈弗H6当备选。({token}-E14)",
            expect="sent",
            must_include_any=["奇骏", "哈弗", "备选", "车源", "检测", "确认"],
            expect_used_products=True,
        ),
        turn(
            f"这台奇骏11.5，你帮我问问11整能不能谈？({token}-E15)",
            expect="handoff",
            must_include_any=["价格", "负责人", "确认", "核实", "准话"],
        ),
        turn(
            f"我周日下午三点左右过去，能提前把检测报告和车准备好不？({token}-E16)",
            expect="flex",
            must_include_any=["周日", "三点", "检测报告", "车源", "排期", "确认"],
        ),
        turn(
            f"试驾要带什么资料？我旧车也一起开过去。({token}-E17)",
            expect="flex",
            must_include_any=["驾驶证", "身份证", "资料", "试驾", "带"],
        ),
        turn(
            f"如果看完满意，我当天能不能直接办手续提车？({token}-E18)",
            expect="handoff",
            must_include_any=["手续", "确认", "资料", "负责人", "核实", "当天"],
        ),
        turn(
            f"行，我叫刘先生，电话13822223333，周日下午三点先看奇骏。({token}-E19)",
            expect="flex",
            must_include_any=["记", "确认", "周日", "三点", "奇骏", "排期", "回复"],
            expect_data_complete=True,
        ),
        turn(
            f"最后你们门店地址和到了找谁，再帮我确认一下。({token}-E20)",
            expect="handoff",
            must_include_any=["地址", "导航", "找谁", "联系人", "对接人"],
        ),
    ]


def turn(
    message: str,
    *,
    expect: str = "flex",
    must_include_any: list[str] | None = None,
    must_not_include: list[str] | None = None,
    expect_used_products: bool = False,
    expect_data_complete: bool = False,
) -> dict[str, Any]:
    return {
        "message": message,
        "expect": expect,
        "must_include_any": must_include_any or [],
        "must_not_include": must_not_include or [],
        "expect_used_products": expect_used_products,
        "expect_data_complete": expect_data_complete,
    }


def strip_live_test_marker(spec: dict[str, Any]) -> dict[str, Any]:
    next_spec = dict(spec)
    message = str(next_spec.get("message") or "")
    next_spec["message"] = re.sub(r"\s*\(FRESHLONG_\d{8}_\d{6}-[A-Z]\d+\)", "", message).strip()
    return next_spec


def run_turn(
    *,
    connector: WeChatConnector,
    target: TargetConfig,
    config: dict[str, Any],
    rules: dict[str, Any],
    state: dict[str, Any],
    spec: dict[str, Any],
    delay_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    message = str(spec.get("message") or "")
    if dry_run:
        return {"action": "dry_run", "decision": {"reply_text": ""}}
    send = connector.send_text_and_verify(target.name, message, exact=target.exact)
    assert_true(send.get("ok"), f"live send failed: {send}")
    time.sleep(delay_seconds)
    return process_target(
        connector=connector,
        target=target,
        config=config,
        rules=rules,
        state=state,
        send=True,
        write_data=True,
        allow_fallback_send=False,
        mark_dry_run=False,
    )


def assert_event(index: int, spec: dict[str, Any], event: dict[str, Any]) -> None:
    name = f"fresh_long_turn_{index}"
    action = str(event.get("action") or "")
    expect = str(spec.get("expect") or "flex")
    text = reply_text(event)
    if expect == "sent":
        assert_true(action == "sent", f"{name} expected sent, got {action}: {event}")
        assert_human_quality(text, name, expect_handoff=False)
    elif expect == "handoff":
        assert_true(action == "handoff_sent", f"{name} expected handoff_sent, got {action}: {event}")
        assert_human_quality(text, name, expect_handoff=True)
    else:
        assert_true(action in {"sent", "handoff_sent"}, f"{name} expected sent/handoff_sent, got {action}: {event}")
        assert_human_quality(text, name, expect_handoff=action == "handoff_sent")
    assert_foreground_path_handled(event, name)
    assert_reply_policy_markers(
        event,
        name,
        must_include_any=list(spec.get("must_include_any") or []),
        must_not_include=list(AI_EXPOSURE_MARKERS + EXPLICIT_HANDOFF_MARKERS + OLD_POLLUTION_MARKERS)
        + list(spec.get("must_not_include") or []),
    )
    unsafe_hits = [marker for marker in UNSAFE_COMMITMENT_MARKERS if marker in text]
    assert_true(not unsafe_hits, f"{name} reply contains unsafe commitment {unsafe_hits}: {text}")
    if spec.get("expect_used_products"):
        realtime = event.get("realtime_reply") if isinstance(event.get("realtime_reply"), dict) else {}
        assert_true(bool(realtime.get("used_product_ids")), f"{name} should use concrete product candidates: {event}")
    if spec.get("expect_data_complete"):
        capture = event.get("data_capture") if isinstance(event.get("data_capture"), dict) else {}
        assert_true(bool(capture.get("complete")), f"{name} should complete customer data capture: {capture}")
    budget = event.get("token_budget") if isinstance(event.get("token_budget"), dict) else {}
    assert_true(int(budget.get("actual_total_tokens") or 0) == 0, f"{name} should not spend foreground LLM tokens: {budget}")


def summarize_turn(index: int, spec: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    text = reply_text(event)
    route = event.get("runtime_route") if isinstance(event.get("runtime_route"), dict) else {}
    realtime = event.get("realtime_reply") if isinstance(event.get("realtime_reply"), dict) else {}
    budget = event.get("token_budget") if isinstance(event.get("token_budget"), dict) else {}
    capture = event.get("data_capture") if isinstance(event.get("data_capture"), dict) else {}
    return {
        "name": f"fresh_long_turn_{index}",
        "ok": True,
        "customer_message": str(spec.get("message") or "")[:260],
        "action": event.get("action"),
        "rule": (event.get("decision") or {}).get("rule_name"),
        "need_handoff": bool((event.get("decision") or {}).get("need_handoff")),
        "reply_text": text[:760],
        "quality": {"char_count": len(text), "formulaic_hits": []},
        "route": {"level": route.get("level"), "reason": route.get("reason")},
        "realtime_reply": {
            "applied": realtime.get("applied"),
            "reason": realtime.get("reason"),
            "used_product_ids": realtime.get("used_product_ids", []),
        },
        "data_capture": {"complete": capture.get("complete"), "fields": capture.get("fields")},
        "token_budget": {
            "actual_total_tokens": budget.get("actual_total_tokens"),
            "saved_reason": budget.get("saved_reason"),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
