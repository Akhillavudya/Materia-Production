"""T4 — Agent reliability (docs/VALIDATION_PLAN.md §5).

Measures the natural-language → correct-tool mapping that neither reference paper
(Masgent / ChatMat) rigorously benchmarks, broken down per free hosted provider
(Groq, Gemini). Ollama is the user-side offline option and is NOT benchmarked.

For each (provider, prompt) we run ONE agent turn with the real production
SYSTEM_PROMPT + TOOL_SPECS and inspect the FIRST tool the model calls. Nothing is
executed — no jobs are spawned — so this is cheap and side-effect-free.

Metrics per provider:
  * tool-selection accuracy  — first tool matches an expected tool (or correctly
                               calls no tool for ambiguous / out-of-scope / conceptual)
  * argument accuracy        — for correctly-selected tools with expected args,
                               fraction of cases whose key args all match
  * per-category breakdown   — single / multi / compute / structure / ambiguous /
                               out_of_scope / conceptual

Pilot (default):   ../venv/bin/python scripts/validation/t4_agent_reliability.py \
                       --providers gemini --ids S1,S4,S11,A1,O1,C1
Full run:          ../venv/bin/python scripts/validation/t4_agent_reliability.py \
                       --providers groq,gemini

Run from backend/. Reads keys from backend/.env via app.core.config (Groq +
Gemini). Emits CSV + a markdown table to docs/validation_results/T4_*.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from t4_prompt_suite import SUITE  # noqa: E402


# ── provider construction (each tested in ISOLATION, no fallback wrapper) ──────

# Env var the provider reads its key from, at run() time.
KEY_ENV = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}


def build_provider(name: str):
    if name == "groq":
        from app.agent.providers.groq import GroqProvider
        return GroqProvider(max_retries=0)  # fail fast on 429 → rotate keys ourselves
    if name == "gemini":
        from app.agent.providers.gemini import GeminiProvider
        return GeminiProvider()
    if name == "ollama":
        from app.agent.providers.ollama import OllamaProvider
        return OllamaProvider()
    raise SystemExit(f"unknown provider {name!r} (use groq | gemini | ollama)")


def load_keys(name: str) -> list[str]:
    """Keys for a provider: GROQ_API_KEYS / GEMINI_API_KEYS (comma list) ∪ the
    single GROQ_API_KEY / GEMINI_API_KEY. De-duplicated, order preserved, so we
    can rotate across several free accounts as each hits its rate limit."""
    plural = os.getenv(f"{name.upper()}_API_KEYS", "")
    single = os.getenv(KEY_ENV[name], "")
    keys, seen = [], set()
    for k in [*plural.split(","), single]:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def _is_rate_limit(err: str) -> bool:
    e = err.lower()
    return any(s in e for s in ("429", "rate limit", "quota", "resource_exhausted",
                                "too many requests", "rate_limit"))


# ── grading helpers ───────────────────────────────────────────────────────────

def _match(expected, actual) -> bool:
    """Case-insensitive / numeric-tolerant match; lists = acceptable variants."""
    if actual is None:
        return False
    if isinstance(expected, (list, tuple)):
        return any(_match(e, actual) for e in expected)
    se, sa = str(expected).strip().lower(), str(actual).strip().lower()
    try:
        return abs(float(se) - float(sa)) < 1e-6
    except ValueError:
        pass
    return se in sa or sa in se


def grade(case: dict, first_tool: str | None, first_args: dict) -> dict:
    expected = case["expected_tools"]
    wants_none = expected == ["NONE"] or "NONE" in expected

    if first_tool is None:
        tool_ok = wants_none
    else:
        tool_ok = first_tool in expected

    # Argument grading: only meaningful when the right tool was actually chosen.
    arg_ok: bool | None = None
    arg_detail = ""
    exp_args = case.get("expected_args")
    if tool_ok and first_tool not in (None,) and exp_args:
        results = {k: _match(v, first_args.get(k)) for k, v in exp_args.items()}
        arg_ok = all(results.values())
        arg_detail = "; ".join(
            f"{k}={'ok' if ok else f'BAD({first_args.get(k)!r})'}"
            for k, ok in results.items())

    success = tool_ok and (arg_ok is not False)
    return {"tool_ok": tool_ok, "arg_ok": arg_ok,
            "arg_detail": arg_detail, "success": success}


# ── one turn (with key rotation) ───────────────────────────────────────────────

class AllKeysRateLimited(Exception):
    """Every available key returned a rate-limit error for one case."""


async def run_case(provider, name: str, keys: list[str], state: dict,
                   system_prompt: str, tool_specs, case: dict) -> dict:
    messages = [{"role": "system", "content": system_prompt}]
    messages += case.get("context", [])
    messages.append({"role": "user", "content": case["prompt"]})

    async def _noop(_delta: str) -> None:  # discard streamed text
        return None

    key_var = KEY_ENV[name]
    t0 = time.time()
    err = None
    first_tool: str | None = None
    first_args: dict = {}
    all_tools: list[str] = []
    rotations = 0

    # Try the current key; on a rate-limit, advance to the next account's key and
    # retry the SAME case. A non-rate-limit error (e.g. bad function-call format)
    # is a REAL result — record it, don't rotate. If every key is rate-limited for
    # this case, the whole provider run is out of quota → raise to stop early.
    for _ in range(len(keys)):
        os.environ[key_var] = keys[state["idx"]]
        try:
            result = await provider.run(messages, tool_specs, _noop)
            all_tools = [tc.name for tc in result.tool_calls]
            if result.tool_calls:
                first_tool = result.tool_calls[0].name
                first_args = dict(result.tool_calls[0].args or {})
            err = None
            break
        except Exception as e:  # noqa: BLE001
            err = str(e)
            if _is_rate_limit(err):
                state["idx"] = (state["idx"] + 1) % len(keys)
                rotations += 1
                continue
            break  # genuine non-quota result — keep it
    else:
        raise AllKeysRateLimited(
            f"all {len(keys)} {name} keys rate-limited at case {case['id']}")

    latency = time.time() - t0
    g = grade(case, first_tool, first_args)
    return {
        "id": case["id"], "category": case["category"], "prompt": case["prompt"],
        "expected_tools": "|".join(case["expected_tools"]),
        "first_tool": first_tool or ("(none)" if not err else "(ERROR)"),
        "all_tools": ",".join(all_tools),
        "tool_ok": g["tool_ok"], "arg_ok": g["arg_ok"],
        "arg_detail": g["arg_detail"], "success": g["success"],
        "latency_s": round(latency, 2), "key_idx": state["idx"],
        "rotations": rotations, "error": err or "",
    }


async def run_provider(name: str, cases: list[dict]) -> list[dict]:
    from app.agent.graph import SYSTEM_PROMPT
    from app.agent.tool_schemas import TOOL_SPECS

    keys = load_keys(name)
    if not keys:
        print(f"\n=== provider: {name} — NO KEYS (set {name.upper()}_API_KEYS); skipping ===")
        return []

    provider = build_provider(name)
    state = {"idx": 0}
    print(f"\n=== provider: {name} ({getattr(provider, 'name', name)}) — "
          f"{len(keys)} key(s) ===")
    rows = []
    # When every key is momentarily 429 it is usually a PER-MINUTE limit that
    # resets shortly — sleep and resume rather than abandoning the run. A hard
    # daily-token cap (Groq) will burn through the waits and then stop cleanly.
    MAX_WAITS, WAIT_S = 6, 65
    for case in cases:
        waits = 0
        while True:
            try:
                row = await run_case(provider, name, keys, state,
                                     SYSTEM_PROMPT, TOOL_SPECS, case)
                break
            except AllKeysRateLimited as e:
                waits += 1
                if waits > MAX_WAITS:
                    print(f"  ⛔ {e}; still limited after {MAX_WAITS} waits — "
                          f"stopping {name} ({len(rows)}/{len(cases)} done).")
                    return rows
                print(f"  ⏳ all {len(keys)} {name} keys 429 at {case['id']}; "
                      f"waiting {WAIT_S}s for per-minute reset "
                      f"(wait {waits}/{MAX_WAITS})…")
                await asyncio.sleep(WAIT_S)
        row["provider"] = name
        flag = "✓" if row["success"] else "✗"
        argbit = "" if row["arg_ok"] is None else (" arg:" + ("ok" if row["arg_ok"] else "BAD"))
        rot = f" rot{row['rotations']}" if row["rotations"] else ""
        print(f"  {flag} [{row['id']}] {name}: {row['first_tool']:<22} "
              f"(want {row['expected_tools']}){argbit}  {row['latency_s']}s"
              f"  key#{row['key_idx']}{rot}"
              + (f"  ERR={row['error'][:70]}" if row["error"] else ""))
        rows.append(row)
    return rows


# ── reporting ─────────────────────────────────────────────────────────────────

CATEGORIES = ["single", "multi", "structure", "compute",
              "ambiguous", "out_of_scope", "conceptual"]


def _agg(rows: list[dict], key="tool_ok") -> tuple[int, int]:
    ok = sum(1 for r in rows if r[key])
    return ok, len(rows)


def write_outputs(rows: list[dict], providers: list[str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = ["provider", "id", "category", "prompt", "expected_tools",
            "first_tool", "all_tools", "tool_ok", "arg_ok", "arg_detail",
            "success", "latency_s", "error"]
    csv_path = out_dir / "T4_agent_reliability.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    md = [
        "# T4 — Agent reliability (results)",
        "",
        f"**Date:** {date.today().isoformat()} · **Plan:** `docs/VALIDATION_PLAN.md` §5",
        "**Harness:** `backend/scripts/validation/t4_agent_reliability.py` · "
        "**Suite:** `backend/scripts/validation/t4_prompt_suite.py`",
        f"**Providers:** {', '.join(providers)} (free hosted stack; Ollama is the "
        "user-side offline option, not benchmarked) · "
        f"**Cases:** {len(rows) // max(len(providers), 1)}",
        "",
        "Each case = one agent turn with the production `SYSTEM_PROMPT` + 23 tool "
        "schemas; we grade the **first** tool the model calls (nothing is executed, "
        "no jobs spawned). Tool-selection = right tool chosen (or correctly no tool "
        "for ambiguous/out-of-scope/conceptual). Argument accuracy = of correctly-"
        "selected tool calls with expected args, the fraction whose key args all match.",
        "",
        "## Aggregate per provider",
        "",
        "| Provider | Tool-selection | Argument accuracy | Mean latency (s) |",
        "|----------|----------------|-------------------|------------------|",
    ]
    for p in providers:
        pr = [r for r in rows if r["provider"] == p]
        if not pr:
            continue
        t_ok, t_n = _agg(pr, "tool_ok")
        arg_rows = [r for r in pr if r["arg_ok"] is not None]
        a_ok = sum(1 for r in arg_rows if r["arg_ok"])
        a_n = len(arg_rows)
        lat = sum(r["latency_s"] for r in pr) / len(pr)
        t_pct = f"{100*t_ok/t_n:.0f}%" if t_n else "—"
        a_pct = f"{a_ok}/{a_n} ({100*a_ok/a_n:.0f}%)" if a_n else "—"
        md.append(f"| {p} | {t_ok}/{t_n} ({t_pct}) | {a_pct} | {lat:.2f} |")

    md += ["", "## Tool-selection by category", "",
           "| Category | " + " | ".join(providers) + " |",
           "|----------|" + "|".join(["------"] * len(providers)) + "|"]
    for cat in CATEGORIES:
        cells = []
        for p in providers:
            cr = [r for r in rows if r["provider"] == p and r["category"] == cat]
            if not cr:
                cells.append("—")
                continue
            ok, n = _agg(cr, "tool_ok")
            cells.append(f"{ok}/{n}")
        if any(c != "—" for c in cells):
            md.append(f"| {cat} | " + " | ".join(cells) + " |")

    # Failure list
    fails = [r for r in rows if not r["success"]]
    md += ["", "## Failures (tool or argument)", ""]
    if not fails:
        md.append("None — every case passed. 🎉")
    else:
        md.append("| Provider | id | Prompt | Expected | Got (first tool) | Why |")
        md.append("|----------|----|--------|----------|------------------|-----|")
        for r in fails:
            if not r["tool_ok"]:
                why = "wrong tool" if r["first_tool"] not in ("(none)", "(ERROR)") \
                    else ("provider error" if r["error"] else "called no tool")
            else:
                why = f"bad args: {r['arg_detail']}"
            prompt = r["prompt"] if len(r["prompt"]) < 60 else r["prompt"][:57] + "…"
            md.append(f"| {r['provider']} | {r['id']} | {prompt} | "
                      f"{r['expected_tools']} | {r['first_tool']} | {why} |")

    md += ["", "**Notes.** Multi-tool prompts grade the correct *first* tool (the "
           "search-before-generate decision); the plan→confirm gate then sequences "
           "the rest. Ambiguous/out-of-scope/conceptual cases pass when the agent "
           "correctly calls no tool (asks/clarifies/answers directly). Argument "
           "matching is case-insensitive substring / numeric-equal.", ""]

    md_path = out_dir / "T4_agent_reliability.md"
    md_path.write_text("\n".join(md) + "\n")
    print(f"\nwrote {csv_path}\nwrote {md_path}")
    for p in providers:
        pr = [r for r in rows if r["provider"] == p]
        if pr:
            t_ok, t_n = _agg(pr, "tool_ok")
            pct = f"{100*t_ok/t_n:.0f}%" if t_n else "—"
            print(f"  {p}: tool-selection {t_ok}/{t_n} ({pct})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="groq,gemini",
                    help="comma list: groq,gemini (ollama is user-side, not benchmarked)")
    ap.add_argument("--ids", default="", help="comma list of case ids (pilot subset)")
    ap.add_argument("--out", default=str(_BACKEND.parent / "docs" / "validation_results"))
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    cases = SUITE
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        cases = [c for c in SUITE if c["id"] in want]
        if not cases:
            raise SystemExit(f"no cases matched ids {sorted(want)}")

    print(f"T4 run — providers={providers} cases={len(cases)}")
    all_rows: list[dict] = []
    for name in providers:
        all_rows += asyncio.run(run_provider(name, cases))

    write_outputs(all_rows, providers, Path(args.out))


if __name__ == "__main__":
    main()
