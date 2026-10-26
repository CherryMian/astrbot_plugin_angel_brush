"""LLM tools for Angel Brush - 2 tools with angel_ prefix."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .core.ratelimit import rate_limiter

_GEN_BASE_DESC = "根据提示词生成一张图片，自动保存到插件数据目录；返回为 file 绝对路径，禁止在 markdown 内联。"
_EDIT_BASE_DESC = "基于一张或多张输入图片按提示词编辑出新图（局部修改、消除、换背景、扩图、多图融合、风格参考），自动保存到插件数据目录；返回为 file 绝对路径，禁止在 markdown 内联。"
_EDIT_DISABLED_DESC = "【当前已禁用】图片编辑功能当前已被管理员关闭。请不要调用此工具。"


def _extract_user_and_chat(context: Any) -> tuple[str, str]:
    """提取调用者的用户 ID 和会话 ID，以支持多维度速率限制。"""
    user_id = "default_user"
    chat_id = "default_chat"
    if context is None:
        return user_id, chat_id

    ctx = getattr(context, "context", context)
    event = (
        getattr(ctx, "event", None)
        or getattr(context, "event", None)
        or getattr(ctx, "message_event", None)
    )

    if event:
        for attr in ("get_sender_id", "sender_id", "user_id"):
            val = getattr(event, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if val:
                user_id = str(val).strip()
                break

        for attr in ("get_session_id", "session_id", "unified_msg_origin", "chat_id", "group_id"):
            val = getattr(event, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if val:
                chat_id = str(val).strip()
                break
    else:
        session = getattr(ctx, "session", None) or getattr(context, "session", None)
        if session:
            uid = getattr(session, "user_id", None)
            if uid:
                user_id = str(uid).strip()
            sid = getattr(session, "session_id", None) or getattr(session, "id", None)
            if sid:
                chat_id = str(sid).strip()

    return user_id, chat_id


def _style_suffix(data_dir: Path) -> str:
    """读取画风配置并拼出 description 后缀；无画风时返回空串。"""
    from .core import config as cfg

    try:
        providers, default_id = cfg.load_config(data_dir)
        style = cfg.load_style_config(data_dir)
        hint = cfg.build_style_hint(
            providers,
            default_id,
            style.get("style_recommend", False),
            style.get("custom_style", ""),
        )
        return f"\n\n画风要求：{hint}" if hint else ""
    except Exception:
        return ""


def _fixed_params_suffix(data_dir: Path) -> str:
    """读取固定参数配置，并在 description 给出友好提示。"""
    from .core import config as cfg

    try:
        fixed = cfg.load_fixed_params(data_dir)
        if fixed.get("enabled"):
            items = []
            if fixed.get("resolution"):
                items.append(f"分辨率={fixed['resolution']}")
            if fixed.get("quality"):
                items.append(f"质量={fixed['quality']}")
            if items:
                return f"\n\n（注意：管理员已全局锁定生图参数：{', '.join(items)}，传入其他参数将被自动覆盖）"
    except Exception:
        pass
    return ""


def _update_description(
    tool: "AngelImageGenerateTool | AngelImageEditTool", base: str, data_dir: Path
) -> None:
    from .core import config as cfg

    if isinstance(tool, AngelImageEditTool):
        if not cfg.load_edit_enabled(data_dir):
            tool.description = _EDIT_DISABLED_DESC
            return

    tool.description = base + _style_suffix(data_dir) + _fixed_params_suffix(data_dir)


def update_tool_descriptions(
    gen_tool: "AngelImageGenerateTool | None", edit_tool: "AngelImageEditTool | None"
) -> None:
    """按当前画风及配置刷新两个工具的 description（运行时调用，无需重启）。"""
    if gen_tool is not None:
        _update_description(gen_tool, _GEN_BASE_DESC, gen_tool.data_dir)
    if edit_tool is not None:
        _update_description(edit_tool, _EDIT_BASE_DESC, edit_tool.data_dir)


def _tool_success_value(result: dict[str, Any], prefix: str) -> str:
    images = result.get("images") or []
    image_lines = "\n".join(
        f"- {img.get('absolute_path') or img.get('relative_path')}" for img in images
    )

    payload = {
        "ok": True,
        "message": (
            f"{prefix}。已落盘到插件数据目录，返回为 file 绝对路径。必须使用 send_message_to_user 发送给用户，禁止在 markdown 内联。\n"
            f"调用示例：{{\"messages\": [{{\"type\": \"image\", \"path\": \"<file 绝对路径>\"}}]}}\n"
            f"待发送的图片 file 路径如下：\n{image_lines}\n"
            f"收到本工具结果后，立即调用 send_message_to_user 发送以上 file 路径的图片，不要只回复文字。"
        ),
        "provider": result.get("provider_name"),
        "providerType": result.get("provider_type"),
        "modelId": result.get("model_id"),
        "model": result.get("model"),
        "images": images,
        "providerText": result.get("provider_text"),
    }
    return json.dumps(payload, ensure_ascii=False)


def _tool_error_value(message: str) -> str:
    return json.dumps({"ok": False, "message": message}, ensure_ascii=False)


@dataclass
class AngelImageGenerateTool(FunctionTool[AstrAgentContext]):
    name: str = "angel_image_generate"
    description: str = _GEN_BASE_DESC
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "生成图片时，把提示词写成一段连续的中文描述，包含主体、场景、光线、风格、构图，以及画面的情绪、氛围和故事感。描述要细致，用词要华丽，文笔要丰富，尽可能丰富，像在给画家描述一幅你想画的画，写成一篇小作文。不只是描述画面里有什么，还要描述这幅画给人的感觉、藏着的情感和故事。",
                },
                "resolution": {
                    "type": "string",
                    "description": "分辨率，例如 1024x1024，默认 1920x1920。",
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        }
    )
    data_dir: Path = field(default=None)  # type: ignore[assignment]

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        from .core import config as cfg
        from .core import service

        # 每次调用前刷新 description
        try:
            _update_description(self, _GEN_BASE_DESC, self.data_dir)
        except Exception:
            pass

        # 速率限制校验
        rl_cfg = cfg.load_ratelimit_config(self.data_dir)
        if rl_cfg.get("enabled"):
            user_id, chat_id = _extract_user_and_chat(context)
            allowed, reason = await rate_limiter.check_and_record(
                rl_cfg, user_id=user_id, chat_id=chat_id
            )
            if not allowed:
                return _tool_error_value(
                    f"【调用频率限制】{reason}。请直接向用户转述该限制，不要立即重试生图。"
                )

        prompt = str(kwargs.get("prompt") or "").strip()
        resolution = str(kwargs.get("resolution") or "").strip() or None
        result = await service.generate_images(
            self.data_dir,
            {"prompt": prompt, "size": resolution, "operation": "generate"},
        )
        return _tool_success_value(result, "图片已生成并保存到插件数据目录")


@dataclass
class AngelImageEditTool(FunctionTool[AstrAgentContext]):
    name: str = "angel_image_edit"
    description: str = _EDIT_BASE_DESC
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "编辑意图描述，说明要修改什么、保留什么。",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "输入图片引用列表，支持插件数据目录相对路径、本地绝对路径或 data URL；多张时用于多图融合/参考。",
                },
                "mask": {
                    "type": "string",
                    "description": "可选 mask 图片引用，白色/不透明区域表示允许修改；仅部分供应商支持，不支持时会返回错误。",
                },
            },
            "required": ["prompt", "images"],
            "additionalProperties": False,
        }
    )
    data_dir: Path = field(default=None)  # type: ignore[assignment]

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        from .core import config as cfg
        from .core import service

        # 每次调用前刷新 description
        try:
            _update_description(self, _EDIT_BASE_DESC, self.data_dir)
        except Exception:
            pass

        # 改图开关校验
        if not cfg.load_edit_enabled(self.data_dir):
            return _tool_error_value(
                "【功能已关闭】管理员已禁用图片编辑功能（angel_image_edit），无法执行改图操作。请直接礼貌告知用户图片编辑功能当前已关闭。"
            )

        # 速率限制校验
        rl_cfg = cfg.load_ratelimit_config(self.data_dir)
        if rl_cfg.get("enabled"):
            user_id, chat_id = _extract_user_and_chat(context)
            allowed, reason = await rate_limiter.check_and_record(
                rl_cfg, user_id=user_id, chat_id=chat_id
            )
            if not allowed:
                return _tool_error_value(
                    f"【调用频率限制】{reason}。请直接向用户转述该限制，不要立即重试改图。"
                )

        prompt = str(kwargs.get("prompt") or "").strip()
        images = kwargs.get("images") or []
        mask = str(kwargs.get("mask") or "").strip() or None
        if isinstance(images, str):
            images = [images]
        images = [str(x).strip() for x in images if str(x).strip()]
        result = await service.generate_images(
            self.data_dir,
            {"prompt": prompt, "images": images, "mask": mask, "operation": "edit"},
        )
        return _tool_success_value(result, "图片已编辑并保存到插件数据目录")
