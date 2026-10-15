"""Tests for the lexer (Stage 1)."""

from pathlib import Path

import pytest

from flowlang.errors import LexicalError
from flowlang.lexer import tokenize
from flowlang.tokens import TokenType as T

EXAMPLES = Path(__file__).parent.parent / "examples"


def types(source):
    """The token types for source, without the final EOF."""
    return [token.type for token in tokenize(source)[:-1]]


# ---- Words ----------------------------------------------------------------


def test_keywords_and_identifiers():
    assert types("let temperature") == [T.LET, T.IDENTIFIER]


def test_maximal_munch_on_words():
    # "letter" starts with "let" but is one identifier.
    assert types("letter") == [T.IDENTIFIER]


def test_identifiers_can_contain_digits_and_underscores():
    tokens = tokenize("_sensor_2")
    assert tokens[0].type == T.IDENTIFIER
    assert tokens[0].lexeme == "_sensor_2"


# ---- Numbers --------------------------------------------------------------


def test_integer_and_float_values():
    integer, number, _ = tokenize("42 32.5")
    assert (integer.type, integer.value) == (T.INT_LITERAL, 42)
    assert (number.type, number.value) == (T.FLOAT_LITERAL, 32.5)


def test_float_without_digits_after_dot_is_an_error():
    with pytest.raises(LexicalError, match="expected a digit after '.'"):
        tokenize("3.")


def test_number_followed_by_letter_is_an_error():
    with pytest.raises(LexicalError, match="malformed number"):
        tokenize("3abc")


# ---- Strings --------------------------------------------------------------


def test_string_value_has_no_quotes():
    token = tokenize('"fan"')[0]
    assert token.type == T.STRING_LITERAL
    assert token.lexeme == '"fan"'
    assert token.value == "fan"


def test_string_escapes():
    token = tokenize(r'"say \"hi\"\n"')[0]
    assert token.value == 'say "hi"\n'


def test_unterminated_string_is_an_error():
    with pytest.raises(LexicalError, match="unterminated string"):
        tokenize('emit "hello;')


def test_string_cannot_span_lines():
    with pytest.raises(LexicalError, match="unterminated string"):
        tokenize('"line one\nline two"')


def test_invalid_escape_is_an_error():
    with pytest.raises(LexicalError, match="invalid escape"):
        tokenize(r'"bad \q"')


# ---- Symbols --------------------------------------------------------------


def test_two_character_operators_are_one_token():
    assert types("<= >= == != && || ->") == [
        T.LESS_EQUAL, T.GREATER_EQUAL, T.EQUAL_EQUAL, T.BANG_EQUAL, T.AND, T.OR, T.ARROW,
    ]


def test_maximal_munch_on_symbols():
    # With a space they are separate tokens; without, one token.
    assert types("< =") == [T.LESS, T.EQUAL]
    assert types("<=") == [T.LESS_EQUAL]


def test_caret_operator():
    assert types("2 ^ 3") == [T.INT_LITERAL, T.CARET, T.INT_LITERAL]


def test_unexpected_character_is_an_error():
    with pytest.raises(LexicalError, match="unexpected character '@'"):
        tokenize("price @ 2")


def test_single_ampersand_suggests_double():
    with pytest.raises(LexicalError, match="did you mean '&&'"):
        tokenize("a & b")


# ---- Whitespace, comments and positions -----------------------------------


def test_comments_are_skipped():
    assert types("let // this is ignored\nx") == [T.LET, T.IDENTIFIER]


def test_positions_are_tracked():
    tokens = tokenize("let x\n  emit y")
    positions = [(t.lexeme, t.line, t.column) for t in tokens[:-1]]
    assert positions == [("let", 1, 1), ("x", 1, 5), ("emit", 2, 3), ("y", 2, 8)]


def test_error_reports_position():
    with pytest.raises(LexicalError) as caught:
        tokenize("let x = 1;\nlet y = #;")
    assert (caught.value.line, caught.value.column) == (2, 9)


def test_token_list_ends_with_eof():
    assert tokenize("")[-1].type == T.EOF
    assert tokenize("let x")[-1].type == T.EOF


# ---- Whole programs -------------------------------------------------------


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.flow")), ids=lambda p: p.name)
def test_example_programs_have_no_lexical_errors(path):
    tokens = tokenize(path.read_text())
    assert tokens[0].type == T.PROGRAM


def test_lexical_error_example_fails():
    with pytest.raises(LexicalError):
        tokenize((EXAMPLES / "errors" / "lexical_error.flow").read_text())
