# FlowLang: notes for Claude

## What this is
A Compiler Design course project: a compiler from FlowLang (`.flow`) to Python 3.
The owner is an intermediate Python coder and will present it in a project review,
so they must understand and be able to explain every piece, not just have it work.

**Deadline: Friday 2026-10-16, around 08:00.** Plan: Stages 1–2 on Wed 10-14,
Stages 3–4 on Thu 10-15, Stage 5 Thu evening. Friday morning is buffer only.
If behind, drop extras (else-if, warnings, `--symbols`) before core phases.

## How to work here
- Build stage by stage (roadmap in README.md). One stage per session works best.
- Explain the concept behind each change in plain language, and connect it to the
  textbook term the examiner will use (DFA, LL(1), left factoring, symbol table, ...).
- `docs/language.md` is the source of truth for syntax and semantics. If the language
  changes, update it first.
- After each stage: update the README roadmap, append to `docs/learning-log.md`, and
  end with a small hands-on exercise. Let the owner make the git commits.

## Rules
- The lexer and parser are hand-written. No parser generators (PLY, Lark, ANTLR, ...).
  Standard library only; pytest is the one dev dependency.
- Keep the pipeline layering: `lexer -> parser -> semantic -> codegen`, with `tac`
  as a second consumer of the annotated AST, and `optimizer` as an optional pass on the TAC. Each phase only consumes the previous
  phase's output; `main.py` wires them together.
- Every compiler error carries a line and column number.
- Plain, readable code over clever code. Small functions with docstrings.

## Running things
- Python: `.venv/bin/python` (3.14).
- Tests: `.venv/bin/python -m pytest`
- Compiler: `.venv/bin/python -m flowlang examples/smart_home.flow`
