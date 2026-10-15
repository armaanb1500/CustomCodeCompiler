"""AST node classes: the tree the parser builds.

An abstract syntax tree (AST) represents the structure of a program, without
the punctuation that is only needed for parsing (semicolons, braces, colons).
For example, `let x: int = 2 + 3;` becomes:

    VarDecl name='x' type='int'
    └── value: BinaryOp op='+'
        ├── left: Literal value=2 type='int'
        └── right: Literal value=3 type='int'

Every node remembers the line and column where it starts, so later phases
can report errors at the right place.
"""

from dataclasses import dataclass


@dataclass(kw_only=True)
class Node:
    """Base class for all AST nodes.

    kw_only means line and column are always passed by name, after the
    node's own fields: BinaryOp("+", left, right, line=1, column=5).
    """

    line: int
    column: int


# ---- Expressions: produce a value -----------------------------------------


@dataclass
class Literal(Node):
    """A value written directly in the source: 42, 32.5, "fan", true."""

    value: int | float | str | bool
    type: str  # "int", "float", "string" or "bool"


@dataclass
class Variable(Node):
    """Reading a variable, e.g. `temperature`."""

    name: str
    type: str | None = None  # filled in by semantic analysis


@dataclass
class BinaryOp(Node):
    """An operator with two operands, e.g. `price * tax`."""

    op: str  # "+", "*", "<=", "&&", ...
    left: "Expression"
    right: "Expression"
    type: str | None = None  # filled in by semantic analysis


@dataclass
class UnaryOp(Node):
    """An operator with one operand: `-x` or `!locked`."""

    op: str  # "-" or "!"
    operand: "Expression"
    type: str | None = None  # filled in by semantic analysis


@dataclass
class Call(Node):
    """A function call, e.g. `calculate_total(1000.0, 18.0)`."""

    name: str
    args: list["Expression"]
    type: str | None = None  # filled in by semantic analysis


Expression = Literal | Variable | BinaryOp | UnaryOp | Call


# ---- Statements: do something ---------------------------------------------


@dataclass
class VarDecl(Node):
    """`let name: type = value;`"""

    name: str
    type: str
    value: Expression


@dataclass
class Assign(Node):
    """`name = value;`"""

    name: str
    value: Expression
    type: str | None = None  # the variable's type, filled in by semantic analysis


@dataclass
class Block(Node):
    """A list of statements between `{` and `}`."""

    statements: list["Statement"]


@dataclass
class IfStmt(Node):
    """`if condition { ... } else ...`

    else_branch is a Block for a plain `else`, another IfStmt for `else if`,
    or None when there is no else.
    """

    condition: Expression
    then_block: Block
    else_branch: "Block | IfStmt | None"


@dataclass
class RepeatStmt(Node):
    """`repeat count { ... }`"""

    count: Expression
    body: Block


@dataclass
class ReturnStmt(Node):
    """`return value;` or `return;` (value is None)."""

    value: Expression | None


@dataclass
class EmitStmt(Node):
    """`emit value;`"""

    value: Expression


@dataclass
class CallStmt(Node):
    """`call name(args);`, a call whose result is not used."""

    call: Call


@dataclass
class TriggerStmt(Node):
    """`trigger event_name;`"""

    event: str


Statement = VarDecl | Assign | IfStmt | RepeatStmt | ReturnStmt | EmitStmt | CallStmt | TriggerStmt


# ---- Top level: declarations and the program ------------------------------


@dataclass
class Param(Node):
    """One function parameter: `price: float`."""

    name: str
    type: str


@dataclass
class FunctionDecl(Node):
    """`fn name(params) -> return_type { ... }` (return_type is None if omitted)."""

    name: str
    params: list[Param]
    return_type: str | None
    body: Block


@dataclass
class EventDecl(Node):
    """`event name { ... }`"""

    name: str
    body: Block


@dataclass
class Program(Node):
    """The root of the tree: `program Name { items }`."""

    name: str
    items: list[FunctionDecl | EventDecl | Statement]
