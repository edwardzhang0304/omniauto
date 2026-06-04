# 微信自动客服高并发保质量测试计划（2026-06-02）

## 1. 测试目标
验证“后台高并发 + 前台串行”改造后：
1. 回复质量不下降。
2. 多会话总体吞吐提升。
3. 不引入错发、漏回、重复回、白屏、风控放大等新问题。

## 2. 测试范围

### 2.1 离线逻辑
- Planner/Polish 双池状态流转。
- 同会话单 inflight 约束。
- Ready queue 顺序与 stale 行为。
- polish 失败降级但不导致主回复失败。

### 2.2 无发送重放
- 三会话并发 capture 样本重放。
- 禁用 polish cache，确保真实打当前 API。
- 验证 planner 与 polish 都可并发完成。

### 2.3 实盘
- 两会话真人节奏。
- 三会话真人节奏。
- 高频追问、连续问题、改口、闲聊穿插。

## 3. 用例矩阵

### T1 状态机正确性
1. planner 完成后必须进入 polish 队列，而不是直接 ready。
2. polish 完成后才进入 ready。
3. polish 失败但有安全草稿时，ready reply 仍可形成。
4. 旧版本 reply 在新版本完成后必须 stale。

### T2 并发与公平性
1. 三个会话同时 pending，planner 可并发提交。
2. polish 不应占满 planner 并发额度。
3. 慢会话不应阻塞其他会话的 planner 提交。
4. 发送阶段依然 FIFO 串行。

### T3 质量与降级
1. final polish 正常完成时，话术与当前版本一致或更自然。
2. final polish 超时/guard 拒绝时，回退草稿但不能主任务失败。
3. 不允许因为高并发改造而把错误会话内容发到别的窗口。

### T4 真实链路
1. `文件传输助手 / 许聪 / 新数据测试` 三会话混合触发。
2. 任一会话连续两问，另一个会话插入新问题。
3. 发送顺序符合“谁先 ready 谁先排队，前台仍单发”的设计。

## 4. 指标与判定

### 4.1 正确性指标
- 错会话发送：`0`
- 漏回：`0`
- 重复回复：`0`
- 因并发导致的白屏：`0`

### 4.2 质量指标
- 回复业务正确性不低于当前版本。
- `polish_applied` 命中率不得异常下降。
- `degraded` 仅可出现在真实上游异常或 guard 拒绝场景。

### 4.3 性能指标
- 同样三会话压力下：
1. 总 ready 完成时间低于当前版本。
2. planner 排队时间明显下降。
3. 单条回复长尾不因资源争抢明显变差。

## 5. 必跑脚本

### 5.1 静态
- `python -m py_compile ...`

### 5.2 离线
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
- 新增：高并发双池调度检查脚本

### 5.3 无发送重放
- 三会话 no-send replay
- 三会话 no-send replay（polish cache disabled）

### 5.4 实盘
- 文件传输助手多轮
- 两会话真人节奏
- 三会话真人节奏

## 6. 结果产物
- scheduler state JSON
- managed listener log
- no-send replay JSON
- 实盘验收报告

## 7. 失败即阻断的场景
1. 任何一次错发到错误会话。
2. 因并发造成微信前台并发操控。
3. 因并发改造造成 final polish 常态失效。
4. 质量明显下降但仅靠“更快”掩盖。
