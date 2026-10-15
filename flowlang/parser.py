"""Syntax analysis: turns the list of tokens into an abstract syntax tree (AST).

This is a recursive-descent parser. Each grammar rule in docs/language.md
becomes one parse_* method, and the methods call each other in the same way
the rules refer to each other:

    grammar                          code
    -------                          ----
    "let"                            self.expect(T.LET, ...)
    rule_name                        self.parse_rule_name()
    ( ... )*      zero or more       while self.check(...):
    ( ... )?      optional           if self.match(...):
    a | b         choice             if/elif on the current token

The parser is LL(1): it always decides what to do by looking at just one
token, the current one.
"""

from flowlang.ast_nodes import (
    Assign, BinaryOp, Block, Call, CallStmt, EmitStmt, EventDecl, Expression,
    FunctionDecl, IfStmt, Literal, Param, Program, RepeatStmt, ReturnStmt,
    Statement, TriggerStmt, UnaryOp, VarDecl, Variable,
)
from flowlang.errors import ParseError
from flowlang.tokens import Token
from flowlang.tokens import TokenType as T

TYPE_KEYWORDS = (T.INT, T.FLOAT, T.BOOL, T.STRING)


def describe_type(token_type: T) -> str:
    """How a token type is named in error messages: ';', 'let', a name, ..."""
    if token_type == T.IDENTIFIER:
        return "a name"
    if token_type == T.EOF:
        return "end of file"
    return f"'{token_type.value}'"


def describe_token(token: Token) -> str:
    """How an actual token is shown in error messages."""
    if token.type == T.EOF:
        return "end of file"
    if token.type == T.IDENTIFIER:
        return f"name '{token.lexeme}'"
    if token.type in (T.INT_LITERAL, T.FLOAT_LITERAL, T.STRING_LITERAL):
        return f"{token.type.value} {token.lexeme}"
    return f"'{token.lexeme}'"


class Parser:
    """Parses one token list (from the lexer) into a Program tree."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0  # index of the current token

    # ---- Moving through the tokens ----------------------------------------

    def current(self) -> Token:
        return self.tokens[self.pos]

    def next(self) -> Token:
        """The token after the current one (a second token of lookahead)."""
        return self.tokens[min(self.pos + 1, len(self.tokens) - 1)]

    def check(self, *types: T) -> bool:
        """Is the current token one of these types? (Does not consume it.)"""
        return self.current().type in types

    def advance(self) -> Token:
        """Consume the current token and return it. Never moves past EOF."""
        token = self.current()
        if token.type != T.EOF:
            self.pos += 1
        return token

    def match(self, *types: T) -> Token | None:
        """Consume the current token if it is one of these types."""
        if self.check(*types):
            return self.advance()
        return None

    def expect(self, token_type: T, context: str) -> Token:
        """Consume a token that must be here, or report a syntax error.

        context completes the message, e.g. "after the variable declaration"
        gives: expected ';' after the variable declaration, found 'emit'.
        """
        if self.check(token_type):
            return self.advance()
        raise self.error_missing(f"{describe_type(token_type)} {context}")

    # ---- Errors -----------------------------------------------------------

    def error_missing(self, expected: str) -> ParseError:
        """Something required is missing. Point at the spot where it belongs."""
        found = self.current()
        message = f"expected {expected}, found {describe_token(found)}"
        previous = self.tokens[self.pos - 1] if self.pos > 0 else found
        if found.line > previous.line:
            # The missing piece belongs at the end of the previous line (a forgotten
            # ';' is the usual case), so point there instead of at the next line.
            return ParseError(message, previous.line, previous.column + len(previous.lexeme))
        return ParseError(message, found.line, found.column)

    def error_here(self, message: str) -> ParseError:
        """The current token doesn't belong here. Point at it."""
        token = self.current()
        return ParseError(message, token.line, token.column)

    # ---- Program and declarations -----------------------------------------

    def parse_program(self) -> Program:
        """program ::= "program" IDENTIFIER "{" item* "}" """
        start = self.expect(T.PROGRAM, "at the start of the file")
        name = self.expect(T.IDENTIFIER, "after 'program'")
        self.expect(T.LBRACE, "after the program name")

        items = []
        while not self.check(T.RBRACE, T.EOF):
            items.append(self.parse_item())

        self.expect(T.RBRACE, "to close the program")
        self.expect(T.EOF, "after the closing '}' of the program")
        return Program(name.lexeme, items, line=start.line, column=start.column)

    def parse_item(self) -> FunctionDecl | EventDecl | Statement:
        """item ::= function_decl | event_decl | statement"""
        if self.check(T.FN):
            return self.parse_function()
        if self.check(T.EVENT):
            return self.parse_event()
        return self.parse_statement()

    def parse_function(self) -> FunctionDecl:
        """function_decl ::= "fn" IDENTIFIER "(" parameters? ")" ( "->" type )? block"""
        start = self.advance()  # 'fn'
        name = self.expect(T.IDENTIFIER, "after 'fn'")
        self.expect(T.LPAREN, "after the function name")

        # parameters ::= parameter ( "," parameter )*
        params = []
        if not self.check(T.RPAREN):
            params.append(self.parse_param())
            while self.match(T.COMMA):
                params.append(self.parse_param())
        self.expect(T.RPAREN, "after the parameters")

        return_type = None
        if self.match(T.ARROW):
            return_type = self.parse_type()

        body = self.parse_block()
        return FunctionDecl(
            name.lexeme, params, return_type, body, line=start.line, column=start.column
        )

    def parse_param(self) -> Param:
        """parameter ::= IDENTIFIER ":" type"""
        name = self.expect(T.IDENTIFIER, "as a parameter name")
        self.expect(T.COLON, "after the parameter name")
        param_type = self.parse_type()
        return Param(name.lexeme, param_type, line=name.line, column=name.column)

    def parse_event(self) -> EventDecl:
        """event_decl ::= "event" IDENTIFIER block"""
        start = self.advance()  # 'event'
        name = self.expect(T.IDENTIFIER, "after 'event'")
        body = self.parse_block()
        return EventDecl(name.lexeme, body, line=start.line, column=start.column)

    def parse_type(self) -> str:
        """type ::= "int" | "float" | "bool" | "string" """
        if self.check(*TYPE_KEYWORDS):
            return self.advance().lexeme
        raise self.error_missing("a type (int, float, bool or string)")

    def parse_block(self) -> Block:
        """block ::= "{" statement* "}" """
        start = self.expect(T.LBRACE, "to start a block")
        statements = []
        while not self.check(T.RBRACE, T.EOF):
            statements.append(self.parse_statement())
        self.expect(T.RBRACE, "to close the block")
        return Block(statements, line=start.line, column=start.column)

    # ---- Statements -------------------------------------------------------

    def parse_statement(self) -> Statement:
        """statement ::= variable_decl | assignment | if_stmt | repeat_stmt
                       | return_stmt | emit_stmt | call_stmt | trigger_stmt

        The first token decides which kind of statement this is (LL(1)).
        """
        if self.check(T.LET):
            return self.parse_var_decl()
        if self.check(T.IDENTIFIER):
            return self.parse_assignment()
        if self.check(T.IF):
            return self.parse_if()
        if self.check(T.REPEAT):
            return self.parse_repeat()
        if self.check(T.RETURN):
            return self.parse_return()
        if self.check(T.EMIT):
            return self.parse_emit()
        if self.check(T.CALL):
            return self.parse_call_stmt()
        if self.check(T.TRIGGER):
            return self.parse_trigger()
        if self.check(T.FN, T.EVENT):
            raise self.error_here("functions and events can only be declared at the top level of the program")
        raise self.error_here(f"expected a statement, found {describe_token(self.current())}")

    def parse_var_decl(self) -> VarDecl:
        """variable_decl ::= "let" IDENTIFIER ":" type "=" expression ";" """
        start = self.advance()  # 'let'
        name = self.expect(T.IDENTIFIER, "after 'let'")
        self.expect(T.COLON, "after the variable name")
        var_type = self.parse_type()
        self.expect(T.EQUAL, "after the type (every variable needs a starting value)")
        value = self.parse_expression()
        self.expect(T.SEMICOLON, "after the variable declaration")
        return VarDecl(name.lexeme, var_type, value, line=start.line, column=start.column)

    def parse_assignment(self) -> Assign:
        """assignment ::= IDENTIFIER "=" expression ";" """
        if self.next().type == T.LPAREN:
            # A common mistake: writing turn_on("fan"); without 'call'.
            name = self.current().lexeme
            raise self.error_here(f"to call a function as a statement, write 'call {name}(...);'")

        name = self.advance()
        self.expect(T.EQUAL, f"after '{name.lexeme}' in an assignment")
        value = self.parse_expression()
        self.expect(T.SEMICOLON, "after the assignment")
        return Assign(name.lexeme, value, line=name.line, column=name.column)

    def parse_if(self) -> IfStmt:
        """if_stmt ::= "if" expression block ( "else" ( if_stmt | block ) )?"""
        start = self.advance()  # 'if'
        condition = self.parse_expression()
        then_block = self.parse_block()

        else_branch = None
        if self.match(T.ELSE):
            if self.check(T.IF):
                else_branch = self.parse_if()  # else if: an if nested inside the else
            else:
                else_branch = self.parse_block()

        return IfStmt(condition, then_block, else_branch, line=start.line, column=start.column)

    def parse_repeat(self) -> RepeatStmt:
        """repeat_stmt ::= "repeat" expression block"""
        start = self.advance()  # 'repeat'
        count = self.parse_expression()
        body = self.parse_block()
        return RepeatStmt(count, body, line=start.line, column=start.column)

    def parse_return(self) -> ReturnStmt:
        """return_stmt ::= "return" expression? ";" """
        start = self.advance()  # 'return'
        value = None
        if not self.check(T.SEMICOLON):
            value = self.parse_expression()
        self.expect(T.SEMICOLON, "after the return statement")
        return ReturnStmt(value, line=start.line, column=start.column)

    def parse_emit(self) -> EmitStmt:
        """emit_stmt ::= "emit" expression ";" """
        start = self.advance()  # 'emit'
        value = self.parse_expression()
        self.expect(T.SEMICOLON, "after the emit statement")
        return EmitStmt(value, line=start.line, column=start.column)

    def parse_call_stmt(self) -> CallStmt:
        """call_stmt ::= "call" function_call ";" """
        start = self.advance()  # 'call'
        name = self.expect(T.IDENTIFIER, "after 'call'")
        call = self.parse_call(name)
        self.expect(T.SEMICOLON, "after the call")
        return CallStmt(call, line=start.line, column=start.column)

    def parse_trigger(self) -> TriggerStmt:
        """trigger_stmt ::= "trigger" IDENTIFIER ";" """
        start = self.advance()  # 'trigger'
        name = self.expect(T.IDENTIFIER, "after 'trigger'")
        self.expect(T.SEMICOLON, "after the trigger statement")
        return TriggerStmt(name.lexeme, line=start.line, column=start.column)

    # ---- Expressions, from lowest to highest precedence -------------------
    #
    # Each level calls the next (tighter) level for its operands, so operators
    # further down this list bind tighter: * before +, + before <, and so on.
    # The while loops build the tree from left to right, which makes every
    # operator left-associative: a - b - c means (a - b) - c.

    def parse_expression(self) -> Expression:
        """expression ::= logical_or"""
        return self.parse_logical_or()

    def parse_logical_or(self) -> Expression:
        """logical_or ::= logical_and ( "||" logical_and )*"""
        left = self.parse_logical_and()
        while self.check(T.OR):
            op = self.advance()
            right = self.parse_logical_and()
            left = BinaryOp(op.lexeme, left, right, line=op.line, column=op.column)
        return left

    def parse_logical_and(self) -> Expression:
        """logical_and ::= equality ( "&&" equality )*"""
        left = self.parse_equality()
        while self.check(T.AND):
            op = self.advance()
            right = self.parse_equality()
            left = BinaryOp(op.lexeme, left, right, line=op.line, column=op.column)
        return left

    def parse_equality(self) -> Expression:
        """equality ::= comparison ( ( "==" | "!=" ) comparison )*"""
        left = self.parse_comparison()
        while self.check(T.EQUAL_EQUAL, T.BANG_EQUAL):
            op = self.advance()
            right = self.parse_comparison()
            left = BinaryOp(op.lexeme, left, right, line=op.line, column=op.column)
        return left

    def parse_comparison(self) -> Expression:
        """comparison ::= additive ( ( "<" | ">" | "<=" | ">=" ) additive )*"""
        left = self.parse_additive()
        while self.check(T.LESS, T.GREATER, T.LESS_EQUAL, T.GREATER_EQUAL):
            op = self.advance()
            right = self.parse_additive()
            left = BinaryOp(op.lexeme, left, right, line=op.line, column=op.column)
        return left

    def parse_additive(self) -> Expression:
        """additive ::= multiplicative ( ( "+" | "-" ) multiplicative )*"""
        left = self.parse_multiplicative()
        while self.check(T.PLUS, T.MINUS):
            op = self.advance()
            right = self.parse_multiplicative()
            left = BinaryOp(op.lexeme, left, right, line=op.line, column=op.column)
        return left

    def parse_multiplicative(self) -> Expression:
        """multiplicative ::= unary ( ( "*" | "/" | "%" ) unary )*"""
        left = self.parse_unary()
        while self.check(T.STAR, T.SLASH, T.PERCENT):
            op = self.advance()
            right = self.parse_unary()
            left = BinaryOp(op.lexeme, left, right, line=op.line, column=op.column)
        return left

    def parse_unary(self) -> Expression:
        """unary ::= ( "!" | "-" ) unary | primary"""
        if self.check(T.BANG, T.MINUS):
            op = self.advance()
            operand = self.parse_unary()  # recursion allows -(-x) and !!flag
            return UnaryOp(op.lexeme, operand, line=op.line, column=op.column)
        return self.parse_power()

    def parse_power(self) -> Expression:
        """power ::= primary ( "^" unary )?

        Unlike the other operators, ^ is right-associative: 2 ^ 3 ^ 2 means
        2 ^ (3 ^ 2). So there is no while loop here. The right side is parsed
        by parse_unary, which comes back to parse_power, and that recursion
        groups the operators from the right.
        """
        base = self.parse_primary()
        if self.check(T.CARET):
            op = self.advance()
            exponent = self.parse_unary()
            return BinaryOp(op.lexeme, base, exponent, line=op.line, column=op.column)
        return base

    def parse_primary(self) -> Expression:
        """primary ::= INTEGER | FLOAT | STRING | "true" | "false"
                     | IDENTIFIER ( "(" arguments? ")" )?
                     | "(" expression ")"
        """
        token = self.current()
        position = {"line": token.line, "column": token.column}

        if self.match(T.INT_LITERAL):
            return Literal(token.value, "int", **position)
        if self.match(T.FLOAT_LITERAL):
            return Literal(token.value, "float", **position)
        if self.match(T.STRING_LITERAL):
            return Literal(token.value, "string", **position)
        if self.match(T.TRUE):
            return Literal(True, "bool", **position)
        if self.match(T.FALSE):
            return Literal(False, "bool", **position)

        if self.match(T.IDENTIFIER):
            # Left factoring: read the name first, then one token of lookahead
            # decides between a function call and a plain variable.
            if self.check(T.LPAREN):
                return self.parse_call(token)
            return Variable(token.lexeme, **position)

        if self.match(T.LPAREN):
            # Parentheses: parse a whole expression again (recursion). No node is
            # created for the parentheses; the tree shape already shows the grouping.
            inner = self.parse_expression()
            self.expect(T.RPAREN, "to close '('")
            return inner

        raise self.error_here(f"expected an expression, found {describe_token(token)}")

    def parse_call(self, name: Token) -> Call:
        """function_call ::= IDENTIFIER "(" arguments? ")"   (the name is already read)
        arguments     ::= expression ( "," expression )*
        """
        self.expect(T.LPAREN, f"after '{name.lexeme}' to call it")
        args = []
        if not self.check(T.RPAREN):
            args.append(self.parse_expression())
            while self.match(T.COMMA):
                args.append(self.parse_expression())
        self.expect(T.RPAREN, "after the arguments")
        return Call(name.lexeme, args, line=name.line, column=name.column)


def parse(tokens: list[Token]) -> Program:
    """Convenience function: parse a token list into a Program tree."""
    return Parser(tokens).parse_program()
