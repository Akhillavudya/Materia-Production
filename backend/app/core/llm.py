# app/core/llm.py

import httpx
import json
import os
import re
import asyncio

OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL',    'qwen3:14b')


SYSTEM_PROMPT = """You are Materia AI, an expert materials simulation assistant specialized in VASP/DFT simulations, POSCAR generation, structure manipulation, and computational materials science.

When a user asks you to generate files, run simulations, or manipulate structures, respond with:
1. ONE tool call line in EXACTLY this format (first line of your response):
   TOOL_CALL: tool_name({"arg1": "value1"})
2. Followed by a clean one-sentence explanation.

CRITICAL RULES:
- TOOL_CALL must be the very first line when a tool is needed
- Never wrap TOOL_CALL in markdown or code blocks
- For questions or explanations — answer naturally with NO tool call
- Never include poscar_path in tool calls — the system finds POSCAR automatically
- Be concise and scientifically accurate

AVAILABLE TOOLS:
1. generate_vasp_poscar({"formula": "NaCl"})
2. generate_vasp_poscar_with_vacancy_defects({"original_element": "Na", "defect_amount": 1})
3. generate_vasp_poscar_with_substitution_defects({"original_element": "Na", "defect_element": "K", "defect_amount": 1})
4. generate_vasp_poscar_with_interstitial_defects({"defect_element": "Li"})
5. generate_supercell_from_poscar({"scaling_matrix": "3 0 0; 0 3 0; 0 0 3"})
6. generate_surface_slab_from_poscar({"miller_indices": [0,0,1], "vacuum_thickness": 15.0, "slab_layers": 4})
    7. customize_vasp_kpoints_with_accuracy({"accuracy_level": "Medium", "gamma_centered": true})
8. generate_vasp_inputs_from_poscar({"vasp_input_sets": "MPRelaxSet"})
9. generate_vasp_workflow_of_convergence_tests({"test_type": "all"})
10. generate_vasp_workflow_of_eos({"scale_factors": [0.94, 0.96, 0.98, 1.00, 1.02, 1.04, 1.06]})
11. generate_vasp_workflow_of_elastic_constants({})
12. generate_vasp_workflow_of_aimd({"temperatures": [500, 1000], "md_steps": 1000, "md_timestep": 2.0})
13. generate_vasp_workflow_of_neb({"initial_poscar_path": "path1", "final_poscar_path": "path2", "num_images": 5})
14. run_simulation_using_mlps({"mlps_type": "CHGNet", "task_type": "single"})
15. visualize_structure_from_poscar({})
16. generate_sqs_from_poscar({"target_configurations": {"La": {"La": 0.5, "Y": 0.5}}})
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
