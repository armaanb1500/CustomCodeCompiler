"""Tests for three-address code generation.

Besides checking the instructions, these tests run the TAC with a small
interpreter (tac_interpreter.py) and compare its output with the generated Python's.
If both back ends print the same thing, the TAC means the same as the program.
"""

import contextlib
import io
from pathlib import Path

import pytest

from flowlang.codegen import generate
from flowlang.lexer import tokenize
from flowlang.main import main
from flowlang.parser import parse
from flowlang.semantic import analyze
from flowlang.tac import Quad, format_quadruples, format_tac, generate_tac
from tac_interpreter import run_tac

EXAMPLES = Path(__file__).parent.parent / "examples"


def tac_units(body):
    program = parse(tokenize(f"program Test {{\n{body}\n}}"))
    return generate_tac(program, analyze(program))


def main_lines(body):
    """The main program's TAC instructions as text."""
    return [str(quad) for quad in tac_units(body)[-1].code]


def run_python(source):
    program = parse(tokenize(source))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(generate(program, analyze(program)), {"__name__": "__main__"})
    return output.getvalue().splitlines()


# ---- Instructions -----------------------------------------------------------


def test_expression_is_split_into_temporaries():
    assert main_lines("let score: int = 2 + 3 * 4;") == [
        "t1 = 3 * 4",
        "t2 = 2 + t1",
        "score = t2",
    ]


def test_quadruple_fields():
    quad = tac_units("let x: int = 2 + 3;")[-1].code[0]
    assert quad == Quad("+", "2", "3", "t1")


def test_if_else_uses_labels_and_jumps():
    assert main_lines('let x: int = 1;\nif x > 0 { emit "pos"; } else { emit "neg"; }') == [
        "x = 1",
        "t1 = x > 0",
        "ifFalse t1 goto L1",
        'emit "pos"',
        "goto L2",
        "L1:",
        'emit "neg"',
        "L2:",
    ]


def test_if_without_else():
    assert main_lines("if true { emit 1; }") == ["ifFalse true goto L1", "emit 1", "L1:"]


def test_repeat_becomes_a_counting_loop():
    assert main_lines('repeat 3 { emit "hi"; }') == [
        "t1 = 0",
        "L1:",
        "t2 = t1 < 3",
        "ifFalse t2 goto L2",
        'emit "hi"',
        "t1 = t1 + 1",
        "goto L1",
        "L2:",
    ]


def test_and_short_circuits():
    assert main_lines("let a: bool = true;\nlet b: bool = false;\nemit a && b;") == [
        "a = true",
        "b = false",
        "t1 = a",
        "ifFalse t1 goto L1",
        "t1 = b",
        "L1:",
        "emit t1",
    ]


def test_or_short_circuits():
    assert "if t1 goto L1" in main_lines("let a: bool = true;\nemit a || false;")


def test_calls_pass_params_first():
    lines = main_lines("fn add(a: int, b: int) -> int { return a + b; }\nemit add(1, 2);")
    assert lines == ["param 1", "param 2", "t2 = call add, 2", "emit t2"]


def test_call_statement_and_trigger_have_no_result():
    assert main_lines('call turn_on("fan");') == ['param "fan"', "call turn_on, 1"]
    assert main_lines("event e { }\ntrigger e;") == ["call e, 0"]


def test_int_to_float_conversion():
    assert main_lines("let y: float = 2;") == ["y = 2.0"]
    assert main_lines("let n: int = 2;\nlet y: float = n;") == ["n = 2", "t1 = inttofloat n", "y = t1"]


def test_unary_operators():
    assert main_lines("let x: int = 1;\nemit -x;") == ["x = 1", "t1 = -x", "emit t1"]


def test_functions_and_events_come_before_main():
    units = tac_units("event e { }\nfn f() { }")
    assert [(unit.kind, unit.name) for unit in units] == [("event", "e"), ("func", "f"), ("main", "Test")]


# ---- Display ----------------------------------------------------------------


def test_format_tac():
    text = format_tac(tac_units("fn double(n: int) -> int { return n * 2; }"))
    assert text == "func double(n):\n    t1 = n * 2\n    return t1\n\nmain Test:"


def test_format_quadruples():
    text = format_quadruples(tac_units("let x: int = 2 + 3;"))
    assert text.splitlines() == [
        "main Test:",
        "    #  op  arg1  arg2  result",
        "    0  +   2     3     t1",
        "    1  =   t1          x",
    ]


# ---- The TAC means the same as the program ----------------------------------


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.flow")), ids=lambda p: p.name)
def test_tac_and_python_print_the_same_output(path):
    source = path.read_text()
    program = parse(tokenize(source))
    assert run_tac(generate_tac(program, analyze(program))) == run_python(source)


@pytest.mark.parametrize("body", [
    "emit 2 + 3 * 4;\nemit 10 - 4 - 3;\nemit 2 ^ 3 ^ 2;\nemit 7 / 2;\nemit 7.0 / 2;",
    "fn fact(n: int) -> int { if n <= 1 { return 1; } else { return n * fact(n - 1); } }\nemit fact(6);",
    "let c: int = 0;\nevent tick { c = c + 1; }\nrepeat 4 { trigger tick; }\nemit c;",
    "fn grade(n: int) -> string { if n >= 90 { return \"A\"; } else if n >= 50 { return \"B\"; } else { return \"C\"; } }\nemit grade(95);\nemit grade(60);\nemit grade(5);",
    "let y: float = 3;\nemit y;\nemit true && !false;\nemit false || 1 > 2;",
])
def test_tac_and_python_agree_on_small_programs(body):
    source = f"program Test {{\n{body}\n}}"
    program = parse(tokenize(source))
    assert run_tac(generate_tac(program, analyze(program))) == run_python(source)


# ---- Command line -----------------------------------------------------------


def test_tac_flag(capsys):
    assert main([str(EXAMPLES / "billing.flow"), "--tac"]) == 0
    output = capsys.readouterr().out
    assert "func calculate_total(price, tax):" in output
    assert "t1 = price * tax" in output


def test_quads_flag(capsys):
    assert main([str(EXAMPLES / "billing.flow"), "--quads"]) == 0
    assert "#   op" in capsys.readouterr().out
