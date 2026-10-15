"""Tests for the parser (Stage 2)."""

from pathlib import Path

import pytest

from flowlang.ast_nodes import (
    Assign, BinaryOp, Block, Call, CallStmt, EmitStmt, EventDecl, FunctionDecl,
    IfStmt, Literal, RepeatStmt, ReturnStmt, TriggerStmt, UnaryOp, VarDecl, Variable,
)
from flowlang.ast_printer import format_ast
from flowlang.errors import ParseError
from flowlang.lexer import tokenize
from flowlang.parser import parse

EXAMPLES = Path(__file__).parent.parent / "examples"


def parse_source(source):
    return parse(tokenize(source))


def parse_items(body):
    """Parse code placed inside a program and return its top-level items."""
    return parse_source(f"program Test {{ {body} }}").items


def parse_expr(text):
    """Parse a single expression (by emitting it) and return its tree."""
    return parse_items(f"emit {text};")[0].value


def shape(expr):
    """A compact form of an expression tree: 2 + 3 * 4 -> ("+", 2, ("*", 3, 4))."""
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Variable):
        return expr.name
    if isinstance(expr, BinaryOp):
        return (expr.op, shape(expr.left), shape(expr.right))
    if isinstance(expr, UnaryOp):
        return (expr.op, shape(expr.operand))
    if isinstance(expr, Call):
        return ("call", expr.name, [shape(arg) for arg in expr.args])
    raise TypeError(expr)


# ---- Expressions: precedence and associativity -----------------------------


def test_multiplication_binds_tighter_than_addition():
    assert shape(parse_expr("2 + 3 * 4")) == ("+", 2, ("*", 3, 4))


def test_operators_are_left_associative():
    assert shape(parse_expr("10 - 4 - 3")) == ("-", ("-", 10, 4), 3)


def test_parentheses_override_precedence():
    assert shape(parse_expr("(2 + 3) * 4")) == ("*", ("+", 2, 3), 4)


def test_and_binds_tighter_than_or():
    assert shape(parse_expr("a || b && c")) == ("||", "a", ("&&", "b", "c"))


def test_comparison_binds_looser_than_arithmetic():
    assert shape(parse_expr("a + 1 > b * 2")) == (">", ("+", "a", 1), ("*", "b", 2))


def test_full_precedence_chain():
    expr = parse_expr("x > 1 && y == 2 || !z")
    assert shape(expr) == ("||", ("&&", (">", "x", 1), ("==", "y", 2)), ("!", "z"))


def test_unary_operators():
    assert shape(parse_expr("-x * 2")) == ("*", ("-", "x"), 2)
    assert shape(parse_expr("!!ready")) == ("!", ("!", "ready"))


def test_power_binds_tighter_than_multiplication():
    assert shape(parse_expr("2 * 3 ^ 2")) == ("*", 2, ("^", 3, 2))


def test_power_is_right_associative():
    assert shape(parse_expr("2 ^ 3 ^ 2")) == ("^", 2, ("^", 3, 2))


def test_power_and_unary_minus():
    assert shape(parse_expr("-2 ^ 2")) == ("-", ("^", 2, 2))
    assert shape(parse_expr("2 ^ -1")) == ("^", 2, ("-", 1))


def test_literals_have_types():
    literals = [parse_expr(text) for text in ("42", "3.5", '"hi"', "true")]
    assert [(lit.value, lit.type) for lit in literals] == [
        (42, "int"), (3.5, "float"), ("hi", "string"), (True, "bool"),
    ]


def test_variable_versus_call():
    # Left factoring: same first token, the next token decides.
    assert shape(parse_expr("total")) == "total"
    assert shape(parse_expr("total()")) == ("call", "total", [])
    assert shape(parse_expr("add(1, x + 2)")) == ("call", "add", [1, ("+", "x", 2)])


# ---- Statements -----------------------------------------------------------


def test_variable_declaration():
    (decl,) = parse_items("let temperature: float = 32.5;")
    assert isinstance(decl, VarDecl)
    assert (decl.name, decl.type, shape(decl.value)) == ("temperature", "float", 32.5)


def test_assignment():
    (stmt,) = parse_items("count = count + 1;")
    assert isinstance(stmt, Assign)
    assert shape(stmt.value) == ("+", "count", 1)


