#!/usr/bin/env python3
"""Run a private question list through the agent and print AGGREGATE results only.

The question file is local and untracked (real campaign questions are private). Format, one per line:

    id<TAB>question<TAB>optional required phrases

Required phrases are separated by `;`, and `a/b` inside one phrase means either word is accepted.
An answer "passes" when every phrase appears (case-insensitive). Lines starting with # are skipped.
Without phrases a question is only counted as answered; read the answers file to judge it yourself.

    scripts/eval_questions.py --questions questions.local.tsv --answers answers.local.md

Needs the same environment as the bot (OPENAI_API_KEY, NOTES_DIR, ...). Token counts are exact; cost
is an estimate from the --price-in / --price-out flags (USD per million tokens; cached input is
counted at the full input price, so the estimate is an upper bound).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analecta.agent import Agent  # noqa: E402
from analecta.aon import AonClient  # noqa: E402
from analecta.config import load_env_file, load_settings  # noqa: E402
from analecta.llm import make_provider  # noqa: E402
from analecta.llm.base import Message  # noqa: E402
from analecta.notes import NotesStore  # noqa: E402
from analecta.prompts import build_system_prompt  # noqa: E402


def parse_questions(text: str) -> list[tuple[str, str, list[str]]]:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        phrases = [p.strip() for p in (cols[2] if len(cols) > 2 else "").split(";") if p.strip()]
        out.append((cols[0].strip(), cols[1].strip(), phrases))
    return out


def passes(answer: str, phrases: list[str]) -> bool:
    low = answer.lower()
    return all(any(alt.strip().lower() in low for alt in p.split("/")) for p in phrases)


async def run(args: argparse.Namespace) -> int:
    load_env_file(os.environ.get("ANALECTA_ENV_FILE", ".env"))
    env = dict(os.environ)
    env.setdefault("DISCORD_TOKEN", "unused")
    env.setdefault("DISCORD_CHANNEL_ID", "0")
    if args.model:
        env["LLM_MODEL"] = args.model
    settings = load_settings(env, need_discord=False)
    questions = parse_questions(Path(args.questions).read_text(encoding="utf-8"))
    aon = AonClient(enabled=settings.aon_enabled, min_interval=settings.aon_min_interval,
                    user_agent=settings.aon_user_agent)
    agent = Agent(make_provider(settings), NotesStore(settings.notes_dir), aon, build_system_prompt,
                  settings.max_tool_turns)
    rows = []
    answers_md = [f"# Answers from model {settings.model}\n"]
    for qid, question, phrases in questions:
        try:
            res = await agent.answer([Message("user", question)])
            text, tools, usage, secs = res.text, res.tools_used, res.usage, res.seconds
            truncated = res.truncated
        except Exception as exc:  # keep going; count as a failure
            text, tools, usage, secs, truncated = f"ERROR {type(exc).__name__}", [], None, 0.0, True
        ok = (not truncated) and passes(text, phrases) if phrases else None
        rows.append((ok, truncated, tools, usage, secs))
        answers_md.append(f"## {qid}: {question}\n\ntools: {', '.join(tools) or '-'}\n\n{text}\n")
    await aon.aclose()
    if args.answers:
        Path(args.answers).write_text("\n".join(answers_md), encoding="utf-8")

    scored = [r for r in rows if r[0] is not None]
    done = [r for r in rows if not r[1]]
    toks_in = [r[3].input_tokens for r in rows if r[3]]
    toks_out = [r[3].output_tokens for r in rows if r[3]]
    cost = [(i * args.price_in + o * args.price_out) / 1e6 for i, o in zip(toks_in, toks_out)]
    print(f"model: {settings.model}")
    print(f"questions: {len(rows)}  completed: {len(done)}  failed/unfinished: {len(rows) - len(done)}")
    if scored:
        print(f"auto-scored: {sum(1 for r in scored if r[0])}/{len(scored)} passed")
    if rows:
        print(f"tool calls per question (mean): {statistics.mean(len(r[2]) for r in rows):.1f}")
        print(f"seconds per question (mean/max): {statistics.mean(r[4] for r in rows):.1f} / {max(r[4] for r in rows):.1f}")
    if toks_in:
        print(f"tokens per question (mean in/out): {statistics.mean(toks_in):.0f} / {statistics.mean(toks_out):.0f}")
        print(f"estimated cost per question: ${statistics.mean(cost):.4f}; per 250 questions: ${statistics.mean(cost) * 250:.2f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--answers", help="write full answers here (keep it untracked)")
    ap.add_argument("--model")
    ap.add_argument("--price-in", type=float, default=0.10)
    ap.add_argument("--price-out", type=float, default=0.50)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
