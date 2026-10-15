"""The symbol table: every declared name, organised into nested scopes.

A symbol is anything with a name: a variable, parameter, function or event.
The table is a stack of scopes. Each scope is a dictionary from name to
Symbol, and the global scope is at the bottom:

    [ {global names}, {names in a function}, {names in an if block} ]

Entering a block pushes a new scope; leaving it pops the scope, and its names
disappear. A lookup searches from the innermost scope outwards, so code can
see names from enclosing scopes but not from inner ones.
"""

from dataclasses import dataclass, field


@dataclass
class Symbol:
    """One declared name and what the compiler knows about it."""

    name: str
    kind: str  # "variable", "parameter", "function", "event" or "builtin"
    type: str | None  # a variable's type, or a function's return type (None = returns nothing)
    params: list[str] = field(default_factory=list)  # parameter types, for functions
    line: int = 0  # where it was declared (0 for built-ins)
    scope: str = "global"  # set by SymbolTable.declare, e.g. "global > fn add"

    def is_variable(self) -> bool:
        return self.kind in ("variable", "parameter")

    def is_callable(self) -> bool:
        return self.kind in ("function", "builtin")

    def describe_type(self) -> str:
        """The type as shown in the --symbols table, e.g. (float, float) -> float."""
        if self.kind == "event":
            return "-"
        if self.is_callable():
            signature = f"({', '.join(self.params)})"
            return f"{signature} -> {self.type}" if self.type else signature
        return self.type


class SymbolTable:
    """A stack of scopes, innermost last."""

    def __init__(self):
        self.scopes: list[dict[str, Symbol]] = [{}]  # starts with just the global scope
        self.scope_names: list[str] = ["global"]
        self.all_symbols: list[Symbol] = []  # every symbol ever declared, for --symbols

    def enter_scope(self, name: str):
        self.scopes.append({})
        self.scope_names.append(name)

    def exit_scope(self):
        self.scopes.pop()
        self.scope_names.pop()

    def declare(self, symbol: Symbol):
        """Add a symbol to the innermost scope."""
        symbol.scope = " > ".join(self.scope_names)
        self.scopes[-1][symbol.name] = symbol
        self.all_symbols.append(symbol)

    def lookup(self, name: str) -> Symbol | None:
        """Find a visible symbol, searching from the innermost scope outwards."""
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def is_global(self, symbol: Symbol) -> bool:
        return self.scopes[0].get(symbol.name) is symbol
