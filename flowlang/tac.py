"""Intermediate code generation: turns the annotated AST into three-address code.

Three-address code (TAC) is a simple, machine-like representation. Each
instruction does at most one operation on at most three addresses (names,
constants or temporaries t1, t2, ...):

    let score: int = 2 + 3 * 4;      becomes      t1 = 3 * 4
                                                  t2 = 2 + t1
                                                  score = t2

There are no if statements or loops in TAC, only labels and jumps:

    L1:                     a place to jump to
    goto L1                 always jump
    ifFalse t1 goto L2      jump only if t1 is false

Each instruction is stored as a quadruple: (op, arg1, arg2, result). The --tac
flag shows the readable text form; --quads shows the quadruple table.

This phase reads the same annotated AST as the Python code generator. Its output
is shown for inspection; the Python target is generated from the tree.
"""

import json
from dataclasses import dataclass

from flowlang.ast_nodes import (
    Assign, BinaryOp, Block, Call, CallStmt, EmitStmt, EventDecl, Expression,
    FunctionDecl, IfStmt, Literal, Program, RepeatStmt, ReturnStmt, Statement,
    TriggerStmt, UnaryOp, VarDecl, Variable,
)
from flowlang.semantic import AnalysisResult


@dataclass
class Quad:
    """One TAC instruction as a quadruple: (op, arg1, arg2, result)."""

    op: str
    arg1: str | None = None
    arg2: str | None = None
    result: str | None = None

    def __str__(self) -> str:
        """The instruction in readable TAC form, e.g. t2 = 2 + t1."""
        if self.op == "label":
            return f"{self.result}:"
        if self.op == "goto":
            return f"goto {self.result}"
        if self.op in ("if", "ifFalse"):
            return f"{self.op} {self.arg1} goto {self.result}"
        if self.op == "=":
            return f"{self.result} = {self.arg1}"
        if self.op == "uminus":
            return f"{self.result} = -{self.arg1}"
        if self.op == "!":
            return f"{self.result} = !{self.arg1}"
        if self.op == "inttofloat":
            return f"{self.result} = inttofloat {self.arg1}"
        if self.op == "param":
            return f"param {self.arg1}"
        if self.op == "call":
            call = f"call {self.arg1}, {self.arg2}"
            return f"{self.result} = {call}" if self.result else call
        if self.op == "return":
            return f"return {self.arg1}" if self.arg1 else "return"
        if self.op == "emit":
            return f"emit {self.arg1}"
        return f"{self.result} = {self.arg1} {self.op} {self.arg2}"  # binary operator


@dataclass
class TACUnit:
    """The TAC for one function, one event, or the main program."""

    kind: str  # "func", "event" or "main"
    name: str
    params: list[str]
    code: list[Quad]
    temps: set[str]  # the temporaries the compiler made for this unit


