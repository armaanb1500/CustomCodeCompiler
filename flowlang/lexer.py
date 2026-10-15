"""Lexical analysis: turns FlowLang source text into a list of tokens.

The lexer reads the source one character at a time. The first character of a
token decides what kind of token it is:

    letter or _    ->  keyword or identifier    (read_word)
    digit          ->  integer or float         (read_number)
    "              ->  string                   (read_string)
    anything else  ->  operator or punctuation  (read_symbol)

Each read_* method is one path through a finite automaton (DFA): it keeps
consuming characters while they still fit the token, and stops at the first
one that doesn't. Whitespace and // comments are skipped between tokens.
"""

from flowlang.errors import LexicalError
from flowlang.tokens import KEYWORDS, Token, TokenType

# Checked before ONE_CHAR_SYMBOLS so that "<=" becomes one token, not "<" then "=".
TWO_CHAR_SYMBOLS = {
    "==": TokenType.EQUAL_EQUAL,
    "!=": TokenType.BANG_EQUAL,
    "<=": TokenType.LESS_EQUAL,
    ">=": TokenType.GREATER_EQUAL,
    "&&": TokenType.AND,
    "||": TokenType.OR,
    "->": TokenType.ARROW,
}

ONE_CHAR_SYMBOLS = {
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.STAR,
    "/": TokenType.SLASH,
    "%": TokenType.PERCENT,
    "^": TokenType.CARET,
    "<": TokenType.LESS,
    ">": TokenType.GREATER,
    "!": TokenType.BANG,
    "=": TokenType.EQUAL,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
    ";": TokenType.SEMICOLON,
    ":": TokenType.COLON,
    ",": TokenType.COMMA,
}

# Escape sequences allowed inside strings: the character after the backslash -> its meaning.
ESCAPES = {'"': '"', "\\": "\\", "n": "\n"}

# What peek() returns when looking past the end of the source.
END = "\0"


def is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def is_letter(ch: str) -> bool:
    return "a" <= ch <= "z" or "A" <= ch <= "Z" or ch == "_"


class Lexer:
    """Scans one FlowLang source string into tokens."""

    def __init__(self, source: str):
        self.source = source
        self.pos = 0  # index of the next character to read
        self.line = 1  # line and column of that character
        self.column = 1
        # Where the token currently being read started (set by next_token).
        self.start = 0
        self.start_line = 1
        self.start_column = 1

    # ---- Reading characters ---------------------------------------------

    def at_end(self) -> bool:
        return self.pos >= len(self.source)

    def peek(self, offset: int = 0) -> str:
        """Look at a character ahead without consuming it (lookahead)."""
        index = self.pos + offset
        return self.source[index] if index < len(self.source) else END

    def advance(self) -> str:
        """Consume one character, keeping the line and column up to date."""
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    # ---- Main loop --------------------------------------------------------

    def tokenize(self) -> list[Token]:
        """Scan the whole source and return its tokens, ending with an EOF token."""
        tokens = []
        while True:
            self.skip_whitespace_and_comments()
            if self.at_end():
                break
            tokens.append(self.next_token())
        tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return tokens

    def skip_whitespace_and_comments(self):
        while not self.at_end():
            ch = self.peek()
            if ch in " \t\r\n":
                self.advance()
            elif ch == "/" and self.peek(1) == "/":
                while not self.at_end() and self.peek() != "\n":
                    self.advance()
            else:
                return

    def next_token(self) -> Token:
        """Read one token. Its first character decides which kind it is."""
        self.start = self.pos
        self.start_line = self.line
        self.start_column = self.column

        ch = self.peek()
        if is_letter(ch):
            return self.read_word()
        if is_digit(ch):
            return self.read_number()
        if ch == '"':
            return self.read_string()
        return self.read_symbol()

    # ---- One method per kind of token -------------------------------------

    def read_word(self) -> Token:
        """Keyword or identifier: a letter or _, then letters, digits or _."""
        while is_letter(self.peek()) or is_digit(self.peek()):
            self.advance()
        word = self.source[self.start : self.pos]
        # The whole word is read first (maximal munch), so "letter" is an
        # identifier, not the keyword "let" followed by "ter".
        token_type = KEYWORDS.get(word, TokenType.IDENTIFIER)
        return self.make_token(token_type)

    def read_number(self) -> Token:
        """Integer (42) or float (32.5). A float needs digits on both sides of the '.'."""
        self.read_digits()
        token_type = TokenType.INT_LITERAL

        if self.peek() == ".":
            if not is_digit(self.peek(1)):
                raise self.error("malformed number: expected a digit after '.'")
            self.advance()  # the '.'
            self.read_digits()
            token_type = TokenType.FLOAT_LITERAL

        if is_letter(self.peek()):
            raise self.error("malformed number: a number cannot be followed directly by a letter")

        text = self.source[self.start : self.pos]
        value = float(text) if token_type == TokenType.FLOAT_LITERAL else int(text)
        return self.make_token(token_type, value)

    def read_digits(self):
        while is_digit(self.peek()):
            self.advance()

    def read_string(self) -> Token:
        """String in double quotes, on one line. Supports the escapes \\" \\\\ and \\n."""
        self.advance()  # the opening quote
        chars = []
        while True:
            if self.at_end() or self.peek() == "\n":
                raise self.error('unterminated string: missing closing "')

            line, column = self.line, self.column
            ch = self.advance()
            if ch == '"':
                break
            if ch == "\\":
                escaped = self.peek()
                if escaped not in ESCAPES:
                    raise LexicalError(r'invalid escape sequence: use \" \\ or \n', line, column)
                self.advance()
                chars.append(ESCAPES[escaped])
            else:
                chars.append(ch)

        return self.make_token(TokenType.STRING_LITERAL, "".join(chars))

    def read_symbol(self) -> Token:
        """Operator or punctuation. Two-character symbols are tried first (maximal munch)."""
        two = self.source[self.pos : self.pos + 2]
        if two in TWO_CHAR_SYMBOLS:
            self.advance()
            self.advance()
            return self.make_token(TWO_CHAR_SYMBOLS[two])

        ch = self.peek()
        if ch in ONE_CHAR_SYMBOLS:
            self.advance()
            return self.make_token(ONE_CHAR_SYMBOLS[ch])

        if ch in "&|":
            raise self.error(f"unexpected character '{ch}' (did you mean '{ch}{ch}'?)")
        raise self.error(f"unexpected character {ch!r}")

    # ---- Helpers ----------------------------------------------------------

    def make_token(self, token_type: TokenType, value=None) -> Token:
        """Build a token from the text between self.start and the current position."""
        lexeme = self.source[self.start : self.pos]
        return Token(token_type, lexeme, self.start_line, self.start_column, value)

    def error(self, message: str) -> LexicalError:
        """An error pointing at the start of the current token."""
        return LexicalError(message, self.start_line, self.start_column)


def tokenize(source: str) -> list[Token]:
    """Convenience function: scan source text into a list of tokens."""
    return Lexer(source).tokenize()
