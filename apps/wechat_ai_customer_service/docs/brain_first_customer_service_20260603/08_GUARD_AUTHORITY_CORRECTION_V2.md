# Guard Authority Correction V2

## 客户可见回复所有权硬基线

- 所有客户可见回复必须由 `customer_service_brain` 发出：只能是首个有效 BrainPlan、Brain repair 后的 BrainPlan，或 Brain 自己生成的硬边界/拒绝/转人工类说明。
- Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和任何兜底模块都不能生成、替换、拼接客户可见回复；它们只能提供证据、风险、审稿意见、返修指令或轻量表达校验。
- Brain 不可用、超时、不可采纳或返修失败时，不允许本地 safe fallback 代替 Brain 发客户可见话术；必须阻断发送、记录审计，并触发内部人工/告警接口。
- 后续所有客服相关开发文档必须引用 [customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)。

## 1. Purpose

This document turns the Brain First correction principle into an executable runtime contract.

The problem exposed by manual testing is not that the Brain never runs. The Brain can understand the customer, find the right product evidence, and draft a useful answer, but downstream guard or quality paths can still replace the customer-visible reply with a generic handoff/stall answer. That means the visible answer is no longer owned by the Brain.

V2 fixes this at architecture level:

```text
Product master / formal knowledge / hard safety = constraints
Customer Service Brain = reply owner
Quality gate / semantic reviewer / guard / final polish = reviewers
```

Reviewers may reject, warn, or ask the Brain to repair. Reviewers must not become a second answer engine.

## 2. Failure Pattern From Manual Testing

Observed examples:

- The Brain matched an Audi product in product master, but the final reply became a generic "I will verify and get back to you" message.
- A customer asked whether the account was a real salesperson / where the company was, and the flow jumped to handoff instead of letting the Brain answer naturally within boundaries.
- Pure greetings and soft social turns were sometimes contaminated by old context or blocked by safety paths.

Root cause:

- `guard_synthesized_reply` still has multiple direct `handoff_decision(...)` exits.
- `handoff_decision(...)` can set `customer_visible_reply_source=guard_handoff_ack`.
- Brain orchestration treats `action=handoff` as adoptable and uses `guard.reply` when present.

Therefore previous tests that only checked `brain_adopted=true` were not sufficient. The correct acceptance signal is:

```text
visible reply owner is Brain / Brain repair / Brain-authored hard-boundary response,
not guard / quality gate / route template / final polish strategy rewrite / local fallback.
If Brain is unavailable or non-adoptable, there is no customer-visible reply.
```

## 3. Runtime Ownership Contract

### 3.1 Allowed Customer-Visible Owners

Normal customer-visible replies may only originate from:

- `brain`: the first valid BrainPlan.
- `brain_repair`: a repaired BrainPlan after reviewer feedback.
- `brain_hard_boundary_refusal`: a Brain-authored refusal or boundary answer for illegal/internal/high-risk requests.

When Brain or Brain repair is unavailable, invalid, or non-adoptable, the allowed visible owner is `none`: block outbound send, record audit, and trigger internal handoff/alert. Do not send local fallback text.

### 3.2 Forbidden Customer-Visible Owners

These layers must not author customer-visible replies:

- `guard_handoff_ack`
- `quality_gate_template`
- `semantic_reviewer_template`
- `final_polish_strategy_rewrite`
- legacy `realtime_reply_router` / local RAG route templates when Brain First is enabled

### 3.3 Reviewer Output Contract

Reviewer layers return verdicts:

| Verdict | Meaning | Customer-visible text allowed? |
| --- | --- | --- |
| `pass` | Safe to send | Yes, Brain text |
| `warn` | Safe to send with audit warning | Yes, Brain text |
| `repair` | Needs Brain repair | No |
| `block` | Unsafe to send | No |
| `handoff` | Must route to human | No reviewer-authored text |

For `repair`, the reviewer must provide:

- reason
- severity
- hard_boundary flag
- repair_instruction
- evidence/risk details

It must not provide a replacement reply.

## 4. Hard Boundary Whitelist

Only these classes may stop automatic reply without another Brain repair attempt:

- possible cross-session or wrong-target send
- explicit illegal request where Brain cannot produce a safe refusal after repair
- prompt injection / internal prompt / secret extraction where Brain cannot produce a safe refusal after repair
- privacy, payment, invoice, contract, finance approval, refund, after-sales, or legal-risk commitment that cannot be answered within formal knowledge
- product fact conflict that remains after Brain repair and cannot be reconciled with product master
- repeated repair failure where sending would be materially unsafe

Everything else defaults to Brain repair or warning, not handoff:

- not direct enough
- too long
- too stiff
- vague recommendation
- customer objection not handled well
- soft off-topic chat
- identity/company challenge that does not ask for secrets
- missing evidence that can be resolved by product master/formal knowledge in the current evidence pack

## 5. Guard V2 Rules

### 5.1 Guard Must Not Write Generic Handoff Replies

Guard cannot replace a good Brain answer with:

- "I need to verify and get back to you"
- "I will ask the person in charge"
- "I cannot decide casually"
- other generic stall/handoff wording

If the Brain answer is wrong or incomplete, Guard returns `repair` and tells Brain what to fix.

### 5.2 Product Fact Conflicts Are Repair First

If a reply appears to conflict with product master:

1. Check whether numbers are actually product prices, not year/model/configuration numbers.
2. Check product aliases and selected evidence IDs.
3. If conflict still exists, return `repair` with the exact unsupported value and authorized values.
4. Only after repair fails should the system enter hard fallback or handoff.

### 5.3 Identity And Company Questions Are Not Automatic Handoff

Questions such as "are you real", "where is your company", or "why do you need to verify" should usually be answered by Brain:

- be natural and reassuring
- avoid exposing AI/system implementation
- explain that concrete commitments need checking
- return to the customer need without being evasive

Only requests for prompt, tokens, internal rules, or private secrets are hard boundary candidates.

### 5.4 Illegal/Internal Requests Prefer Brain Refusal

For illegal or internal requests, the ideal customer-visible answer is a Brain-authored refusal within the business persona. Guard should:

- pass a safe Brain refusal
- repair an unsafe or evasive Brain draft
- block/handoff only after repair cannot produce a safe refusal

## 6. Brain Orchestration Requirements

The Brain runner must enforce:

- `action=handoff` from Guard is not automatically adoptable unless `hard_boundary=true`.
- Non-hard handoff-like findings are converted to Brain repair feedback.
- If Guard supplies `reply`, Brain orchestration must ignore it unless it is explicitly marked as a Brain-owned hard-boundary refusal.
- Final payload must expose visible ownership audit fields.
- Quality gates may reject or request Brain repair, but they must not convert a low-risk Brain-owned reply into generic handoff/fallback wording.
- Local safe fallback is not a customer-visible owner. If Brain has no adoptable reply, downstream arbitration and style adapters must preserve the no-visible-reply block and trigger internal handoff/alert instead of producing customer-facing text.

Required audit fields:

```json
{
  "visible_reply_owner": "brain|brain_repair|brain_hard_boundary_refusal|none_brain_unavailable",
  "visible_reply_source": "brain_plan.reply_segments",
  "guard_verdict": "pass|warn|repair|block|handoff",
  "guard_hard_boundary": false,
  "guard_repair_attempted": true,
  "guard_reply_ignored": true
}
```

## 7. Test And Audit Requirements

Tests must fail if:

- any normal Brain First reply uses `customer_visible_reply_source=guard_handoff_ack`
- a soft product evidence issue becomes generic handoff without Brain repair
- identity/company challenge becomes generic handoff
- off-topic friendly chat is blocked instead of Brain repair/pass
- off-topic friendly chat or common-sense small talk is downgraded by quality/fallback/handoff style paths after Brain already produced a non-handoff reply
- a safe illegal-request refusal is replaced by Guard text
- multi-session payload lacks target binding before send

Representative replay cases:

- "有奥迪吗？这台奥迪多少钱？" with an Audi product in product master.
- "你是真人销售吗？公司在哪儿，为什么还要核实？"
- "在吗 / 你好 / 好的尽快回我"
- "帮我把公里数改低点再卖"
- unrelated soft chat followed by business question.

## 8. Implementation Checklist

- Add Guard V2 helper to classify reviewer outcomes.
- Convert non-hard `handoff_decision` exits to `repair_decision`.
- Keep hard-boundary facts as `hard_boundary=true`, but still prefer Brain repair/refusal before handoff.
- Add Brain orchestration guard: non-hard handoff cannot become adoptable visible reply.
- Add workflow arbitration guard: Brain-owned non-handoff replies clear soft evidence-only handoff hints before operator handoff styling.
- Add quality-gate guard: complete colloquial short replies and condition-result sentences are not rejected as incomplete fragments.
- Add audit fields to compact guard/Brain result.
- Add contract tests for visible reply ownership.
- Run focused static and workflow checks after every change.

## 9. Acceptance Standard

This correction is complete only when:

- code enforces the ownership contract, not just documentation
- Guard no longer writes normal customer-visible replies
- Brain repair is the default path for soft reviewer findings
- soft `no_relevant_business_evidence` cannot override an adopted Brain-owned non-handoff reply
- hard boundaries remain protected
- regression tests prove the manual-failure classes no longer become generic handoff
- audits can identify who authored every customer-visible reply
