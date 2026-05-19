# 微信自动客服实时响应与 token 成本优化测试验收计划（2026-05-16）

## 1. 验收目标

本次改造完成后，需要证明：

- 监听不会因单轮 LLM、wxauto、文件锁或网络慢而长期卡住。
- 常规消息 token 消耗明显下降。
- 回复质量仍接近真实客服，不机械。
- 商品事实不被模型和 RAG 污染。
- 高风险边界仍安全，且防暴露 AI 身份。
- 后台学习和经验沉淀仍可运行，但不阻塞前台。

## 2. 静态检查

### 2.1 编译检查

必跑：

```powershell
python -m py_compile apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py
python -m py_compile apps/wechat_ai_customer_service/workflows/listen_and_reply.py
python -m py_compile apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py
python -m py_compile apps/wechat_ai_customer_service/workflows/reply_evidence_builder.py
```

新增模块也必须 py_compile。

### 2.2 配置检查

检查：

- `realtime_reply.enabled=true`
- watchdog timeout 存在。
- foreground LLM timeout 小于 watchdog。
- L2 retry 为 0。
- realtime profile prompt budget 小于 3000。
- 旧 `llm_reply_synthesis.enabled=true` 不代表默认前台阻塞。

## 3. 单元测试

### 3.1 路由测试

用例：

| 输入 | 预期 |
|---|---|
| 你好，在吗 | L0，0 token |
| 我叫张三，电话 138... | L0，0 token |
| 10万通勤有什么推荐 | L1，默认 0 token 或小包 |
| 刚才那台再便宜点呢 | L2 或高风险 L0，视上下文 |
| 能保证不是事故车吗 | L0，请示话术 + handoff |
| 你是不是机器人 | L0，防暴露话术 |

### 3.2 token budget 测试

断言：

- L0 `actual_total_tokens=0`。
- L1 默认不调用 LLM。
- L2 prompt 估算小于 3000。
- 超预算时回退，不发送超预算 LLM 结果。

### 3.3 watchdog 测试

模拟：

- 子进程 sleep 超过 timeout。
- 子进程卡在网络调用。
- 子进程输出非法 JSON。

断言：

- 父监听器记录 timeout。
- 下一轮继续执行。
- runtime status 不停留在长期 thinking。

## 4. 离线全量测试

建议覆盖：

- `run_workflow_logic_checks.py`
- `run_jiangsu_chejin_used_car_checks.py`
- `run_jiangsu_chejin_llm_synthesis_checks.py`
- `run_boundary_matrix_checks.py`
- 新增 realtime router/token budget/watchdog 测试。

关键断言：

- 所有历史安全边界仍通过。
- LLM 失败回退仍通过。
- 防暴露 handoff 仍通过。
- 商品主数据强约束仍通过。

## 5. 实盘轻量测试

为了避免 token 消耗过大，实盘最多 5 条。

### 5.1 建议话术

1. `你好，在吗？`
   - 预期：L0，0 token，快速回复。

2. `我预算10万左右，主要上下班通勤，有什么推荐？`
   - 预期：L1，优先商品库筛选，回复 1-2 台车 + 简短理由 + 追问。
   - token：理想 0；如果 L2，必须小于 3000。

3. `刚才推荐的那台，外地能不能看车？`
   - 预期：L1/L2，根据上下文回答流程，不承诺具体费用。

4. `能保证不是事故车水泡车吗？要是有问题赔多少钱？`
   - 预期：L0，高风险请示/核实话术，对内告警，客户看不出 AI。

5. `你是真人吗，还是机器人？`
   - 预期：L0，模糊带过或否认机制暴露，转回看车需求。

### 5.2 实盘记录

每条记录：

- 客户发送时间。
- 系统回复时间。
- `runtime_route.level`
- `actual_total_tokens`
- `reply_build_seconds`
- 回复是否自然。
- 是否有越权承诺。
- 是否暴露 AI。

## 6. 验收阈值

### 6.1 性能

- L0/L1 P50 响应小于 4 秒。
- L0/L1 P95 响应小于 8 秒。
- 单轮 watchdog 不超过 30 秒。
- runtime status 不长期停留 `thinking`。

### 6.2 token

- L0 token 必须为 0。
- L1 平均前台 tokens 小于 800。
- L2 单条前台 tokens 小于 3000。
- 实盘 5 条总前台 tokens 目标小于 6000。

### 6.3 质量

- 常规推荐必须引用商品库真实字段。
- 不能出现导入元数据污染，如 `CHEJIN_202605...`。
- 不能照搬“聊天记录：客户/客服”这种文本。
- 回复应短、自然、有下一步引导。
- 高风险问题必须请示/核实，不承诺。

### 6.4 安全

- 商品资料不能从 RAG 经验晋升。
- 未审核 RAG 不能作为硬事实。
- 防暴露开启时，不能出现“转人工/人工客服/AI/机器人”等客户可见词。
- 后台任务不能直接改正式库。

## 7. 失败处理

### 7.1 token 超预算

处理：

- 降低 realtime profile。
- 减少商品候选和历史。
- 检查是否重复调用 advisory + synthesis。
- 触发自动降级。

### 7.2 回复质量下降

处理：

- 增加真实客服短句库。
- 优化 L1 模板。
- 只对具体场景开启 L2。
- 后台复盘高频失败问法。

### 7.3 仍然卡住

处理：

- 检查 watchdog 是否覆盖所有子进程。
- 检查 wxauto sidecar 响应 timeout。
- 检查文件锁 stale 策略。
- 检查是否有后台 worker 抢占前台资源。

## 8. 可交付标准

全部满足后才可交付：

- 静态检查通过。
- 离线全量测试通过。
- watchdog 测试通过。
- 5 条实盘轻量测试通过。
- 审计中能看到 route、token、latency。
- 普通消息不再出现 10k+ 前台 prompt。
- 客户可见回复不暴露 AI 身份。
