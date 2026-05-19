# 行业共享知识库上线清单（2026-05-07）

## 1. 发布前
- 已确认 4 个默认行业存在且状态为 active：
  - `used_car`
  - `home_appliance`
  - `fast_food`
  - `lab_instruments`
- 已确认现有租户行业绑定：
  - `jiangsu_chejin_usedcar_customer_20260501 -> used_car`
  - `default/test01 -> home_appliance`
- 已完成共享库种子初始化（global + 4 行业）
- 已完成新建账号行业菜单联调
- 已完成强制在线演练（离线锁定、上线解锁、续租停服）

## 2. 发布窗口动作
1. 发布服务端代码（VPS admin + shared snapshot builder）。
2. 发布客户端代码（cloud gate + runtime start/续租 + 规则只读）。
3. 打开生产配置：
   - `WECHAT_CLOUD_REQUIRED=1`
   - `WECHAT_CLOUD_STRICT_ONLINE=1`
4. 执行一次 `shared/cloud-snapshot` 强制刷新。
5. 在控制台抽样验证 3 个租户：
   - 行业字段
   - 快照行业
   - policy_bundle 行业一致

## 3. 发布后监控
- 监控指标：
  - `cloud_gate.reason`
  - `managed_listener_cloud_refresh_failed` 计数
  - `423 cloud_authoritative_access_required` 请求量
- 重点关注：
  - 节点注册/令牌是否过期导致续租失败
  - 网络探测误报（探测超时阈值过严）

## 4. 故障处理优先级
1. 云端不可达：先恢复 VPS 可达性。
2. 节点鉴权失败：检查 node token / bearer token 生命周期。
3. 快照不完整：检查 `policy_bundle.merged` 是否生成。
4. 租户行业错配：修正 tenant `industry_id` 后强制刷新快照。

## 5. 紧急兜底策略（审批后）
- 临时改为：
  - `WECHAT_CLOUD_REQUIRED=0`
  - `WECHAT_CLOUD_STRICT_ONLINE=0`
- 风险：
  - 客户端可在离线状态继续运行（失去强管控）
- 要求：
  - 故障修复后必须恢复强制在线配置并补做一次全量验收。
