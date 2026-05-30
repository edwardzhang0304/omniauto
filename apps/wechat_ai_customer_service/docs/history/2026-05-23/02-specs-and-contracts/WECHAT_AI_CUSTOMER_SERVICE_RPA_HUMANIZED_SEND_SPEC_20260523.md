# 微信自动客服 RPA 人类化发送参数契约（2026-05-23）

## 配置节点
- 路径：`listener_config.json -> rpa_humanized_send`

## 字段定义
- `enabled: bool`
  - 是否启用人类化输入节奏。
- `input_method: enum(auto|uia_chunks|clipboard_chunks|clipboard_once)`
  - `auto`: UIA 优先分段，失败再走剪贴板守卫；
  - `uia_chunks`: 强制 UIA 分段赋值；
  - `clipboard_chunks`: 强制剪贴板分段；
  - `clipboard_once`: 单次粘贴兼容兜底。
- `typing_chunk_min_chars: int`
- `typing_chunk_max_chars: int`
  - 分段长度区间，最小不小于 1，且 `max >= min`。
- `typing_char_delay_min_ms: int`
- `typing_char_delay_max_ms: int`
  - 每段输入后的延时按字符数线性放大。
- `typing_micro_pause_every_chars: int`
- `typing_micro_pause_min_ms: int`
- `typing_micro_pause_max_ms: int`
  - 长文本中的“停顿呼吸”参数。
- `typing_typo_probability: float(0~1)`
- `typing_typo_max: int`
  - 小概率“错字->删除”模拟，最终文本不变。
- `send_pre_delay_min_ms: int`
- `send_pre_delay_max_ms: int`
- `send_post_input_delay_min_ms: int`
- `send_post_input_delay_max_ms: int`
  - 发送前后节奏延时。

## 环境变量映射
- `WECHAT_WIN32_OCR_HUMANIZED_INPUT_ENABLED`
- `WECHAT_WIN32_OCR_HUMANIZED_INPUT_METHOD`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MIN_CHARS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MAX_CHARS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_MICRO_PAUSE_EVERY_CHARS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_PROBABILITY`
- `WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_MAX`
- `WECHAT_WIN32_OCR_HUMANIZED_SEND_PRE_DELAY_MIN_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_SEND_PRE_DELAY_MAX_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_SEND_POST_INPUT_DELAY_MIN_MS`
- `WECHAT_WIN32_OCR_HUMANIZED_SEND_POST_INPUT_DELAY_MAX_MS`

## 合规边界
- 本契约不包含设备指纹伪造、硬件地址伪装、客户端逆向补丁能力。
- 若检测到登录页或安全阻塞，必须停机，不允许继续自动发送。
