"""maibot-chat-summary-plugin

MaiBot 聊天总结插件（针对 MaiBot 1.2.x 规范升级重构版）
支持在群聊中通过 /总结 [条数] 汇总近期群聊记录，调用大模型生成总结并以转发消息形式发送。
"""

from __future__ import annotations

import re
import time
from typing import Any

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase


# ===========================================================================
# 配置模型
# ===========================================================================


class PluginSectionConfig(PluginConfigBase):
    """插件基础设置"""

    __ui_label__ = "基础设置"
    __ui_icon__ = "settings"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用聊天总结插件")
    config_version: str = Field(default="1.1.0", description="配置文件版本")
    default_message_count: int = Field(
        default=100, description="默认生成总结使用的消息条数（用户未指定数字时）"
    )
    max_message_count: int = Field(
        default=500, description="允许用户单次总结的最大消息条数上限"
    )
    max_retrieval_count: int = Field(
        default=1500, description="从数据库检索的最大候选消息条数"
    )
    max_message_length: int = Field(
        default=200, description="单条消息最大字数截断（0为不截断）"
    )
    prompt_template: str = Field(
        default="""# Role
你是一个幽默风趣、洞察敏锐的群聊气氛观察员与聊天总结专家。

# Task
请基于以下提供的群聊记录（按时间先后顺序排列），为群友生成一份结构清晰、生动有趣且内容详实的聊天总结。

# Requirements
1. 【核心焦点】：提炼群内讨论的主要话题、突发事件或争议热点（使用小标题分点阐述）。
2. 【高光时刻】：记录群友们的精彩发言、爆梗金句或高频互动的成员。
3. 【气氛速报】：简要概括当前群内的整体交流氛围与情绪倾向。
4. 【要求】：语言表达自然流畅、富有活人感，避免生硬死板的官方公文腔调；自动忽略纯表情包、复读灌水与无意义符号。

# Input Data
--- 聊天记录开始 ---
{messages}
--- 聊天记录结束 ---

# Output
请直接输出排版优雅的 Markdown 格式群聊总结报告。""",
        description="生成总结时使用的提示词模板，支持变量 {messages} 与 {message_count}",
    )


class PermissionsSectionConfig(PluginConfigBase):
    """权限与生效群设置"""

    __ui_label__ = "权限与应用范围"
    __ui_icon__ = "shield"
    __ui_order__ = 1

    group_mode: str = Field(
        default="all",
        description="群聊生效模式：'all'（所有群允许使用）或 'whitelist'（仅白名单群允许使用）",
    )
    group_whitelist: list[str] = Field(
        default=[],
        description="允许使用 /总结 命令的 QQ 群号列表（白名单模式下生效，如 ['123456789']）",
    )
    permission_mode: str = Field(
        default="blacklist",
        description="用户权限模式：'whitelist'（白名单模式）或 'blacklist'（黑名单模式）",
    )
    admin_id_list: list[str] = Field(
        default=[],
        description="管理员 QQ 号列表，不受群白名单与用户黑名单限制",
    )
    user_id_list: list[str] = Field(
        default=[],
        description="用户 QQ 号列表（根据 permission_mode 决定允许或禁止）",
    )


class LLMSectionConfig(PluginConfigBase):
    """大语言模型设置"""

    __ui_label__ = "模型配置"
    __ui_icon__ = "cpu"
    __ui_order__ = 2

    task_name: str = Field(
        default="utils",
        description="调用系统的模型任务组（如 utils, replyer, planner）",
    )
    model_name: str = Field(
        default="",
        description="指定具体模型名称（留空则自动选用任务组内的可用模型）",
    )
    temperature: float = Field(
        default=0.7, description="生成温度 (0.0 ~ 1.0)"
    )
    max_tokens: int = Field(
        default=4096, description="总结生成最大输出 Token 数"
    )


