"""Semantic analysis: checks that a grammatically correct program makes sense.

The parser only checks the shape of the program. This phase checks its meaning
(the rules in docs/language.md, section 3):
  - every name is declared before it is used, and not declared twice
  - operators, assignments, conditions and calls get values of the right type
  - return, call and trigger are used correctly

It walks the AST and keeps a symbol table (symbols.py) of declared names.
There are two passes over the program:
  1. Collect every function and event, so they can be used before the line
     where they are declared, and can call each other (including recursion).
  2. Check every statement and expression, in source order.

It also records what the code generator needs later:
  - the type of each expression, written into the node's `type` field
    (this makes it an "annotated AST"), and
  - which global variables each function or event assigns to.
"""

from dataclasses import dataclass

from flowlang.ast_nodes import (
    Assign, BinaryOp, Block, Call, CallStmt, EmitStmt, EventDecl, Expression,
    FunctionDecl, IfStmt, Literal, Node, Program, RepeatStmt, ReturnStmt,
    Statement, TriggerStmt, UnaryOp, VarDecl, Variable,
)
from flowlang.errors import SemanticError
from flowlang.symbols import Symbol, SymbolTable

NUMERIC = ("int", "float")


@dataclass
class AnalysisResult:
    """What semantic analysis passes on to the code generator."""

    symbols: list[Symbol]  # every declared symbol, for the --symbols table
    global_writes: dict[str, set[str]]  # function/event name -> global variables it assigns


# ---- Type rules (the tables in docs/language.md) ---------------------------


def is_compatible(target: str, actual: str) -> bool:
    """Can a value of type `actual` be stored where `target` is expected?

    Only exact matches, plus int -> float widening (an int fits in a float).
    """
    return actual == target or (target == "float" and actual == "int")


def binary_result_type(op: str, left: str, right: str) -> str | None:
    """The type of `left op right`, or None if the operator doesn't allow these types."""
    both_numbers = left in NUMERIC and right in NUMERIC

    if op in ("+", "-", "*", "/", "^"):
        if both_numbers:
            return "int" if left == right == "int" else "float"
        if op == "+" and left == right == "string":
            return "string"  # concatenation
        return None
    if op == "%":
        return "int" if left == right == "int" else None
    if op in ("<", ">", "<=", ">="):
        return "bool" if both_numbers else None
    if op in ("==", "!="):
        return "bool" if left == right or both_numbers else None
    if op in ("&&", "||"):
        return "bool" if left == right == "bool" else None
    raise ValueError(f"unknown operator {op!r}")


def always_returns(statements: list[Statement]) -> bool:
    """Does this list of statements return on every path?

    True if the last statement is a return, or an if/else where every branch
    always returns. (An if without an else can be skipped, so it doesn't count.)
    """
    if not statements:
        return False
    last = statements[-1]
    if isinstance(last, ReturnStmt):
        return True
    if isinstance(last, IfStmt):
        return if_always_returns(last)
    return False


def if_always_returns(stmt: IfStmt) -> bool:
    if not always_returns(stmt.then_block.statements):
        return False
    if stmt.else_branch is None:
        return False
    if isinstance(stmt.else_branch, IfStmt):
        return if_always_returns(stmt.else_branch)
    return always_returns(stmt.else_branch.statements)


def article(type_name: str) -> str:
    """'an int', 'a float': the type name with the right article for messages."""
    return f"an {type_name}" if type_name[0] in "aeiou" else f"a {type_name}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


# ---- The analyzer -----------------------------------------------------------


