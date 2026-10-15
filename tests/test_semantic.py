"""Tests for semantic analysis (Stage 3)."""

from pathlib import Path

import pytest

from flowlang.errors import SemanticError
from flowlang.lexer import tokenize
from flowlang.parser import parse
from flowlang.semantic import analyze, binary_result_type, is_compatible

EXAMPLES = Path(__file__).parent.parent / "examples"


def check_program(source):
    """Run lexer, parser and semantic analysis. Returns (program, analysis)."""
    program = parse(tokenize(source))
    return program, analyze(program)


def check(body):
    """Check code placed inside a program. Returns (program, analysis)."""
    return check_program(f"program Test {{\n{body}\n}}")


def error_message(body):
    """Check code that must fail; return the semantic error message."""
    with pytest.raises(SemanticError) as caught:
        check(body)
    return caught.value.message


# ---- Type rules -----------------------------------------------------------


@pytest.mark.parametrize("op, left, right, expected", [
    ("+", "int", "int", "int"),
    ("+", "int", "float", "float"),
    ("/", "int", "int", "int"),
    ("^", "int", "int", "int"),
    ("^", "float", "int", "float"),
    ("+", "string", "string", "string"),
    ("+", "string", "int", None),
    ("-", "string", "string", None),
    ("%", "int", "int", "int"),
    ("%", "float", "int", None),
    ("<", "int", "float", "bool"),
    ("<", "string", "string", None),
    ("==", "string", "string", "bool"),
    ("==", "int", "float", "bool"),
    ("==", "int", "string", None),
    ("&&", "bool", "bool", "bool"),
    ("&&", "int", "bool", None),
])
def test_binary_result_type(op, left, right, expected):
    assert binary_result_type(op, left, right) == expected


def test_int_widens_to_float_but_not_back():
    assert is_compatible("float", "int")
    assert not is_compatible("int", "float")
    assert not is_compatible("string", "int")


# ---- Declarations and scopes ----------------------------------------------


def test_valid_declarations_pass():
    check("let x: int = 1;\nlet y: float = x + 0.5;\nlet name: string = \"fan\";")


def test_undeclared_variable():
    assert error_message("emit humidity;") == "'humidity' is not declared"


def test_use_before_declaration():
    assert "not declared" in error_message("emit x;\nlet x: int = 1;")


def test_variable_cannot_use_itself_in_its_own_value():
    assert "not declared" in error_message("let x: int = x + 1;")


def test_redeclaring_in_the_same_scope():
    message = error_message("let x: int = 1;\nlet x: int = 2;")
    assert message == "'x' is already declared at line 2"


def test_no_shadowing_in_inner_blocks():
    assert "already declared" in error_message("let x: int = 1;\nif true { let x: int = 2; }")


def test_block_variables_disappear_after_the_block():
    assert "not declared" in error_message("if true { let inner: int = 1; }\nemit inner;")


def test_sibling_blocks_can_reuse_a_name():
    check('if true { let x: int = 1; } else { let x: string = "a"; }')


def test_assignment_type_mismatch():
    message = error_message("let count: int = 0;\ncount = 2.5;")
    assert message == "cannot assign a float value to 'count', which is declared as int"


def test_cannot_assign_to_undeclared_variable():
    assert "not declared" in error_message("count = 1;")


def test_cannot_assign_to_a_function():
    assert "not a variable" in error_message("fn f() { }\nf = 1;")


# ---- Conditions and loops -------------------------------------------------


def test_if_condition_must_be_bool():
    assert error_message("if 1 { emit 1; }") == "the if condition must be a bool, not int"


def test_repeat_count_must_be_int():
    assert error_message("repeat 2.5 { emit 1; }") == "the repeat count must be an int, not float"


def test_operator_type_error():
    assert error_message('emit "a" - 1;') == "cannot use '-' with string and int"


def test_unary_type_errors():
    assert "'!' needs a bool" in error_message("emit !5;")
    assert "'-' needs a number" in error_message("emit -true;")


# ---- Functions and calls --------------------------------------------------


def test_functions_can_be_used_before_their_declaration():
    check("emit double(2);\nfn double(n: int) -> int { return n * 2; }")


