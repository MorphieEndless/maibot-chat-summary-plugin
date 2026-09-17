# maibot-chat-summary-plugin
MaiBot 的智能聊天总结插件（已全面升级适配 MaiBot 1.2.x 现代 SDK 架构）。

## 功能特性
- **智能总结提炼**：通过 `/总结` 指令自动梳理近期群聊上下文，调用大模型提炼核心焦点、高光金句与交流气氛。
- **高信噪比清洗**：自动剔除表情反应（Reaction）、拍一拍、进群退群通知与纯表情包占位符，支持单条发言长度智能截断。
- **优雅防刷屏**：优先采用合并转发消息（Forward Node）发送总结，若适配器或通道受限则自动平滑降级为纯文本。
- **完善的权限体系**：支持群聊白名单模式（`whitelist` / `all`）与用户权限控制（`whitelist` / `blacklist`），内置全局管理员特权。
- **现代 SDK 架构**：全面迁移至 `maibot_sdk.MaiBotPlugin` 标准，天然支持 MaiBot WebUI 可视化参数配置与热重载。

## 使用方法
在已启用的群聊中发送：
- `/总结`：拉取本群最近 100 条有效发言生成总结报告；
- `/总结 <count>`：指定拉取条数（例如 `/总结 50` 或 `/总结 200`，支持范围 10~500）；
- `/summary` 或 `/聊天总结`：同义别名。

## 安装步骤
1. 进入 MaiBot 插件目录：
   ```bash
   cd <maibot 根目录>/data/MaiMBot/plugins
   git clone https://github.com/Bdbmzwsc/maibot-chat-summary-plugin
   ```
2. 重启麦麦容器或进程：
   ```bash
   docker restart maim-bot-core
   ```
3. 插件将在启动时自动加载并注册命令，首次启动会自动生成默认配置文件。

## 配置说明
插件配置位于 WebUI「插件设置」或本地 `config.toml`：

```toml
[plugin]
enabled = true
default_message_count = 100
max_message_count = 500
max_retrieval_count = 1500
max_message_length = 200

[permissions]
group_mode = "all"            # 可选 "all"（全部群）或 "whitelist"（仅白名单群）
group_whitelist = []          # 白名单群号列表，如 ["123456789"]
permission_mode = "blacklist" # 可选 "blacklist" 或 "whitelist"
admin_id_list = []            # 管理员 QQ 列表，不受群与用户限制
user_id_list = []             # 受限或允许的用户 QQ 列表

[llm]
task_name = "utils"           # 调用系统的模型组（如 utils, replyer, planner）
model_name = ""               # 指定模型名称（留空则跟随系统任务组）
temperature = 0.7
max_tokens = 4096
```

## 免责声明
本插件仅供群聊娱乐与交流归纳使用。
- 所有总结内容均由大语言模型基于群聊记录归纳生成，不代表真实人物评价或立场。
- 请勿将总结结果用于人身攻击或其他不当用途。
