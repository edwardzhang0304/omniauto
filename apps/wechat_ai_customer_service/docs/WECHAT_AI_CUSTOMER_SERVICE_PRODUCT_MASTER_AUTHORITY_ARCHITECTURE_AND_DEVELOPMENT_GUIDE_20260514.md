# 微信自动客服 商品主数据权威化架构与开发指南（2026-05-14）

## 1. 目标定义
- 商品主数据（`products`、`erp_exports`）属于“确定性事实层”。
- 该层仅允许人工控制入口写入，不允许聊天经验、RAG经验、候选晋升或相近覆盖写回。
- 自动客服运行时只读取该层，不得从回复过程反向更新该层。

## 2. 分层职责
- 正式知识层（商品主数据）：权威事实，人工维护，供运行时引用。
- 经验层（RAG经验）：观察与表达素材，可自动分诊，但不具备商品主数据写权限。
- 候选层（review_candidates）：用于话术/规则候选审核，不承担商品主数据入库职责。

## 3. 允许与禁止的写入路径
### 3.1 允许（商品主数据）
- 商品控制台人工录入与维护（`/api/product-console/*`）。
- 人工确认后保存到商品库（`KnowledgeGenerator.confirm_session` / `ProductConsoleService.save_product_item`）。

### 3.2 禁止（已硬关闭）
- `RAG经验 -> 商品候选`（`build_candidate_from_experience`）。
- `候选 -> 商品主数据 apply`（`CandidateStore.apply_native_candidate`）。
- `候选分类改写到 products/erp_exports`（`CandidateStore.change_candidate_category`）。
- `RAG formal overlap 用经验覆盖/合并商品主数据`（`resolve_formal_overlap` 非 discard 策略 + `save_formal_item`）。

## 4. 核心策略
### 4.1 Source Authority 全源硬拒
- `evaluate_candidate_source_authority`：对 `products/erp_exports` 一律拒绝。
- `evaluate_experience_source_authority`：对 `products/erp_exports` 一律拒绝。
- 不再依赖“是否 observed_wechat”作为商品主数据拦截条件。

### 4.2 经验层自动降噪
- 对命中“商品主数据形态（车型/价格/库存等）”的 RAG经验，自动分诊为 `discard`。
- 目标是减少人工审核噪音，避免运营误升。

## 5. 代码落地点
- `admin_backend/services/source_authority_policy.py`
- `admin_backend/services/rag_admin_service.py`
- `admin_backend/services/rag_experience_interpreter.py`
- `admin_backend/services/candidate_store.py`
- `tests/run_admin_backend_checks.py`

## 6. 兼容性说明
- 上传识别与候选生成能力保留（用于解析与审阅），但商品主数据写回由策略层统一阻断。
- 对政策/话术/商品专属知识（`product_faq` 等）链路不做本次破坏性改动。

## 7. 风险与边界
- 风险：历史流程若依赖“候选直接写商品库”，将改为失败并提示手动入口。
- 处理：前端/操作手册明确“商品主数据仅走商品库人工维护”。
- 非目标：本次不改动运行时回答策略本身，只改写入治理边界。
