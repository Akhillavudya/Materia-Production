"""Ollama provider — native tool calling for offline/local development.

Fallback backend (e.g. `qwen3`, which supports native tools). Same neutral
interface as the Gemini provider; no regex/JSON-from-prose extraction.
"""

from __future__ import annotations

import json
import uuid

from ollama import AsyncClient

from app.agent.providers.base import LLMProvider, LLMResult, OnText, ToolCall, ToolSpec
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Offline-only tool-routing primer ──────────────────────────────────────────
# Injected ONLY by this provider (never in graph.py's shared SYSTEM_PROMPT, which
# gives Gemini 100% and must stay untouched). qwen3:14b — the offline fallback —
# under-calls tools and anchors on a couple of them (T4: 41% vs Gemini 100%). This
# compact map is written in terms of tool *semantics*, not the benchmark prompts,
# so it generalises. Kept short because the 14B model has limited attention budget.
_OFFLINE_TOOL_PRIMER = """\
TOOL-USE RULES (follow exactly):
- If the user asks for a concrete ACTION, you MUST call the single best-matching \
tool — never answer such a request in prose. Only skip calling a tool when the \
request is genuinely ambiguous, out of scope, or a purely conceptual question.
- If the user names a material by CHEMICAL FORMULA (e.g. NaCl) that isn't already \
loaded, call search_materials FIRST. If they give a Materials Project id (e.g. \
mp-149) go straight to the generate/compute tool.
- Always fill EVERY required argument from the tool's schema (formula, material_id, \
scaling, axis, thickness, miller, accuracy_level, calculator_type, ...). Never emit \
a tool call with a required argument left null.
- Pick the tool by intent — do NOT default to generate_sqs or compute_neb:
  find/search materials, or resolve a formula -> search_materials
  full VASP inputs (INCAR+KPOINTS+POSCAR) for a known id -> generate_vasp_inputs
  only a POSCAR -> generate_poscar ; only a KPOINTS file -> generate_kpoints
  supercell -> make_supercell ; add vacuum -> add_vacuum ; surface slab -> make_slab
  put a molecule on a slab -> add_adsorbate
  vacancy -> create_vacancy ; substitute an element -> create_substitution ; \
interstitial -> create_interstitial
  space group / symmetry -> analyze_symmetry ; change file format -> convert_structure
  relax / optimize / minimise -> optimize_structure
  molecular dynamics / NVT / NPT -> run_md_simulation
  elastic tensor / moduli -> compute_elastic_tensor
  phonon band structure / DOS -> compute_phonons
  ion migration barrier (NEB) -> compute_neb
  random alloy / disordered solid solution (SQS) -> generate_sqs
  which ML potentials are available -> list_models
"""


def _with_offline_primer(messages: list[dict]) -> list[dict]:
    """Append the routing primer to the system message (or add one if absent).

    Provider-scoped: the shared SYSTEM_PROMPT is never edited — we only augment the
    copy this provider sends to Ollama, so Gemini is completely unaffected.
    """
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            m["content"] = f"{(m.get('content') or '').rstrip()}\n\n{_OFFLINE_TOOL_PRIMER}"
            return out
    return [{"role": "system", "content": _OFFLINE_TOOL_PRIMER}, *out]


def _to_messages(messages: list[dict]) -> list[dict]:
    """Translate the neutral conversation into Ollama chat messages."""
    out: list[dict] = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        if role in ("system", "user"):
            out.append({"role": role, "content": content or ""})
            continue

        if role == "assistant":
            entry: dict = {"role": "assistant", "content": content or ""}
            tcs = msg.get("tool_calls", [])
            if tcs:
                entry["tool_calls"] = [
                    {"function": {"name": tc.name, "arguments": tc.args or {}}}
                    for tc in tcs
                ]
            out.append(entry)
            continue

        if role == "tool":
            payload = content if isinstance(content, str) else json.dumps(content)
            out.append({
                "role": "tool",
                "content": payload,
                "tool_name": msg.get("name", "tool"),
            })
            continue

    return out


def _to_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or settings.ollama_model
        self.host = host or settings.ollama_base_url

    async def run(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        on_text: OnText,
    ) -> LLMResult:
        client = AsyncClient(host=self.host)

        text_acc: list[str] = []
        tool_calls: list[ToolCall] = []

        # `think=False` disables qwen3's chain-of-thought. Left on, the model
        # spends the whole turn "thinking" and returns prose with no tool call —
        # the exact silent no-op that hit Gemini (fixed there with a 0 thinking
        # budget). Without this the agent never calls a tool on the offline path.
        # temperature=0 → greedy decoding. qwen3's default (0.8) injects randomness
        # that shows up as erratic tool-selection (anchoring on generate_sqs / NEB);
        # for single-turn tool routing we want the most likely tool, deterministically.
        async for chunk in await client.chat(
            model=self.model,
            messages=_to_messages(_with_offline_primer(messages)),
            tools=_to_tools(tools) if tools else None,
            think=False,
            options={"temperature": 0.0, "num_ctx": 16384},
            stream=True,
        ):
            message = chunk.get("message") if isinstance(chunk, dict) else chunk.message
            if message is None:
                continue

            token = (message.get("content") if isinstance(message, dict)
                     else message.content) or ""
            if token:
                text_acc.append(token)
                await on_text(token)

            tcs = (message.get("tool_calls") if isinstance(message, dict)
                   else getattr(message, "tool_calls", None)) or []
            for tc in tcs:
                fn = tc["function"] if isinstance(tc, dict) else tc.function
                name = fn["name"] if isinstance(fn, dict) else fn.name
                args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=uuid.uuid4().hex, name=name, args=dict(args or {})))

        return LLMResult(text="".join(text_acc), tool_calls=tool_calls)
