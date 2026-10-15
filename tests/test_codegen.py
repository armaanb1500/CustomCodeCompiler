"""Tests for code generation (Stage 4).

Most tests compile a small FlowLang program, run the generated Python, and
check what it prints: the behaviour is what matters, not the exact text.
"""

import contextlib
import io
from pathlib import Path

import pytest

from flowlang.codegen import generate
from flowlang.lexer import tokenize
from flowlang.parser import parse
from flowlang.semantic import analyze

EXAMPLES = Path(__file__).parent.parent / "examples"


def compile_source(source):
    """Run all four phases and return the generated Python code."""
    program = parse(tokenize(source))
    return generate(program, analyze(program))


def compile_body(body):
    return compile_source(f"program Test {{\n{body}\n}}")


def run(body):
    """Compile code placed inside a program, run it, and return its printed lines."""
    code = compile_body(body)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(code, {"__name__": "__main__"})
    return output.getvalue().splitlines()


# ---- Arithmetic and precedence --------------------------------------------


@pytest.mark.parametrize("expression, expected", [
    ("2 + 3 * 4", "14"),
    ("(2 + 3) * 4", "20"),
    ("10 - 4 - 3", "3"),
    ("10 - (4 - 3)", "9"),
    ("2 ^ 3 ^ 2", "512"),
    ("(2 ^ 3) ^ 2", "64"),
    ("-2 ^ 2", "-4"),
    ("2 * 3 ^ 2", "18"),
    ("7 % 3", "1"),
])
def test_arithmetic(expression, expected):
    assert run(f"emit {expression};") == [expected]


def test_int_division_is_integer_division():
    assert run("emit 7 / 2;") == ["3"]


def test_float_division_is_normal_division():
    assert run("emit 7.0 / 2;") == ["3.5"]


def test_int_power_with_negative_exponent_stays_int():
    assert run("emit 2 ^ -1;") == ["0"]
    assert run("emit 2.0 ^ -1;") == ["0.5"]


def test_comparisons_are_not_chained_like_python():
    # Python would read 1 < 2 == true as (1 < 2) and (2 == True), which is False.
    assert run("emit 1 < 2 == true;") == ["true"]
    assert "(1 < 2) == True" in compile_body("emit 1 < 2 == true;")


def test_not_gets_parentheses_inside_comparisons():
    assert "(not a) == b" in compile_body("let a: bool = true;\nlet b: bool = false;\nemit !a == b;")


def test_logic_operators():
    assert run("emit true && !false;") == ["true"]
    assert run("emit false || 1 > 2;") == ["false"]
    assert run("emit !(true && false);") == ["true"]


# ---- Values and conversions -----------------------------------------------


def test_booleans_print_in_flowlang_spelling():
    assert run("emit true;\nemit 3 > 5;") == ["true", "false"]


def test_string_concatenation():
    assert run('emit "Hello, " + "world";') == ["Hello, world"]


def test_int_widened_to_float_becomes_a_float():
    assert run("let y: float = 2;\nemit y;") == ["2.0"]
    assert run("let n: int = 3;\nlet y: float = n;\ny = n + 1;\nemit y;") == ["4.0"]


def test_int_argument_to_float_parameter_is_converted():
    assert run("fn show(x: float) { emit x; }\ncall show(5);") == ["5.0"]


# ---- Statements -----------------------------------------------------------


def test_if_elif_else():
    body = (
        "fn grade(n: int) -> string {\n"
        '  if n >= 90 { return "A"; } else if n >= 50 { return "B"; } else { return "C"; }\n'
        "}\n"
        "emit grade(95);\nemit grade(70);\nemit grade(10);"
    )
    assert run(body) == ["A", "B", "C"]
    assert "elif n >= 50:" in compile_body(body)


def test_repeat():
    assert run('repeat 3 { emit "hi"; }') == ["hi", "hi", "hi"]


def test_nested_repeat():
    assert run("let count: int = 0;\nrepeat 3 { repeat 2 { count = count + 1; } }\nemit count;") == ["6"]


def test_empty_blocks_become_pass():
    code = compile_body("event idle { }\nif true { }")
    assert "pass" in code
    assert run("event idle { }\nif true { }\ntrigger idle;") == []


def test_recursive_function():
    body = "fn fact(n: int) -> int { if n <= 1 { return 1; } else { return n * fact(n - 1); } }\nemit fact(5);"
    assert run(body) == ["120"]


def test_function_called_before_its_declaration():
    assert run("emit double(4);\nfn double(n: int) -> int { return n * 2; }") == ["8"]


def test_builtins():
    assert run('call turn_on("fan");\ncall turn_off("light");') == ["[fan switched on]", "[light switched off]"]


# ---- Events and globals ---------------------------------------------------


def test_event_updating_a_global_gets_a_global_statement():
    body = "let count: int = 0;\nevent tick { count = count + 1; }\ntrigger tick;\ntrigger tick;\nemit count;"
    assert run(body) == ["2"]
    assert "global count" in compile_body(body)


def test_reading_a_global_needs_no_global_statement():
    body = "let limit: int = 5;\nevent check { emit limit; }\ntrigger check;"
    assert run(body) == ["5"]
    assert "global" not in compile_body(body)


# ---- Names ----------------------------------------------------------------


def test_python_keywords_are_renamed():
    body = "let class: int = 1;\nlet print: int = 2;\nemit class + print;"
    assert run(body) == ["3"]
    code = compile_body(body)
    assert "class_: int = 1" in code
    assert "print_: int = 2" in code


# ---- Whole programs -------------------------------------------------------


EXPECTED_OUTPUT = {
    "smart_home.flow": [
        "High temperature detected", "[fan switched on]", "Motion detected",
        "[fan switched off]", "1",
    ],
    "billing.flow": ["1180.0", "Standard purchase"],
    "security.flow": [
        "Account should be locked", "Security check", "Security check", "Security check", "14",
    ],
}


@pytest.mark.parametrize("name, expected", EXPECTED_OUTPUT.items())
def test_example_programs_produce_the_right_output(name, expected):
    code = compile_source((EXAMPLES / name).read_text())
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(code, {"__name__": "__main__"})
    assert output.getvalue().splitlines() == expected


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.flow")), ids=lambda p: p.name)
def test_generated_code_is_valid_python(path):
    compile(compile_source(path.read_text()), path.name, "exec")  # raises SyntaxError if not
