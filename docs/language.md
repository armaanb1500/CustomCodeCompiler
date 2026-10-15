# FlowLang language specification

FlowLang is a small domain-specific language for event-driven rules (smart-device
automation, alerts, workflow rules). The compiler `flowc` translates `.flow` files
into Python 3.

This file is the source of truth for the language. If the language changes, change
this file first, then the code.

---

## 1. Lexical rules (used by the lexer, Stage 1)

| Token kind | Rule | Examples |
|---|---|---|
| Keyword | one of the reserved words below | `let`, `if`, `emit` |
| IDENTIFIER | a letter or `_`, then letters, digits or `_` | `temperature`, `turn_on` |
| INTEGER | one or more digits | `0`, `42` |
| FLOAT | digits `.` digits (both sides required) | `32.5`, `0.0` |
| STRING | text inside double quotes, on one line. Escapes: `\"` `\\` `\n` | `"Motion detected"` |
| Operator | `+ - * / % ^` `== != < > <= >=` `&& \|\| !` `=` `->` | |
| Punctuation | `( ) { } ; : ,` | |
| Comment | `//` to the end of the line (skipped, not a token) | `// check sensors` |

Whitespace (spaces, tabs, newlines) separates tokens and is otherwise ignored.

**Keywords:** `program let fn event if else repeat return emit call trigger
int float bool string true false`

**Lexical errors:** an unexpected character (e.g. `@`), an unterminated string,
or a malformed number (e.g. `3.`).

---

## 2. Grammar (EBNF, used by the parser, Stage 2)

Notation: `*` = zero or more, `?` = optional, `|` = choice, `"x"` = literal token.

```
program        ::= "program" IDENTIFIER "{" item* "}"

item           ::= function_decl
                 | event_decl
                 | statement

function_decl  ::= "fn" IDENTIFIER "(" parameters? ")" ( "->" type )? block
parameters     ::= parameter ( "," parameter )*
parameter      ::= IDENTIFIER ":" type

event_decl     ::= "event" IDENTIFIER block

type           ::= "int" | "float" | "bool" | "string"

block          ::= "{" statement* "}"

statement      ::= variable_decl
                 | assignment
                 | if_stmt
                 | repeat_stmt
                 | return_stmt
                 | emit_stmt
                 | call_stmt
                 | trigger_stmt

variable_decl  ::= "let" IDENTIFIER ":" type "=" expression ";"
assignment     ::= IDENTIFIER "=" expression ";"
if_stmt        ::= "if" expression block ( "else" ( if_stmt | block ) )?
repeat_stmt    ::= "repeat" expression block
return_stmt    ::= "return" expression? ";"
emit_stmt      ::= "emit" expression ";"
call_stmt      ::= "call" function_call ";"
trigger_stmt   ::= "trigger" IDENTIFIER ";"

expression     ::= logical_or
logical_or     ::= logical_and ( "||" logical_and )*
logical_and    ::= equality ( "&&" equality )*
equality       ::= comparison ( ( "==" | "!=" ) comparison )*
comparison     ::= additive ( ( "<" | ">" | "<=" | ">=" ) additive )*
additive       ::= multiplicative ( ( "+" | "-" ) multiplicative )*
multiplicative ::= unary ( ( "*" | "/" | "%" ) unary )*
unary          ::= ( "!" | "-" ) unary
                 | power
power          ::= primary ( "^" unary )?
primary        ::= INTEGER | FLOAT | STRING | "true" | "false"
                 | IDENTIFIER ( "(" arguments? ")" )?
                 | "(" expression ")"

function_call  ::= IDENTIFIER "(" arguments? ")"
arguments      ::= expression ( "," expression )*
```

**Why this grammar suits a hand-written (recursive-descent) parser:**

- **No left recursion.** Repetition is written with `*`, not as `additive ::= additive "+" ...`,
  so each rule becomes a function with a `while` loop instead of calling itself forever.
- **Left-factored.** `primary` reads one `IDENTIFIER` and then checks whether `(` follows,
  so the parser never has to guess between "variable" and "function call".
- **LL(1).** Each choice can be decided by looking at the next token only:
  a statement starting with `let` is a declaration, `if` is an if-statement,
  an `IDENTIFIER` is an assignment, and so on.
- **Precedence comes from rule order.** Rules lower in the chain bind tighter:
  `*` before `+`, `+` before `<`, `<` before `==`, `==` before `&&`, `&&` before `||`.
  All binary operators are left-associative: `a - b - c` means `(a - b) - c`.
- **`^` (power) is the exception.** It binds tighter than `*` and unary `-`, and is
  right-associative: `2 ^ 3 ^ 2` means `2 ^ (3 ^ 2)`, as in maths. In the grammar,
  its right side is `unary` (which leads back to `power`) instead of a `*` loop,
  so the recursion builds the tree from the right. `-2 ^ 2` means `-(2 ^ 2)`, and
  `2 ^ -1` is allowed.
- **No dangling else.** Blocks always need braces, so every `else` is unambiguous.

---

## 3. Semantic rules (checked by semantic analysis, Stage 3)

### Scopes and names
- A variable must be declared with `let` before it is used.
- **No shadowing:** a name cannot be declared again while an earlier declaration of
  it is still visible. (Reason: Python scopes are per-function, not per-block, so
  allowing shadowing would make the generated Python behave differently.)
- Function and event names are collected in a first pass, so they can be used
  before the line where they are declared.
- Functions and events can only be declared at the top level of `program`.

### Types
- Four types: `int`, `float`, `bool`, `string`. No `null`.
- The only automatic conversion is **int → float** (widening). For example, an `int`
  can be stored in a `float` variable or passed to a `float` parameter.

| Operator | Operand types | Result type |
|---|---|---|
| `+ - * /` | int, int | int (`/` is integer division) |
| `+ - * /` | any mix of int/float | float |
| `+` | string, string | string (concatenation) |
| `%` | int, int | int |
| `^` | int, int | int |
| `^` | any mix of int/float | float |
| `< > <= >=` | numbers | bool |
| `== !=` | two values of the same type (int/float may mix) | bool |
| `&& \|\|` | bool, bool | bool |
| `!` | bool | bool |
| unary `-` | int or float | same type |

- `if` conditions must be `bool`. The `repeat` count must be `int`.
- `emit` accepts a value of any type.

### Functions, events and returns
- A call must pass the right number of arguments, each of a compatible type.
- A function without `-> type` returns nothing. It can be used with `call`, but
  not inside an expression.
- `call` may also be used on a function that returns a value; the value is discarded.
- `return` is only allowed inside a function. Its value must match the return type.
  A function with no return type must use `return;` with no value.
- A function with a return type must return on every path: its last statement must
  be a `return`, or an `if`/`else` whose branches all end in a `return`.
- `trigger name;` requires `name` to be an event.

### Built-in functions
The global scope starts with these already declared:

| Built-in | Meaning |
|---|---|
| `turn_on(device: string)` | Simulates switching a device on (prints a message) |
| `turn_off(device: string)` | Simulates switching a device off (prints a message) |

User code cannot declare its own function with these names.

### Order of checking and known limitations
- Pass 1 collects all functions and events; pass 2 checks everything in source
  order. A function or event body can use global variables declared *above* it.
- Compilation stops at the first error (no error recovery).
- **Limitation:** the checker does not follow calls at compile time. If a function or
  event is triggered *before* a global variable it uses has been assigned (possible
  because functions can be used before their declaration), the generated Python
  fails at run time with a `NameError`. Detecting this would need inter-procedural
  analysis, which is beyond this project's scope.

---

## 4. Translation to Python (code generation, Stage 4)

| FlowLang | Python |
|---|---|
| `let x: int = 5;` | `x: int = 5` (types kept as Python annotations) |
| `fn f(a: int) -> int { ... }` | `def f(a: int) -> int:` |
| `event e { ... }` | `def e() -> None:` |
| `trigger e;` | `e()` |
| `emit expr;` | `print(expr)`; a bool prints as `true`/`false` |
| `call f(a);` | `f(a)` |
| `repeat n { ... }` | `for _ in range(n):` |
| `if / else if / else` | `if / elif / else` |
| `&&` `\|\|` `!` | `and` `or` `not` |
| `true` / `false` | `True` / `False` |
| `int / int` | `//` (integer division) |
| `a ^ b` | `a ** b` |
| `int ^ int` | `int(a ** b)` (a negative exponent would otherwise give a float) |
| empty block `{ }` | `pass` |
| int value stored as float | `2.0`, or `float(expr)` |
| `string` type | `str` |

Generated file layout: a short header comment, the built-in helper functions, then
all functions and events, then the top-level statements in source order inside
`if __name__ == "__main__":`. Functions come first so a function can be called
before its declaration in the source file.

When a function or event assigns to a top-level variable, the generator adds
`global name` at the start of the Python function. Without it Python would raise
`UnboundLocalError`.

FlowLang identifiers that are Python keywords (e.g. `class`, `def`, `None`), or names
the generated code relies on (`print`, `range`, `str`, `_`, ...), get a trailing
underscore in the output (`class_`).

The code generator adds parentheses where Python's precedence differs from FlowLang's:
`not` binds looser than `==` in Python, and Python chains comparisons
(`a < b == c` means `a < b and b == c`), so `!a == b` becomes `(not a) == b` and
`a < b == c` becomes `(a < b) == c`.

---

## 5. Intermediate code (three-address code)

`--tac` shows the program as three-address code; `--quads` shows the same
instructions as quadruples `(op, arg1, arg2, result)`. TAC is generated from the
annotated AST, alongside the Python target.

| Instruction | Meaning |
|---|---|
| `x = y` | copy |
| `t = a op b` | binary operation (any FlowLang binary operator except `&&`, `\|\|`) |
| `t = -a`, `t = !a` | unary minus (`uminus` in quadruples), not |
| `t = inttofloat a` | int → float widening |
| `L:` | label |
| `goto L` | unconditional jump |
| `if a goto L`, `ifFalse a goto L` | conditional jumps |
| `param a`, then `t = call f, n` or `call f, n` | call `f` with the last `n` params |
| `return a`, `return` | return from a function |
| `emit a` | output a value |

- Temporaries `t1, t2, ...` and labels `L1, L2, ...` are numbered across the whole program.
- `&&` and `||` use short-circuit jumps: the right side is skipped when the left side
  already decides the result.
- `repeat n` evaluates `n` once, then counts a temporary up from 0 to `n`.
- An event is a unit with no parameters; `trigger e;` is `call e, 0`.

---

## 6. Optimisation (optional)

`--optimize` (or `-O`) runs the optimiser on the TAC before printing it, followed by
a summary. Without the flag the TAC is shown exactly as generated. The Python output
is never affected. Passes, repeated until nothing changes:

| Pass | Effect |
|---|---|
| constant folding | `t1 = 3 * 4` → `t1 = 12` (using FlowLang's rules: `int / int` divides whole numbers) |
| constant propagation | a variable or temporary known to hold a constant is replaced by it |
| constant conditions | `ifFalse true goto L` is removed; `ifFalse false goto L` becomes `goto L` |
| unreachable code | instructions after `goto`/`return`, up to the next label, are removed |
| redundant jumps | a jump to a label that directly follows it is removed |
| unused labels | labels that no jump targets are removed |
| unused temporaries | a compiler temporary that is never read is removed (calls are kept) |

Safety rules: known values are forgotten at every label (several paths can meet
there) and, except for temporaries, at every call (the callee may change globals).
Division by zero and very large powers are not folded. The program's own variables
are never removed.
