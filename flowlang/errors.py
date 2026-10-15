"""Compiler errors, shared by every phase.

Each error remembers where it happened (line and column), so it can be shown
with the source line and a caret (^) under the problem:

    lexical error at line 4, column 30: unexpected character '@'
       4 |     let total: float = price @ 2.0;
         |                              ^
"""


class CompileError(Exception):
    """Base class for every error found in a FlowLang program."""

    phase = "compile"  # each subclass names its phase: "lexical", "syntax", ...

    def __init__(self, message: str, line: int, column: int):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column

    def format(self, source: str) -> str:
        """Return the error message with the source line and a caret under the column."""
        header = f"{self.phase} error at line {self.line}, column {self.column}: {self.message}"
        lines = source.splitlines()
        if not 1 <= self.line <= len(lines):
            return header

        code = lines[self.line - 1]
        # Copy tabs from the source line so the caret still lines up when tabs are used.
        padding = "".join("\t" if ch == "\t" else " " for ch in code[: self.column - 1])
        return f"{header}\n{self.line:>4} | {code}\n     | {padding}^"


class LexicalError(CompileError):
    """An error found while turning characters into tokens."""

    phase = "lexical"


class ParseError(CompileError):
    """An error found while checking the tokens against the grammar."""

    phase = "syntax"


class SemanticError(CompileError):
    """An error in the meaning of the program: unknown names, wrong types, ..."""

    phase = "semantic"