class Analyzer:
    """Walks one Program tree, checking it against the semantic rules."""

    def __init__(self):
        self.symbols = SymbolTable()
        self.current_function: Symbol | None = None  # the function being checked, for return
        self.current_body: str | None = None  # the function or event being checked
        self.global_writes: dict[str, set[str]] = {}

        # Built-in functions are declared in the global scope before the program.
        self.symbols.declare(Symbol("turn_on", "builtin", None, params=["string"]))
        self.symbols.declare(Symbol("turn_off", "builtin", None, params=["string"]))

    def analyze(self, program: Program) -> AnalysisResult:
        # Pass 1: declare every function and event first.
        for item in program.items:
            if isinstance(item, FunctionDecl):
                param_types = [param.type for param in item.params]
                self.declare(Symbol(item.name, "function", item.return_type, param_types, item.line), item)
            elif isinstance(item, EventDecl):
                self.declare(Symbol(item.name, "event", None, line=item.line), item)

        # Pass 2: check everything in source order.
        for item in program.items:
            if isinstance(item, FunctionDecl):
                self.check_function(item)
            elif isinstance(item, EventDecl):
                self.check_event(item)
            else:
                self.check_statement(item)

        return AnalysisResult(self.symbols.all_symbols, self.global_writes)

    # ---- Helpers -----------------------------------------------------------

    def error(self, message: str, node: Node) -> SemanticError:
        return SemanticError(message, node.line, node.column)

    def declare(self, symbol: Symbol, node: Node):
        """Declare a name, unless it is already visible (no redeclaring, no shadowing)."""
        existing = self.symbols.lookup(symbol.name)
        if existing is not None:
            where = "as a built-in function" if existing.kind == "builtin" else f"at line {existing.line}"
            raise self.error(f"'{symbol.name}' is already declared {where}", node)
        self.symbols.declare(symbol)

    def require_compatible(self, target: str, actual: str, node: Node, message: str):
        if not is_compatible(target, actual):
            raise self.error(message, node)

    # ---- Functions and events ----------------------------------------------

    def check_function(self, fn: FunctionDecl):
        self.current_function = self.symbols.lookup(fn.name)
        self.current_body = fn.name
        self.global_writes[fn.name] = set()

        # Parameters and the body's own variables share one scope.
        self.symbols.enter_scope(f"fn {fn.name}")
        for param in fn.params:
            self.declare(Symbol(param.name, "parameter", param.type, line=param.line), param)
        self.check_statements(fn.body.statements)
        self.symbols.exit_scope()

        if fn.return_type is not None and not always_returns(fn.body.statements):
            raise self.error(f"function '{fn.name}' must return {article(fn.return_type)} on every path", fn)

        self.current_function = None
        self.current_body = None

    def check_event(self, event: EventDecl):
        self.current_body = event.name
        self.global_writes[event.name] = set()
        self.check_block(event.body, f"event {event.name}")
        self.current_body = None

    # ---- Statements --------------------------------------------------------

    def check_block(self, block: Block, scope_name: str):
        """A block gets its own scope: names declared inside disappear at the '}'."""
        self.symbols.enter_scope(scope_name)
        self.check_statements(block.statements)
        self.symbols.exit_scope()

    def check_statements(self, statements: list[Statement]):
        for stmt in statements:
            self.check_statement(stmt)

    def check_statement(self, stmt: Statement):
        if isinstance(stmt, VarDecl):
            self.check_var_decl(stmt)
        elif isinstance(stmt, Assign):
            self.check_assign(stmt)
        elif isinstance(stmt, IfStmt):
            self.check_if(stmt)
        elif isinstance(stmt, RepeatStmt):
            self.check_repeat(stmt)
        elif isinstance(stmt, ReturnStmt):
            self.check_return(stmt)
        elif isinstance(stmt, EmitStmt):
            self.check_expression(stmt.value)  # emit accepts any type
        elif isinstance(stmt, CallStmt):
            self.check_call(stmt.call, value_needed=False)
        elif isinstance(stmt, TriggerStmt):
            self.check_trigger(stmt)
        else:
            raise TypeError(f"unknown statement {stmt!r}")

    def check_var_decl(self, stmt: VarDecl):
        # The value is checked before the name is declared, so `let x: int = x;` is an error.
        value_type = self.check_expression(stmt.value)
        self.require_compatible(
            stmt.type, value_type, stmt.value,
            f"cannot store {article(value_type)} value in '{stmt.name}', which is declared as {stmt.type}",
        )
        self.declare(Symbol(stmt.name, "variable", stmt.type, line=stmt.line), stmt)

    def check_assign(self, stmt: Assign):
        symbol = self.symbols.lookup(stmt.name)
        if symbol is None:
            raise self.error(f"'{stmt.name}' is not declared (use 'let' to declare it)", stmt)
        if not symbol.is_variable():
            raise self.error(f"cannot assign to '{stmt.name}': it is {article(symbol.kind)}, not a variable", stmt)

        value_type = self.check_expression(stmt.value)
        self.require_compatible(
            symbol.type, value_type, stmt.value,
            f"cannot assign {article(value_type)} value to '{stmt.name}', which is declared as {symbol.type}",
        )

        stmt.type = symbol.type  # the code generator needs it for int -> float conversion

        # Remember global variables assigned inside a function or event:
        # the generated Python needs a `global` statement for them.
        if self.current_body is not None and self.symbols.is_global(symbol):
            self.global_writes[self.current_body].add(stmt.name)

    def check_if(self, stmt: IfStmt):
        condition_type = self.check_expression(stmt.condition)
        if condition_type != "bool":
            raise self.error(f"the if condition must be a bool, not {condition_type}", stmt.condition)

        self.check_block(stmt.then_block, "if")
        if isinstance(stmt.else_branch, IfStmt):
            self.check_if(stmt.else_branch)  # else if
        elif stmt.else_branch is not None:
            self.check_block(stmt.else_branch, "else")

    def check_repeat(self, stmt: RepeatStmt):
        count_type = self.check_expression(stmt.count)
        if count_type != "int":
            raise self.error(f"the repeat count must be an int, not {count_type}", stmt.count)
        self.check_block(stmt.body, "repeat")

    def check_return(self, stmt: ReturnStmt):
        fn = self.current_function
        if fn is None:
            raise self.error("'return' is only allowed inside a function", stmt)

        if stmt.value is None:
            if fn.type is not None:
                raise self.error(f"function '{fn.name}' must return {article(fn.type)} value", stmt)
            return

        if fn.type is None:
            raise self.error(f"function '{fn.name}' has no return type, so it cannot return a value", stmt)
        value_type = self.check_expression(stmt.value)
        self.require_compatible(
            fn.type, value_type, stmt.value,
            f"function '{fn.name}' must return {article(fn.type)}, not {article(value_type)}",
        )

    def check_trigger(self, stmt: TriggerStmt):
        symbol = self.symbols.lookup(stmt.event)
        if symbol is None:
            raise self.error(f"event '{stmt.event}' is not declared", stmt)
        if symbol.kind != "event":
            raise self.error(f"'{stmt.event}' is {article(symbol.kind)}, not an event", stmt)

    # ---- Expressions -------------------------------------------------------
    # Each check returns the expression's type and stores it in the node.

    def check_expression(self, expr: Expression) -> str:
        if isinstance(expr, Literal):
            return expr.type  # the parser already knows a literal's type
        if isinstance(expr, Variable):
            return self.check_variable(expr)
        if isinstance(expr, Call):
            return self.check_call(expr, value_needed=True)
        if isinstance(expr, UnaryOp):
            return self.check_unary(expr)
        if isinstance(expr, BinaryOp):
            return self.check_binary(expr)
        raise TypeError(f"unknown expression {expr!r}")

    def check_variable(self, expr: Variable) -> str:
        symbol = self.symbols.lookup(expr.name)
        if symbol is None:
            raise self.error(f"'{expr.name}' is not declared", expr)
        if symbol.is_callable():
            raise self.error(f"'{expr.name}' is a function: call it with {expr.name}(...)", expr)
        if not symbol.is_variable():
            raise self.error(f"'{expr.name}' is an event, not a variable", expr)
        expr.type = symbol.type
        return expr.type

    def check_call(self, call: Call, value_needed: bool) -> str | None:
        """Check a function call. value_needed is False for `call f();` statements."""
        symbol = self.symbols.lookup(call.name)
        if symbol is None:
            raise self.error(f"function '{call.name}' is not declared", call)
        if symbol.kind == "event":
            raise self.error(f"'{call.name}' is an event: fire it with 'trigger {call.name};'", call)
        if not symbol.is_callable():
            raise self.error(f"'{call.name}' is {article(symbol.kind)}, not a function", call)

        if len(call.args) != len(symbol.params):
            raise self.error(
                f"'{call.name}' takes {plural(len(symbol.params), 'argument')} "
                f"but got {len(call.args)}",
                call,
            )
        for number, (arg, param_type) in enumerate(zip(call.args, symbol.params), start=1):
            arg_type = self.check_expression(arg)
            self.require_compatible(
                param_type, arg_type, arg,
                f"argument {number} of '{call.name}' must be {article(param_type)}, not {article(arg_type)}",
            )

        if value_needed and symbol.type is None:
            raise self.error(f"'{call.name}' does not return a value, so it cannot be used in an expression", call)
        call.type = symbol.type
        return call.type

    def check_unary(self, expr: UnaryOp) -> str:
        operand_type = self.check_expression(expr.operand)
        if expr.op == "-" and operand_type not in NUMERIC:
            raise self.error(f"'-' needs a number, not {article(operand_type)}", expr)
        if expr.op == "!" and operand_type != "bool":
            raise self.error(f"'!' needs a bool, not {article(operand_type)}", expr)
        expr.type = operand_type
        return expr.type

    def check_binary(self, expr: BinaryOp) -> str:
        left_type = self.check_expression(expr.left)
        right_type = self.check_expression(expr.right)
        result_type = binary_result_type(expr.op, left_type, right_type)
        if result_type is None:
            raise self.error(f"cannot use '{expr.op}' with {left_type} and {right_type}", expr)
        expr.type = result_type
        return expr.type


def analyze(program: Program) -> AnalysisResult:
    """Convenience function: check a Program tree and return what codegen needs."""
    return Analyzer().analyze(program)
