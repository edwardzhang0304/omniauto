# RPA Low-Disturbance Listener Design

## Goal

Keep customer-service response fast while reducing unnecessary WeChat UI operations.

The guardrail is not "reply less"; it is "do not touch the WeChat UI unless a
real state change requires it".

## Current Mechanisms We Keep

- Long-running operator guard: the listener starts the keyboard/mouse guard for
  the whole listening session. F8 remains the pause/stop escape path.
- Current-chat fast path: `open_chat` already returns without clicking when the
  target chat title is visible.
- Anchor-based history backfill: history scrolling is only needed when the last
  processed/replied anchor cannot be found on the current screen.
- Session digest monitor: the session monitor already compares preview/time
  digests to detect changed conversations.
- RPA-first transport: wxauto4 remains disabled by default and only acts as a
  reserve when explicitly enabled.

## Changes In This Pass

- `sessions` polling becomes passive by default. It captures/OCRs the visible
  WeChat window without activation, window normalization, clicking, or scrolling.
- `messages` reading no longer scrolls to latest by default. It relies on the
  current screen first, and the existing anchor backfill mechanism scrolls only
  when necessary.
- Low-risk multi-target mode no longer performs idle whitelist sweeps. If the
  session list has no changed preview/unread signal, the loop does not enter
  chat pages.
- A short warmup window is added after session-list change detection so burst
  messages can settle before LLM processing.
- Sidecar responses include page fingerprints for audit/debugging.
- Active UI actions are audited and protected by a generous action budget to
  stop runaway activate/click/scroll loops without throttling normal replies.
- Interactive calibration is event-triggered instead of loop-triggered: once at
  startup, once after F8 resume, and after repeated passive-listener failures.
  Normal idle polling remains passive.

## Runtime Behavior

Idle loop:

1. Keep operator guard running.
2. Poll `sessions` passively every few seconds with jitter.
3. If session fingerprints are unchanged, skip all chat-page operations.
4. If passive probes repeatedly fail or return suspicious empty OCR, run one
   interactive calibration pass; if calibration still fails, stop and hand off.

Changed loop:

1. Wait a short randomized warmup.
2. Poll `sessions` passively again.
3. Process only changed targets.
4. Read current chat screen first.
5. Use anchor backfill only if the current screen cannot prove continuity.
6. Send with guarded `enter_only` trigger.

Startup/resume loop:

1. Start or resume the long-running operator guard first.
2. Run one interactive WeChat status calibration with window normalization.
3. Continue passive polling only if calibration confirms an online main window.

## Why This Should Reduce Risk

WeChat sees far fewer unnecessary focus, click, and wheel actions. The listener
can still be responsive because passive screenshot/OCR polling remains frequent.
