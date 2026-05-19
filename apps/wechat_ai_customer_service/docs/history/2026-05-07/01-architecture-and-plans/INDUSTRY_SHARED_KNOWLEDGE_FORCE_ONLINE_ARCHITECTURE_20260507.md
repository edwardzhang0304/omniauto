# 行业共享知识库 + 强制在线架构（2026-05-07）

## 1. 目标与结论
本次架构升级目标：
- 把单一“共享公共知识库”升级为“全局共享 + 行业共享”双层共享体系。
- 客户账号按租户行业自动匹配对应行业共享库，实现更精准客服推理。
- 把“平台底线规则 + 平台通用理解词典”收拢到云端策略包，下发到客户端缓存。
- 在产品层面启用强制在线（Fail-Closed）：离线、续租失败、云端门禁失败时，客户端不可用。

结论：方案合理，且已经落地核心代码；客户端改动确实很小，主要是读取/展示与只读交互，不再承担规则主存储。

## 2. 分层模型（四层）
运行时知识层按优先级：
1. Tenant 专有知识（客户私有）
2. Industry Shared 行业共享知识（按行业匹配）
3. Global Shared 全局共享知识（跨行业兜底）
4. Platform Policy Bundle（云端下发的平台底线规则与理解词典）

说明：
- 业务问答的“知识命中”仍遵循 Tenant > Industry > Global 的覆盖逻辑。
- 安全与意图基础能力由 `policy_bundle.merged` 提供，并且在云端强制模式下本地只读。

## 3. 数据模型与关键字段
### 3.1 租户行业绑定
- `tenant.json` / VPS tenant record 新增：
  - `industry_id`: `used_car | home_appliance | fast_food | lab_instruments`

默认绑定：
- `jiangsu_chejin_usedcar_customer_20260501 -> used_car`
- `default -> home_appliance`
- `test01 -> home_appliance`

### 3.2 共享库条目
共享条目新增行业维度：
- `industry_id`
  - `global` 表示全局共享规则
  - 其他为行业规则

### 3.3 云端快照结构
`/v1/shared/knowledge` 下发快照包含：
- `tenant_industry_id`
- `industry_catalog`
- `items`（仅 global + 当前租户行业）
- `policy_bundle`（`global / industry / merged`）

## 4. 强制在线门禁（Fail-Closed）
### 4.1 门禁判定
客户端门禁状态依赖：
- VPS 地址已配置
- 快照来源合法（`cloud_official_shared_library`）
- 共享快照 lease 有效
- `policy_bundle.merged` 完整（包含 safety + understanding）
- 严格在线模式下，云端健康探测可达 + 快照新鲜度满足阈值

### 4.2 锁定行为
当门禁不通过：
- Admin Backend 非豁免接口返回 `423 cloud_authoritative_access_required`
- 自动客服 Runtime 启动被拒绝
- 已运行的 listener 续租失败或门禁失败后自动停服

### 4.3 续租策略
- 启动时强制拉取最新共享行业快照。
- 运行中按周期续租（默认 20 秒，可配置）。
- 任一轮续租失败即停服（强约束模式）。

## 5. 客户端边界（回答“客户端是不是只需小改”）
判断：是，客户端只需小改但不是“零改动”。

客户端最小改动点：
- 读取云端快照中的 `policy_bundle.merged`。
- 平台规则编辑页识别 `readonly=true` 并禁改。
- 云端门禁失败时显示锁定态（`423` 及原因）。

不需要做的大改动：
- 不需要本地维护行业规则主数据。
- 不需要重建本地多行业知识数据库结构。

## 6. 安全现实与工程边界
“客户端不可绕过”在通用本地环境里只能做到“工程上强约束”，不能做到“数学上绝对不可绕过”。要继续提升强度，需叠加：
- 安装包签名与完整性校验
- 核心逻辑二进制化与反篡改
- 服务端挑战签名与短时令牌
- 设备指纹 + 节点证书 + 频繁续租

当前落地方案已满足业务层强管控目标：不连服务端、不通过续租，不可用。
