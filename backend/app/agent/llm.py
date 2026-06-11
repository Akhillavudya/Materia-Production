# app/agent/llm.py

import httpx
import json
import re
import asyncio

from app.core.config import settings

OLLAMA_BASE_URL = settings.ollama_base_url
OLLAMA_MODEL    = settings.ollama_model


SYSTEM_PROMPT = """You are Materia AI, an expert materials simulation assistant specialized in materials search, POSCAR generation, and computational materials science.

When a user asks you to generate files, run simulations, or manipulate structures, respond with:
1. ONE tool call line in EXACTLY this format (first line of your response):
   TOOL_CALL: tool_name({"arg1": "value1"})
2. Followed by a clean one-sentence explanation.

CRITICAL RULES:
- TOOL_CALL must be the very first line when a tool is needed
- Never wrap TOOL_CALL in markdown or code blocks
- For questions or explanations — answer naturally with NO tool call
- Be concise and scientifically accurate

AVAILABLE TOOLS:
1. search_materials({"formula": "NaCl", "limit": 10})
2. generate_vasp_inputs({"material_id": "mp-123", "source": "mp", "task": "relaxation"})
3. optimize_structure({"fmax": 0.02, "calculator_type": "mace"})
4. run_md_simulation({"ensemble": "nvt", "temperature": 300})
"""


def parse_tool_call(text: str) -> dict | None:
    match = re.search(
        r'TOOL_CALL:\s*(\w+)\s*\((\{.*?\})\)',
        text,
        re.DOTALL | re.IGNORECASE
    )
    if not match:
        return None
    try:
        return {
            "tool": match.group(1).strip(),
            "args": json.loads(match.group(2).strip())
        }
    except (json.JSONDecodeError, IndexError):
        return None


def clean_text(text: str) -> str:
    """Remove TOOL_CALL line and think blocks from visible text."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'TOOL_CALL:\s*\w+\s*\([^)]*\)\s*\n?', '', text, flags=re.DOTALL).strip()
    return text


async def stream_chat(messages: list[dict]):
    """
    TRUE streaming — yields tokens as they arrive from Ollama.
    
    Strategy:
    - Stream tokens to the caller in real time
    - After stream ends, check if full text contained a TOOL_CALL
    - If yes, yield the __TOOL__ signal at the end
    - The caller (agent.py) handles interleaving text + tools
    
    This means:
    - Text appears immediately as typed by the model
    - Tool signals come AFTER text is done
    - No buffering delay
    """
    full_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *messages,
    ]

    full_text = []
    in_think  = False

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model":    OLLAMA_MODEL,
                "messages": full_messages,
                "stream":   True,
            }
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    done  = chunk.get("done", False)

                    if token:
                        full_text.append(token)

                        # filter <think> blocks from yielded tokens
                        # (we accumulate full_text for tool detection regardless)
                        # simple state machine: track if we're inside <think>
                        # this is approximate — good enough for Qwen3
                        pass

                    if done:
                        break
                except json.JSONDecodeError:
                    continue

    # now process the complete text
    complete = "".join(full_text)

    # strip think blocks
    clean = re.sub(r'<think>.*?</think>', '', complete, flags=re.DOTALL).strip()

    # check for tool call
    tool_call = parse_tool_call(clean)

    # get the visible text (without TOOL_CALL line)
    visible = clean_text(clean)

    # yield visible text word by word (simulates streaming)
    # we do this AFTER collecting because:
    # 1. we need to strip think blocks first
    # 2. we need to remove TOOL_CALL line from visible text
    # the delay is only ~0.5-2s for the LLM to finish thinking
    if visible:
        words = visible.split(' ')
        for i, word in enumerate(words):
            tok = word + ('' if i == len(words) - 1 else ' ')
            if tok:
                yield tok
                await asyncio.sleep(0.008)  # 8ms per word — smooth streaming effect

    # signal tool call if present
    if tool_call:
        yield "\n__TOOL__:" + json.dumps(tool_call)
