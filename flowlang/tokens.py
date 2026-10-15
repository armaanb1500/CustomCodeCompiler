"""Token definitions: the vocabulary of FlowLang.

The lexer turns source text into a list of Token objects. Each token has a
type (what kind of word it is, e.g. IDENTIFIER) and a lexeme (the exact text
it came from, e.g. "temperature").
"""

from dataclasses import dataclass
from enum import Enum


class TokenType(Enum):
    """Every kind of token in FlowLang.

    For fixed tokens (keywords, operators, punctuation) the value is the exact
    text. For the rest it is a description, used later in error messages.
    """

    # Names and literal values
    IDENTIFIER = "identifier"
    INT_LITERAL = "integer literal"
    FLOAT_LITERAL = "float literal"
    STRING_LITERAL = "string literal"

    # Keywords
    PROGRAM = "program"
    LET = "let"
    FN = "fn"
    EVENT = "event"
    IF = "if"
    ELSE = "else"
    REPEAT = "repeat"
    RETURN = "return"
    EMIT = "emit"
    CALL = "call"
    TRIGGER = "trigger"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    TRUE = "true"
    FALSE = "false"

    # Operators
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    CARET = "^"
    EQUAL_EQUAL = "=="
    BANG_EQUAL = "!="
    LESS = "<"
    GREATER = ">"
    LESS_EQUAL = "<="
    GREATER_EQUAL = ">="
    AND = "&&"
    OR = "||"
    BANG = "!"
    EQUAL = "="
    ARROW = "->"

    # Punctuation
    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    SEMICOLON = ";"
    COLON = ":"
    COMMA = ","

    # Marks the end of the token list, so the parser always has a token to look at.
    EOF = "end of file"


# Reserved words. A word that is not in this table is an identifier.
KEYWORDS = {
    "program": TokenType.PROGRAM,
    "let": TokenType.LET,
    "fn": TokenType.FN,
    "event": TokenType.EVENT,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "repeat": TokenType.REPEAT,
    "return": TokenType.RETURN,
    "emit": TokenType.EMIT,
    "call": TokenType.CALL,
    "trigger": TokenType.TRIGGER,
    "int": TokenType.INT,
    "float": TokenType.FLOAT,
    "bool": TokenType.BOOL,
    "string": TokenType.STRING,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
}


@dataclass(frozen=True)
class Token:
    """One token, with its position in the source for error messages."""

    type: TokenType
    lexeme: str  # the exact source text, e.g. '"fan"' or '32.5'
    line: int
    column: int
    value: int | float | str | None = None  # Python value for literals ("fan", 32.5), else None