def tac_literal(value: int | float | str | bool) -> str:
    """How a constant is written in TAC: 42, 32.5, "fan", true."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)  # double quotes, with escapes
    return repr(value)


class TACGenerator:
    """Generates the TAC units for one analyzed FlowLang Program."""

    def __init__(self, analysis: AnalysisResult):
        # Parameter types of every function and built-in, for int -> float conversion.
        self.callables = {s.name: s for s in analysis.symbols if s.is_callable()}
        self.user_names = {s.name for s in analysis.symbols}  # temporaries must not clash with these
        self.temp_count = 0
        self.label_count = 0
        self.code: list[Quad] = []  # the unit currently being generated
        self.temps: set[str] = set()  # temporaries made for the current unit
        self.return_type: str | None = None

    def new_temp(self) -> str:
        self.temp_count += 1
        while f"t{self.temp_count}" in self.user_names:  # skip names the program already uses
            self.temp_count += 1
        temp = f"t{self.temp_count}"
        self.temps.add(temp)
        return temp

    def new_label(self) -> str:
        self.label_count += 1
        return f"L{self.label_count}"

    def add(self, op: str, arg1: str | None = None, arg2: str | None = None, result: str | None = None):
        self.code.append(Quad(op, arg1, arg2, result))

    # ---- Units --------------------------------------------------------------

    def generate(self, program: Program) -> list[TACUnit]:
        """Functions and events first, then the main program."""
        units = []
        main_statements = []
        for item in program.items:
            if isinstance(item, FunctionDecl):
                self.return_type = item.return_type
                params = [param.name for param in item.params]
                units.append(self.unit("func", item.name, params, item.body.statements))
                self.return_type = None
            elif isinstance(item, EventDecl):
                units.append(self.unit("event", item.name, [], item.body.statements))
            else:
                main_statements.append(item)
        units.append(self.unit("main", program.name, [], main_statements))
        return units

    def unit(self, kind: str, name: str, params: list[str], statements: list[Statement]) -> TACUnit:
        self.code = []
        self.temps = set()
        self.statements(statements)
        return TACUnit(kind, name, params, self.code, self.temps)

    # ---- Statements ---------------------------------------------------------

    def statements(self, statements: list[Statement]):
        for stmt in statements:
            self.statement(stmt)

    def block(self, block: Block):
        self.statements(block.statements)

    def statement(self, stmt: Statement):
        if isinstance(stmt, VarDecl):
            self.add("=", self.value(stmt.value, stmt.type), result=stmt.name)
        elif isinstance(stmt, Assign):
            self.add("=", self.value(stmt.value, stmt.type), result=stmt.name)
        elif isinstance(stmt, IfStmt):
            self.if_statement(stmt)
        elif isinstance(stmt, RepeatStmt):
            self.repeat(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                self.add("return")
            else:
                self.add("return", self.value(stmt.value, self.return_type))
        elif isinstance(stmt, EmitStmt):
            self.add("emit", self.expression(stmt.value))
        elif isinstance(stmt, CallStmt):
            self.call(stmt.call, keep_result=False)
        elif isinstance(stmt, TriggerStmt):
            self.add("call", stmt.event, "0")  # an event is a function with no arguments
        else:
            raise TypeError(f"unknown statement {stmt!r}")

    def if_statement(self, stmt: IfStmt):
        """
            <condition into c>
            ifFalse c goto L_else
            <then block>
            goto L_end
        L_else:
            <else branch>
        L_end:
        """
        condition = self.expression(stmt.condition)
        if stmt.else_branch is None:
            end = self.new_label()
            self.add("ifFalse", condition, result=end)
            self.block(stmt.then_block)
            self.add("label", result=end)
            return

        else_label = self.new_label()
        end = self.new_label()
        self.add("ifFalse", condition, result=else_label)
        self.block(stmt.then_block)
        self.add("goto", result=end)
        self.add("label", result=else_label)
        if isinstance(stmt.else_branch, IfStmt):
            self.if_statement(stmt.else_branch)  # else if: another if inside the else part
        else:
            self.block(stmt.else_branch)
        self.add("label", result=end)

    def repeat(self, stmt: RepeatStmt):
        """
            n = <count>             (evaluated once)
            i = 0
        L_start:
            c = i < n
            ifFalse c goto L_end
            <body>
            i = i + 1
            goto L_start
        L_end:
        """
        count = self.expression(stmt.count)
        counter = self.new_temp()
        start = self.new_label()
        end = self.new_label()
        self.add("=", "0", result=counter)
        self.add("label", result=start)
        condition = self.new_temp()
        self.add("<", counter, count, condition)
        self.add("ifFalse", condition, result=end)
        self.block(stmt.body)
        self.add("+", counter, "1", counter)
        self.add("goto", result=start)
        self.add("label", result=end)

    # ---- Expressions --------------------------------------------------------
    # Each method adds the instructions for an expression and returns the
    # address that holds its value: a constant, a variable name or a temporary.

    def value(self, expr: Expression, target_type: str | None) -> str:
        """An expression's address, converted to float if an int is stored as a float."""
        address = self.expression(expr)
        if target_type == "float" and expr.type == "int":
            if isinstance(expr, Literal):
                return tac_literal(float(expr.value))  # 2 -> 2.0, no instruction needed
            temp = self.new_temp()
            self.add("inttofloat", address, result=temp)
            return temp
        return address

    def expression(self, expr: Expression) -> str:
        if isinstance(expr, Literal):
            return tac_literal(expr.value)
        if isinstance(expr, Variable):
            return expr.name
        if isinstance(expr, Call):
            return self.call(expr, keep_result=True)
        if isinstance(expr, UnaryOp):
            operand = self.expression(expr.operand)
            temp = self.new_temp()
            self.add("uminus" if expr.op == "-" else "!", operand, result=temp)
            return temp
        if isinstance(expr, BinaryOp):
            if expr.op in ("&&", "||"):
                return self.short_circuit(expr)
            left = self.expression(expr.left)
            right = self.expression(expr.right)
            temp = self.new_temp()
            self.add(expr.op, left, right, temp)
            return temp
        raise TypeError(f"unknown expression {expr!r}")

    def short_circuit(self, expr: BinaryOp) -> str:
        """&& and || skip the right side when the left side decides the answer.

        a && b:   t = a                a || b:   t = a
                  ifFalse t goto L               if t goto L
                  t = b                          t = b
              L:                             L:
        """
        result = self.new_temp()
        end = self.new_label()
        self.add("=", self.expression(expr.left), result=result)
        self.add("ifFalse" if expr.op == "&&" else "if", result, result=end)
        self.add("=", self.expression(expr.right), result=result)
        self.add("label", result=end)
        return result

    def call(self, call: Call, keep_result: bool) -> str | None:
        """param for each argument (evaluated first), then the call itself."""
        param_types = self.callables[call.name].params
        args = [self.value(arg, param_type) for arg, param_type in zip(call.args, param_types)]
        for arg in args:
            self.add("param", arg)
        if not keep_result:
            self.add("call", call.name, str(len(args)))
            return None
        temp = self.new_temp()
        self.add("call", call.name, str(len(args)), temp)
        return temp


def generate_tac(program: Program, analysis: AnalysisResult) -> list[TACUnit]:
    """Convenience function: the TAC units for an analyzed program."""
    return TACGenerator(analysis).generate(program)


# ---- Display ----------------------------------------------------------------


def unit_header(unit: TACUnit) -> str:
    if unit.kind == "func":
        return f"func {unit.name}({', '.join(unit.params)}):"
    if unit.kind == "event":
        return f"event {unit.name}:"
    return f"main {unit.name}:"


def format_tac(units: list[TACUnit]) -> str:
    """The TAC as text (the --tac flag). Labels stick out to the left."""
    lines = []
    for unit in units:
        if lines:
            lines.append("")
        lines.append(unit_header(unit))
        for quad in unit.code:
            indent = "  " if quad.op == "label" else "    "
            lines.append(indent + str(quad))
    return "\n".join(lines)


def format_quadruples(units: list[TACUnit]) -> str:
    """The TAC as quadruple tables, one per unit (the --quads flag)."""
    lines = []
    for unit in units:
        if lines:
            lines.append("")
        lines.append(unit_header(unit))
        rows = [("#", "op", "arg1", "arg2", "result")]
        for number, quad in enumerate(unit.code):
            rows.append((str(number), quad.op, quad.arg1 or "", quad.arg2 or "", quad.result or ""))
        widths = [max(len(row[i]) for row in rows) + 2 for i in range(5)]
        for row in rows:
            lines.append("    " + "".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())
    return "\n".join(lines)
