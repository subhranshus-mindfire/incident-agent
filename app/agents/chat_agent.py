"""Chat agent loop: routes a message, calls tools, and answers from their results."""

from __future__ import annotations

import json
import logging
from typing import Any

from groq import BadRequestError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.grounding import reply_problems
from app.agents.router import route_message
from app.config.config import get_settings
from app.constants.llm import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    MAX_OUTPUT_TOKENS,
    MAX_TOOL_CALL_ATTEMPTS,
    MAX_TOOL_ROUNDS,
)
from app.llms.providers import ProviderNotConfiguredError, build_chat_model, is_rate_limit_error
from app.prompts.loader import load_prompt
from app.tools.chat_tools import _TOOLS_BY_NAME, TOOLS
from app.utils.errors import error_payload

logger = logging.getLogger("incident_agent.agents.chat_agent")


CHAT_SYSTEM_PROMPT = load_prompt("chat_agent")


def _message_text(message: BaseMessage) -> str:
    """Plain text of a model reply. Gemini returns a list of content blocks; Groq returns a string."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


async def _grounded_reply(base_llm: Any, messages: list[BaseMessage], text: str) -> str:
    """The reply, if it is grounded in the tool results. Otherwise the model gets one rewrite, and if the
    rewrite is still not grounded, the reply is withheld."""
    tool_results = [str(m.content) for m in messages if isinstance(m, ToolMessage)]
    problems = reply_problems(text, tool_results)
    if not problems:
        return text

    logger.warning(f"Chat reply is not grounded in tool results: {problems}")
    if not isinstance(messages[-1], AIMessage):
        messages = messages + [AIMessage(content=text)]
    rewrite = HumanMessage(
        content=(
            f"The answer is not grounded: {'; '.join(problems)}. Rewrite it using only figures from the tool "
            "results, say what was not measured, and do not state a cause the data does not show. Do not call tools."
        )
    )
    try:
        retried = _message_text(await base_llm.ainvoke(messages + [rewrite]))
    except Exception as exc:
        logger.error(f"Grounding rewrite failed: {exc}")
        retried = ""
    if retried and not reply_problems(retried, tool_results):
        return retried
    return (
        "I could not confirm some figures in my answer against the tool results, so I am not "
        "reporting them. Ask again, or check the console."
    )


def _is_unknown_tool_error(exc: BadRequestError) -> bool:
    text = str(exc)
    return "tool_use_failed" in text or "tool call validation failed" in text


async def _invoke_model(llm: Any, messages: list[BaseMessage]) -> AIMessage:
    """Calls the model. Retries when it names a tool that does not exist, which the provider rejects."""
    for attempt in range(1, MAX_TOOL_CALL_ATTEMPTS + 1):
        try:
            response: AIMessage = await llm.ainvoke(messages)
            return response
        except BadRequestError as exc:
            if not _is_unknown_tool_error(exc) or attempt == MAX_TOOL_CALL_ATTEMPTS:
                raise
            logger.warning(f"Model called an unknown tool (attempt {attempt}); retrying: {exc}")
    raise RuntimeError("unreachable: the loop returns or raises")


def _to_messages(history: list[dict[str, str]], message: str) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]
    for item in history[-MAX_HISTORY_TURNS:]:
        if item.get("role") == "assistant":
            messages.append(AIMessage(content=item.get("content", "")[:MAX_HISTORY_CHARS]))
        else:
            messages.append(HumanMessage(content=item.get("content", "")[:MAX_HISTORY_CHARS]))
    messages.append(HumanMessage(content=message))
    return messages


async def run_chat(message: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Runs one chat turn: fixed or live answers first, otherwise the model calls tools and answers from them."""
    routed = await route_message(message)
    if routed.reply is not None:
        return {"reply": routed.reply, "incident": None}
    message = routed.text

    try:
        base_llm = build_chat_model(get_settings(), max_output_tokens=MAX_OUTPUT_TOKENS)
    except ProviderNotConfiguredError as exc:
        return {
            "reply": f"The language model is not configured: {exc}. Set it in .env and restart the app.",
            "incident": None,
        }
    llm = base_llm.bind_tools(TOOLS)

    messages = _to_messages(history, message)
    incident: dict[str, Any] | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            ai_message = await _invoke_model(llm, messages)
        except Exception as exc:
            if is_rate_limit_error(exc):
                logger.warning(f"Language model rate limit reached: {exc}")
                return {
                    "reply": "The language model's usage limit is reached. Wait a while and ask again.",
                    "incident": incident,
                }
            logger.error(f"Language model call failed: {exc}")
            return {
                "reply": "The language model could not process this request. "
                "Ask a narrower question, for example about one service or a shorter time window.",
                "incident": incident,
            }
        messages.append(ai_message)
        if not ai_message.tool_calls:
            reply = await _grounded_reply(base_llm, messages, _message_text(ai_message))
            return {"reply": reply, "incident": incident}

        for call in ai_message.tool_calls:
            tool_fn = _TOOLS_BY_NAME.get(call["name"])
            if tool_fn is None:
                result: Any = {"error": f"unknown tool {call['name']}"}
            else:
                try:
                    result = await tool_fn.ainvoke(call["args"])
                except Exception as exc:  # a bad tool call must not end the whole turn
                    logger.warning(f"Tool {call['name']} failed: {exc}")
                    result = error_payload(exc)
            if (
                call["name"] == "start_investigation"
                and isinstance(result, dict)
                and result.get("incident_id")
            ):
                incident = result
                result = {k: v for k, v in result.items() if k != "incident_id"}
            messages.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"])
            )

    # Out of tool rounds: answer from the results already gathered, without offering more tools.
    messages.append(
        HumanMessage(
            content="Stop calling tools. Answer now from the tool results above, and say what is still missing."
        )
    )
    try:
        final = await base_llm.ainvoke(messages)
    except Exception as exc:
        logger.error(f"Final answer call failed: {exc}")
        return {
            "reply": "I could not finish the analysis. Try a narrower question.",
            "incident": incident,
        }
    reply = await _grounded_reply(base_llm, messages, _message_text(final))
    return {"reply": reply, "incident": incident}
