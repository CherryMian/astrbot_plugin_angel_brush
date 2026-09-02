"""LLM tools for Angel Brush - 2 tools with angel_ prefix."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


def _tool_success_value(result: dict[str, Any], prefix: str) -> str:
    images = result.get("images") or []
    image_lines = "\n".join(
        f"- {img.get('absolute_path') or img.get('relative_path')}" for img in images
    )
    import json

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


@dataclass
class AngelImageGenerateTool(FunctionTool[AstrAgentContext]):
    name: str = "angel_image_generate"
    description: str = "根据提示词生成一张图片，自动保存到插件数据目录；返回为 file 绝对路径，禁止在 markdown 内联。"
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "详细、可直接交给生图模型的提示词。",
                },
                "resolution": {
                    "type": "string",
                    "description": "分辨率，例如 1024x1024，默认 1024x1024。",
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
        from .core import service

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
    description: str = "基于一张或多张输入图片按提示词编辑出新图（局部修改、消除、换背景、扩图、多图融合、风格参考），自动保存到插件数据目录；返回为 file 绝对路径，禁止在 markdown 内联。"
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
        from .core import service

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