def test_recursion_is_allowed():
    check("fn fact(n: int) -> int { if n <= 1 { return 1; } else { return n * fact(n - 1); } }")


def test_wrong_argument_count():
    message = error_message("fn add(a: int, b: int) -> int { return a + b; }\nemit add(5);")
    assert message == "'add' takes 2 arguments but got 1"


def test_wrong_argument_type():
    message = error_message('call turn_on(5);')
    assert message == "argument 1 of 'turn_on' must be a string, not an int"


def test_int_argument_widens_to_float_parameter():
    check("fn half(x: float) -> float { return x / 2.0; }\nemit half(3);")


def test_function_without_value_cannot_be_used_in_expression():
    assert "does not return a value" in error_message('emit turn_on("fan");')


def test_call_statement_may_discard_a_value():
    check("fn one() -> int { return 1; }\ncall one();")


def test_undeclared_function():
    assert error_message("call launch();") == "function 'launch' is not declared"


def test_function_used_as_variable():
    assert "is a function" in error_message("fn f() { }\nemit f;")


def test_duplicate_function():
    assert "already declared" in error_message("fn f() { }\nfn f() { }")


def test_cannot_redefine_a_builtin():
    assert error_message("fn turn_on(d: string) { }") == "'turn_on' is already declared as a built-in function"


def test_duplicate_parameter_names():
    assert "already declared" in error_message("fn f(a: int, a: int) { }")


# ---- Returns --------------------------------------------------------------


def test_return_outside_function():
    assert error_message("return;") == "'return' is only allowed inside a function"


def test_return_inside_event_is_not_allowed():
    assert "only allowed inside a function" in error_message("event e { return; }")


def test_return_type_mismatch():
    message = error_message('fn f() -> int { return "x"; }')
    assert message == "function 'f' must return an int, not a string"


def test_void_function_cannot_return_a_value():
    assert "cannot return a value" in error_message("fn f() { return 1; }")


def test_missing_return_value():
    assert "must return an int value" in error_message("fn f() -> int { return; }")


def test_missing_return_on_some_path():
    message = error_message("fn f(x: int) -> int { if x > 0 { return 1; } }")
    assert message == "function 'f' must return an int on every path"


def test_if_else_returning_on_every_path_is_fine():
    check("fn sign(x: int) -> int { if x > 0 { return 1; } else if x < 0 { return -1; } else { return 0; } }")


# ---- Events and trigger ---------------------------------------------------


def test_trigger_needs_an_event():
    assert error_message("trigger nothing;") == "event 'nothing' is not declared"
    assert "not an event" in error_message("fn f() { }\ntrigger f;")


def test_event_cannot_be_called_like_a_function():
    assert "fire it with 'trigger e;'" in error_message("event e { }\ncall e();")


# ---- Information passed on to code generation -----------------------------


def test_expression_types_are_recorded_in_the_tree():
    program, _ = check("let x: float = 1 + 2.5;\nlet y: int = 7 / 2;")
    first, second = program.items
    assert first.value.type == "float"
    assert second.value.type == "int"


def test_global_writes_are_recorded():
    _, analysis = check(
        "let count: int = 0;\n"
        "event tick { let local: int = 1; local = 2; count = count + local; }\n"
        "fn reset(n: int) { n = 0; count = n; }"
    )
    assert analysis.global_writes == {"tick": {"count"}, "reset": {"count"}}


def test_symbols_record_their_scope():
    _, analysis = check("fn add(a: int, b: int) -> int { return a + b; }")
    scopes = {symbol.name: symbol.scope for symbol in analysis.symbols}
    assert scopes["add"] == "global"
    assert scopes["a"] == "global > fn add"


# ---- Whole programs -------------------------------------------------------


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.flow")), ids=lambda p: p.name)
def test_example_programs_pass(path):
    check_program(path.read_text())


@pytest.mark.parametrize("name, line", [
    ("undeclared_variable.flow", 4),
    ("type_mismatch.flow", 3),
    ("wrong_argument_count.flow", 7),
])
def test_semantic_error_examples_fail_at_the_right_line(name, line):
    with pytest.raises(SemanticError) as caught:
        check_program((EXAMPLES / "errors" / name).read_text())
    assert caught.value.line == line