def test_if_without_else():
    (stmt,) = parse_items("if ready { emit 1; }")
    assert isinstance(stmt, IfStmt)
    assert isinstance(stmt.then_block, Block)
    assert stmt.else_branch is None


def test_else_if_chain_nests_ifs():
    (stmt,) = parse_items("if a { emit 1; } else if b { emit 2; } else { emit 3; }")
    assert isinstance(stmt.else_branch, IfStmt)
    assert isinstance(stmt.else_branch.else_branch, Block)


def test_repeat():
    (stmt,) = parse_items("repeat n - 1 { emit 1; }")
    assert isinstance(stmt, RepeatStmt)
    assert shape(stmt.count) == ("-", "n", 1)
    assert len(stmt.body.statements) == 1


def test_emit_call_and_trigger():
    emit, call, trigger = parse_items('emit "hi"; call turn_on("fan"); trigger alarm;')
    assert isinstance(emit, EmitStmt)
    assert isinstance(call, CallStmt) and call.call.name == "turn_on"
    assert isinstance(trigger, TriggerStmt) and trigger.event == "alarm"


# ---- Functions and events -------------------------------------------------


def test_function_with_params_and_return_type():
    (fn,) = parse_items("fn add(a: int, b: float) -> float { return a + b; }")
    assert isinstance(fn, FunctionDecl)
    assert [(p.name, p.type) for p in fn.params] == [("a", "int"), ("b", "float")]
    assert fn.return_type == "float"
    (ret,) = fn.body.statements
    assert isinstance(ret, ReturnStmt) and shape(ret.value) == ("+", "a", "b")


def test_function_without_return_type():
    (fn,) = parse_items("fn reset() { return; }")
    assert fn.params == []
    assert fn.return_type is None
    assert fn.body.statements[0].value is None


def test_event():
    (event,) = parse_items("event on_alarm { emit 1; }")
    assert isinstance(event, EventDecl)
    assert event.name == "on_alarm"


def test_nodes_remember_positions():
    (decl,) = parse_items("\n  let x: int = 1;")
    assert (decl.line, decl.column) == (2, 3)


# ---- Syntax errors --------------------------------------------------------


def test_missing_semicolon_points_at_end_of_line():
    with pytest.raises(ParseError) as caught:
        parse_source("program T {\n  let x: int = 3\n  emit x;\n}")
    error = caught.value
    assert "expected ';' after the variable declaration" in error.message
    assert (error.line, error.column) == (2, 17)


def test_missing_closing_brace():
    with pytest.raises(ParseError, match="found end of file"):
        parse_source("program T { emit 1;")


def test_missing_type():
    with pytest.raises(ParseError, match="expected a type"):
        parse_items("let x: = 5;")


def test_missing_expression():
    with pytest.raises(ParseError, match="expected an expression, found ';'"):
        parse_items("let x: int = ;")


def test_unclosed_parenthesis():
    with pytest.raises(ParseError, match="expected '\\)' to close '\\('"):
        parse_items("emit (1 + 2;")


def test_function_inside_block_is_an_error():
    with pytest.raises(ParseError, match="only be declared at the top level"):
        parse_items("event e { fn inner() { } }")


def test_call_without_call_keyword_gives_a_hint():
    with pytest.raises(ParseError, match="write 'call turn_on"):
        parse_items('turn_on("fan");')


def test_code_after_program_is_an_error():
    with pytest.raises(ParseError, match="expected end of file"):
        parse_source("program T { } emit 1;")


# ---- Whole programs and the AST printer -----------------------------------


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.flow")), ids=lambda p: p.name)
def test_example_programs_parse(path):
    program = parse_source(path.read_text())
    assert program.items


def test_syntax_error_example_fails():
    with pytest.raises(ParseError) as caught:
        parse_source((EXAMPLES / "errors" / "syntax_error.flow").read_text())
    assert (caught.value.line, caught.value.column) == (5, 23)


def test_ast_printer_draws_a_tree():
    text = format_ast(parse_source("program Demo { let x: int = 2 + 3; }"))
    assert text == (
        "Program name='Demo'\n"
        "└── VarDecl name='x' type='int'\n"
        "    └── value: BinaryOp op='+'\n"
        "        ├── left: Literal value=2 type='int'\n"
        "        └── right: Literal value=3 type='int'"
    )
