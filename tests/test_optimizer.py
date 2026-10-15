"""Tests for the TAC optimiser.

The most important check: optimised TAC prints exactly the same output as the
original TAC (run with tac_interpreter.py). An optimisation must never change
what a program does.
"""

from pathlib import Path

import pytest

from flowlang.lexer import tokenize
from flowlang.main import main
from flowlang.optimizer import evaluate, format_report, optimize
from flowlang.parser import parse
from flowlang.semantic import analyze
from flowlang.tac import generate_tac
from tac_interpreter import run_tac

EXAMPLES = Path(__file__).parent.parent / "examples"


def units_for(source):
    program = parse(tokenize(source))
    return generate_tac(program, analyze(program))


def optimized_main(body):
    """The optimised main program's TAC as text lines."""
    units, _ = optimize(units_for(f"program Test {{\n{body}\n}}"))
    return [str(quad) for quad in units[-1].code]


# ---- Constant folding and propagation ---------------------------------------


def test_constant_expression_is_folded():
    assert optimized_main("let score: int = 2 + 3 * 4;") == ["score = 14"]


@pytest.mark.parametrize("expression, expected", [
    ("7 / 2", "3"),
    ("7.0 / 2", "3.5"),
    ("2 ^ 10", "1024"),
    ("2 ^ -1", "0"),
    ("10 % 3", "1"),
    ("-(4 - 6)", "2"),
    ('"Hello, " + "world"', '"Hello, world"'),
    ("1 < 2 && !false", "true"),
])
def test_folding_follows_flowlang_rules(expression, expected):
    assert optimized_main(f"emit {expression};") == [f"emit {expected}"]


def test_division_by_zero_is_not_folded():
    # The compiler must not crash; the error is left for run time.
    assert optimized_main("emit 1 / 0;") == ["t1 = 1 / 0", "emit t1"]


def test_huge_powers_are_not_folded():
    assert evaluate("^", 2, 1000) is None


def test_known_variable_values_are_propagated():
    assert optimized_main("let x: int = 5;\nlet y: int = x * 2;\nemit y + 1;") == [
        "x = 5",
        "y = 10",
        "emit 11",
    ]


def test_values_are_forgotten_after_a_call():
    # The event changes c, so `emit c` must not become `emit 0`.
    lines = optimized_main("let c: int = 0;\nevent tick { c = c + 1; }\ntrigger tick;\nemit c;")
    assert lines == ["c = 0", "call tick, 0", "emit c"]


def test_values_are_forgotten_at_labels():
    # After the if, x could be 1 or 2, so the emit must keep reading x.
    body = "let x: int = 1;\nlet go: bool = 3 > 2;\nevent e { }\ntrigger e;\nif go { x = 2; }\nemit x;"
    assert optimized_main(body)[-1] == "emit x"


# ---- Jumps and dead code ------------------------------------------------------


def test_constant_condition_removes_the_dead_branch():
    assert optimized_main('if 1 > 2 { emit "no"; } else { emit "yes"; }') == ['emit "yes"']


def test_always_true_condition_keeps_only_the_then_branch():
    assert optimized_main('if true { emit "yes"; } else { emit "no"; }') == ['emit "yes"']


def test_unreachable_code_after_return_is_removed():
    units, report = optimize(units_for((EXAMPLES / "billing.flow").read_text()))
    category = next(unit for unit in units if unit.name == "category")
    assert [str(quad) for quad in category.code] == [
        "t4 = amount > 5000.0",
        "ifFalse t4 goto L1",
        'return "Premium"',
        "L1:",
        "t5 = amount > 1000.0",
        "ifFalse t5 goto L3",
        'return "Standard"',
        "L3:",
        'return "Basic"',
    ]
    assert report.counts["unreachable"] == 2


def test_loops_stay_loops():
    lines = optimized_main('repeat 3 { emit "hi"; }')
    assert "goto L1" in lines
    assert "t1 = t1 + 1" in lines


def test_program_variables_are_never_removed():
    # Only compiler temporaries are deleted; x might be read by another unit.
    assert optimized_main("let x: int = 1;") == ["x = 1"]


def test_temporaries_do_not_clash_with_program_names():
    units = units_for("program T {\nlet t1: int = 2;\nemit t1 + 3;\n}")
    assert [str(quad) for quad in units[-1].code] == ["t1 = 2", "t2 = t1 + 3", "emit t2"]
    optimized, _ = optimize(units)
    assert [str(quad) for quad in optimized[-1].code] == ["t1 = 2", "emit 5"]


# ---- The golden rule: same output ---------------------------------------------


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.flow")), ids=lambda p: p.name)
def test_optimised_examples_print_the_same_output(path):
    units = units_for(path.read_text())
    optimized, _ = optimize(units)
    assert run_tac(optimized) == run_tac(units)


@pytest.mark.parametrize("body", [
    "emit 2 + 3 * 4;\nemit 10 - 4 - 3;\nemit 2 ^ 3 ^ 2;\nemit 7 / 2;\nemit 7.0 / 2;",
    "fn fact(n: int) -> int { if n <= 1 { return 1; } else { return n * fact(n - 1); } }\nemit fact(6);",
    "let c: int = 0;\nevent tick { c = c + 1; }\nrepeat 4 { trigger tick; }\nemit c;",
    "let x: int = 1;\nif x > 0 { x = x + 10; } else { x = 0; }\nemit x;\nrepeat x - 9 { x = x * 2; }\nemit x;",
    "let y: float = 3;\nemit y;\nemit true && !false;\nemit false || 1 > 2;",
])
def test_optimised_programs_print_the_same_output(body):
    units = units_for(f"program Test {{\n{body}\n}}")
    optimized, _ = optimize(units)
    assert run_tac(optimized) == run_tac(units)


def test_original_units_are_not_changed():
    units = units_for("program T { emit 2 + 3; }")
    before = [str(quad) for quad in units[-1].code]
    optimize(units)
    assert [str(quad) for quad in units[-1].code] == before


# ---- Report and command line ----------------------------------------------------


def test_report():
    _, report = optimize(units_for("program T { emit 2 + 3; }"))
    assert (report.before, report.after) == (2, 1)
    assert format_report(report).splitlines()[0] == "Optimisation: 2 -> 1 instructions"


def test_report_when_nothing_changes():
    _, report = optimize(units_for("program T { let x: int = 1; }"))
    assert "nothing to optimise" in format_report(report)


def test_optimize_flag(capsys):
    assert main([str(EXAMPLES / "security.flow"), "--tac", "--optimize"]) == 0
    output = capsys.readouterr().out
    assert "score = 14" in output
    assert "Optimisation: 26 -> 16 instructions" in output


def test_without_optimize_flag_tac_is_unchanged(capsys):
    assert main([str(EXAMPLES / "security.flow"), "--tac"]) == 0
    output = capsys.readouterr().out
    assert "t7 = 3 * 4" in output
    assert "Optimisation" not in output


def test_short_flag_alone_shows_optimised_tac(capsys):
    assert main([str(EXAMPLES / "security.flow"), "-O"]) == 0
    assert "score = 14" in capsys.readouterr().out


def test_optimize_with_quads(capsys):
    assert main([str(EXAMPLES / "security.flow"), "--quads", "-O"]) == 0
    output = capsys.readouterr().out
    assert "#   op" in output
    assert "Optimisation:" in output