class ChatSummaryConfig(PluginConfigBase):
    """聊天总结插件总配置"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    permissions: PermissionsSectionConfig = Field(
        default_factory=PermissionsSectionConfig
    )
    llm: LLMSectionConfig = Field(default_factory=LLMSectionConfig)


# ===========================================================================
# 文本清洗工具函数
# ===========================================================================

_RE_FORWARD = re.compile(
    r"={10}\s*转发消息开始\s*={10}[\s\S]*?={10}\s*转发消息结束\s*={10}"
)
_RE_REPLY_PREFIX = re.compile(r"\[回复了.*?的消息:.*?\]\s*")
_RE_AT_MENTION = re.compile(r"@<[^>]+>")
_RE_EMOJI_BRACKET = re.compile(r"\[(?:表情包|图片|未知表情|动画表情|CQ:[a-z0-9_-]+).*?\]", re.IGNORECASE)


def _clean_and_format_messages(messages: list[dict], max_msg_len: int = 200) -> list[str]:
    """清洗从能力接口获取的原始消息列表并转为紧凑的可读文本。"""
    formatted_lines: list[str] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        # 过滤通知类事件（如拍一拍、贴表情反应、群荣誉变更等）与已识别的指令
        if msg.get("is_notify") or msg.get("is_command"):
            continue

        text = str(msg.get("processed_plain_text") or "").strip()
        if not text:
            continue

        # 过滤各类特殊系统消息标记
        if text.startswith(("[事件-", "[通知", "[文件:", "[语音:")):
            continue

        # 剥离多余的前缀和嵌套标签
        text = _RE_FORWARD.sub("", text)
        text = _RE_REPLY_PREFIX.sub("", text)
        text = _RE_AT_MENTION.sub("", text)
        text = _RE_EMOJI_BRACKET.sub("", text).strip()

        # 剥离后若无有效文字内容则跳过（避免向 LLM 喂一堆空白或无意义标点）
        if not text:
            continue

        # 截断过长消息
        if 0 < max_msg_len < len(text):
            text = text[:max_msg_len] + "…[截断]"

        # 获取用户昵称
        u_info = msg.get("message_info", {}).get("user_info", {})
        nickname = (
            str(u_info.get("user_cardname") or "").strip()
            or str(u_info.get("user_nickname") or "").strip()
            or str(u_info.get("user_id") or "群友").strip()
        )

        # 格式化时间戳
        ts_val = msg.get("timestamp")
        time_str = ""
        try:
            if ts_val is not None:
                t = float(ts_val)
                time_str = time.strftime("%m-%d %H:%M", time.localtime(t))
        except (ValueError, TypeError):
            pass

        if time_str:
            formatted_lines.append(f"[{time_str}] {nickname}: {text}")
        else:
            formatted_lines.append(f"{nickname}: {text}")

    return formatted_lines


# ===========================================================================
# 插件主类
# ===========================================================================


class ChatSummaryPlugin(MaiBotPlugin):
    """聊天总结插件主类"""

    config_model = ChatSummaryConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("聊天总结插件 (maibot-chat-summary-plugin) 已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("聊天总结插件已卸载")

    async def on_config_update(
        self, scope: str, config_data: dict[str, Any], version: str
    ) -> None:
        self.ctx.logger.info(f"聊天总结插件配置已更新 [scope={scope}, version={version}]")

    @Command(
        "summary",
        description="根据近期聊天记录生成智能总结（用法：/总结 [条数]）",
        pattern=r"^/总结(?:\s+(?P<count>\d+))?\s*$",
        aliases=["/聊天总结", "/summary"],
    )
    async def handle_summary(
        self,
        stream_id: str = "",
        group_id: str = "",
        user_id: str = "",
        matched_groups: dict | None = None,
        message: dict | None = None,
        **kwargs: Any,
    ) -> tuple[bool, str | None, bool]:
        """响应 /总结 命令。"""
        del message, kwargs
        cfg: ChatSummaryConfig = self.config  # type: ignore

        # 1. 基础总开关判断
        if not cfg.plugin.enabled:
            return False, None, False

        user_id_str = str(user_id or "").strip()
        group_id_str = str(group_id or "").strip()
        is_admin = user_id_str in [str(uid).strip() for uid in cfg.permissions.admin_id_list]

        # 2. 群聊作用域校验
        if group_id_str:
            if cfg.permissions.group_mode == "whitelist" and not is_admin:
                allowed_groups = [str(gid).strip() for gid in cfg.permissions.group_whitelist]
                if group_id_str not in allowed_groups:
                    # 不在允许群白名单中，静默跳过（不拦截后续常规对话处理）
                    return False, None, False
        else:
            # 私聊场景：若非管理员，则仅支持管理员在私聊发起跨流/独立操作
            if not is_admin:
                await self.ctx.send.text("聊天总结功能目前仅在群聊中开放。", stream_id)
                return True, None, True

        # 3. 用户黑白名单权限校验
        if not is_admin:
            user_list = [str(uid).strip() for uid in cfg.permissions.user_id_list]
            if cfg.permissions.permission_mode == "blacklist" and user_id_str in user_list:
                await self.ctx.send.text("你暂无权限使用聊天总结功能。", stream_id)
                return True, None, True
            elif cfg.permissions.permission_mode == "whitelist" and user_id_str not in user_list:
                await self.ctx.send.text("你暂无权限使用聊天总结功能。", stream_id)
                return True, None, True

        # 4. 解析要总结的消息数量
        target_count = cfg.plugin.default_message_count
        if matched_groups and matched_groups.get("count"):
            try:
                parsed_count = int(matched_groups["count"])
                target_count = max(10, min(parsed_count, cfg.plugin.max_message_count))
            except (ValueError, TypeError):
                target_count = cfg.plugin.default_message_count

        # 5. 发送前置响应提示
        await self.ctx.send.text(
            f"收到！正在整理本群近期聊天记录并生成总结，请稍候...",
            stream_id,
        )

        # 6. 从能力接口查询历史消息
        retrieval_limit = min(
            target_count * 2, cfg.plugin.max_retrieval_count
        )
        current_time = time.time()
        start_time = current_time - 86400 * 7  # 默认在最近 7 天内检索

        try:
            query_res = await self.ctx.message.get_by_time_in_chat(
                chat_id=stream_id,
                start_time=str(start_time),
                end_time=str(current_time),
                limit=retrieval_limit,
                filter_command=True,
                filter_mai=False,
            )
        except Exception as exc:
            self.ctx.logger.error(f"调用 message.get_by_time_in_chat 失败: {exc}", exc_info=True)
            query_res = None

        raw_messages: list[dict] = []
        if isinstance(query_res, dict) and query_res.get("success"):
            raw_messages = query_res.get("messages", [])
        elif isinstance(query_res, list):
            raw_messages = query_res

        # 如果通过时间范围查询结果过少，尝试通过 get_recent 补查
        if len(raw_messages) < 10:
            try:
                recent_res = await self.ctx.message.get_recent(
                    chat_id=stream_id, limit=retrieval_limit
                )
                if isinstance(recent_res, dict) and recent_res.get("success"):
                    raw_messages = recent_res.get("messages", [])
                elif isinstance(recent_res, list):
                    raw_messages = recent_res
            except Exception as exc:
                self.ctx.logger.warning(f"调用 message.get_recent 降级失败: {exc}")

        # 7. 清洗与格式化
        formatted_lines = _clean_and_format_messages(
            raw_messages, max_msg_len=cfg.plugin.max_message_length
        )

        # 取最近的 target_count 条有效对话
        if len(formatted_lines) > target_count:
            formatted_lines = formatted_lines[-target_count:]

        if len(formatted_lines) < 5:
            await self.ctx.send.text("本群近期有效聊天记录过少，暂时无法生成有价值的总结。", stream_id)
            return True, None, True

        self.ctx.logger.info(
            f"成功整理 {len(formatted_lines)} 条群聊记录，正在调用 LLM 进行总结..."
        )

        # 8. 组装提示词并调用 LLM
        messages_block = "\n".join(formatted_lines)
        prompt = cfg.plugin.prompt_template.format(
            messages=messages_block,
            message_count=len(formatted_lines),
        )

        try:
            llm_res = await self.ctx.llm.generate(
                prompt=prompt,
                task_name=cfg.llm.task_name or "utils",
                model_name=cfg.llm.model_name or "",
                temperature=cfg.llm.temperature,
                max_tokens=cfg.llm.max_tokens,
            )
        except Exception as exc:
            self.ctx.logger.error(f"调用 LLM 生成总结异常: {exc}", exc_info=True)
            await self.ctx.send.text("抱歉，大模型生成总结时遇到了网络或接口异常，请稍后重试。", stream_id)
            return True, None, True

        if not isinstance(llm_res, dict) or not llm_res.get("success"):
            err = llm_res.get("error", "未知错误") if isinstance(llm_res, dict) else "返回为空"
            self.ctx.logger.error(f"大模型生成总结失败: {err}")
            await self.ctx.send.text(f"抱歉，大模型处理失败: {err}", stream_id)
            return True, None, True

        summary_text = str(llm_res.get("response") or "").strip()
        if not summary_text:
            await self.ctx.send.text("大模型返回的内容为空，未能生成有效总结。", stream_id)
            return True, None, True

        used_model = llm_res.get("model_name") or cfg.llm.model_name or cfg.llm.task_name
        footer = f"\n\n---\n*本次总结基于最近 {len(formatted_lines)} 条有效发言，由 {used_model} 生成*"
        final_summary = summary_text + footer

        # 9. 优先使用合并转发发送，失败则降级为纯文本
        forward_success = False
        try:
            forward_nodes = [
                {
                    "user_id": "",
                    "nickname": "聊天总结助手",
                    "content": [{"type": "text", "data": final_summary}],
                }
            ]
            send_res = await self.ctx.send.forward(forward_nodes, stream_id)
            if send_res is True or (isinstance(send_res, dict) and send_res.get("success")):
                forward_success = True
        except Exception as exc:
            self.ctx.logger.warning(f"以合并转发发送总结失败，降级为纯文本发送: {exc}")

        if not forward_success:
            await self.ctx.send.text(final_summary, stream_id)

        return True, None, True


def create_plugin() -> ChatSummaryPlugin:
    """导出插件工厂函数"""
    return ChatSummaryPlugin()
