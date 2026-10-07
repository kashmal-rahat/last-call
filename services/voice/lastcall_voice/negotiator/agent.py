"""Negotiator LLM Agent creation and callback configuration."""

import logging
from datetime import datetime
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo
from pydantic import AwareDatetime

from google.adk.agents import LlmAgent
from google.adk.tools import BaseTool
from google.adk.tools.tool_context import ToolContext
from lastcall_shared.logging_utils import mask_pii_data
from lastcall_shared.models import AgentDealBrief
from lastcall_voice.negotiator.prompt import render_instruction
from lastcall_voice.negotiator.tools import get_negotiator_tools

PKT = ZoneInfo("Asia/Karachi")
logger = logging.getLogger("lastcall_voice.negotiator")


def build_negotiator(
    model: str,
    view: AgentDealBrief,
    *,
    mode: Literal["text", "voice"] = "text",
    agent_gender: Literal["male", "female"] = "male",
    city_style: Literal["karachi", "lahore", "islamabad"] = "karachi",
    clock: Callable[[], AwareDatetime] | None = None,
) -> LlmAgent:
    """Builds the Negotiator LlmAgent with dynamic prompt and blocking tools.

    Privacy & Security Rules:
    - Never log transcript text, audio, or the floor price.
    - All tools are BLOCKING.
    - Instruction is dynamically rendered per turn/context.
    """
    now_fn = clock or (lambda: datetime.now(PKT))

    def _instruction_provider(ctx: Any) -> str:
        return render_instruction(
            view,
            mode=mode,
            agent_gender=agent_gender,
            city_style=city_style,
            now=now_fn(),
        )

    async def before_tool_callback(tool: BaseTool, args: dict, tool_context: ToolContext) -> None:
        tool_name = getattr(tool, "name", str(tool))
        safe_args = mask_pii_data(args) if isinstance(args, dict) else {}
        logger.info(
            "tool_call_start",
            extra={
                "tool": tool_name,
                "call_id": tool_context.state.get("call_id") if tool_context else None,
                "args": safe_args,
            },
        )
        return None

    async def after_tool_callback(
        tool: BaseTool,
        args: dict,
        tool_context: ToolContext,
        tool_response: dict,
    ) -> None:
        tool_name = getattr(tool, "name", str(tool))
        decision = None
        if isinstance(tool_response, dict):
            decision = tool_response.get("decision") or tool_response.get("ok") or tool_response.get("recorded")
        logger.info(
            "tool_call_end",
            extra={
                "tool": tool_name,
                "call_id": tool_context.state.get("call_id") if tool_context else None,
                "decision": decision,
            },
        )
        return None

    tools = get_negotiator_tools()

    return LlmAgent(
        name="negotiator",
        model=model,
        instruction=_instruction_provider,
        tools=tools,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )
