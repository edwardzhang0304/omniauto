# 实盘话术风格适配器数据协议

## 风格样本

标准样本结构：

```json
{
  "id": "style_xxx",
  "tenant_id": "tenant_xxx",
  "industry_id": "used_car",
  "source_type": "cleaned_real_chat_pack",
  "source_id": "chejin_real_xxx",
  "scenario": "price_objection",
  "customer_stage": "comparison",
  "customer_message": "这个价格感觉有点高",
  "service_reply": "哥，这个价确实不是最低的，但车况和手续都比较稳，您主要是预算卡在哪个区间？",
  "tone_tags": ["natural", "concise", "wechat"],
  "intent_tags": ["price", "budget"],
  "borrowable_patterns": ["先接住情绪", "解释价值", "反问预算"],
  "risk_tags": [],
  "quality_score": 0.86,
  "status": "active"
}
```

## 运行输入

适配器运行时接收：

```json
{
  "tenant_id": "tenant_xxx",
  "customer_message": "客户当前消息",
  "base_reply": "系统基础回复",
  "source_channel": "realtime",
  "recent_reply_texts": ["最近已发送回复"],
  "evidence_pack": {},
  "identity_guard_enabled": true
}
```

`source_channel` 可选值：

- `realtime`
- `rag`
- `llm`
- `rule`
- `handoff`

## 运行输出

```json
{
  "enabled": true,
  "applied": true,
  "mode": "fast_local",
  "reason": "style_adapter_applied",
  "source_channel": "realtime",
  "style_source_ids": ["chejin_real_xxx"],
  "raw_reply_text": "适配后的无前缀回复",
  "reply_text": "适配后的客户可见回复",
  "guard": {
    "allowed": true,
    "changed_facts": false
  }
}
```

## 商品主数据隔离

商品资料只能由商品库手动导入或维护。

风格适配器不得从聊天记录中吸收以下内容为事实：

- 车型/型号主数据。
- 价格。
- 库存。
- 优惠。
- 合同开票规则。
- 售后或质量承诺。

如果实盘聊天片段里含有这些内容，适配器只能学习句式，不得复制事实内容。

## 审计要求

每次适配都应记录：

- 是否启用。
- 是否生效。
- 使用了哪些样本。
- 为什么未生效。
- 是否触发事实漂移拦截。
- 是否触发防AI暴露兜底。
