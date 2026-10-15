# Learning log

Notes on what each stage built and the compiler concepts behind it. Useful for
the project report and for preparing for review questions.

---

## Stage 0: Project setup

### What we built
- The folder structure, a Python virtual environment, and pytest.
- `docs/language.md`, the full language specification: lexical rules, grammar,
  semantic rules, and how each construct translates to Python.
- Example programs in `examples/`, plus programs in `examples/errors/` that each
  contain one deliberate error. These become test cases in later stages.
- A command-line entry point (`python -m flowlang file.flow`) that only reads the
  file for now.

### Concepts

**A compiler is a pipeline of phases.** Each phase turns one representation of
the program into another:

| Phase | Input → Output | Catches |
|---|---|---|
| Lexical analysis (lexer) | characters → tokens | invalid characters, unterminated strings |
| Syntax analysis (parser) | tokens → abstract syntax tree (AST) | code that breaks the grammar |
| Semantic analysis | AST → checked AST + symbol table | undeclared names, type errors |
| Code generation | AST → target code | nothing; the input is already known to be valid |

The first three phases form the **front end** (understanding the source language).
Code generation is the **back end** (producing the target language). Real compilers
also have an optimization phase in between; FlowLang skips it to keep the scope small.

**Transpiler (source-to-source compiler).** FlowLang compiles to Python source code
rather than machine code or bytecode. It's still a full compiler: it has every
analysis phase, and only the back end's target is different.

**Hand-written vs generated front end.** Tools like Flex and Bison take a
specification (regex patterns and grammar rules) and generate the lexer and parser.
We write both by hand instead. Our grammar is LL(1), so it maps directly onto a
*recursive-descent parser*, where each grammar rule becomes one function. GCC,
Clang, Go and Rust all use hand-written parsers, mainly because of the control it
gives over error messages.

### Language decisions made at this stage
Compared with the first draft of the grammar:
- Top-level statements are allowed inside `program` (the examples needed them).
- Added `function_call` and `arguments` rules, which the draft used without defining.
- Added `else if`, `//` comments, functions without a return type, and `return;`.
- Added `trigger name;` so events can actually be fired.
- `turn_on` / `turn_off` are built-in functions, pre-declared in the global scope.
- `repeat` takes any `int` expression, not only a number literal.
- No shadowing, because Python scopes are per-function rather than per-block.

### Exercise
1. Write your own program `examples/my_rules.flow` that uses every keyword at least
   once. Check it against the grammar in `docs/language.md` by hand.
2. Take its first `let` line and write out the tokens the lexer should produce,
   e.g. `KEYWORD(let) IDENTIFIER(temperature) COLON ...`. We'll compare against
   the real lexer in Stage 1.
3. Make the first commit:
   ```bash
   git add .
   git commit -m "Stage 0: project setup and language specification"
   ```

---

## Stage 1: Lexer

### What we built
- `flowlang/tokens.py`: the `TokenType` enum (every kind of token), the `KEYWORDS`
  table, and the `Token` dataclass (type, lexeme, line, column, value).
- `flowlang/errors.py`: `CompileError`, the base class for every compiler error, and
  `LexicalError`. Errors print the source line with a caret under the problem.
- `flowlang/lexer.py`: the hand-written scanner.
- A `--tokens` flag that prints the token table, and 28 tests in `tests/`.

### How the lexer works
`tokenize()` loops: skip whitespace and comments, read one token, repeat, then add
an `EOF` token at the end. To read a token, `next_token()` looks at the **first
character** and picks a method:

| First character | Method | Produces |
|---|---|---|
| letter or `_` | `read_word` | keyword (if in `KEYWORDS`) or `IDENTIFIER` |
| digit | `read_number` | `INT_LITERAL` or `FLOAT_LITERAL` |
| `"` | `read_string` | `STRING_LITERAL` |
| anything else | `read_symbol` | operator / punctuation, or a lexical error |

Two small helpers do all the character handling: `peek()` looks at a character
without consuming it, and `advance()` consumes it and updates line and column.

### Concepts (and how to explain them)

**Token vs lexeme.** The token type is the category (`IDENTIFIER`); the lexeme is the
exact text (`temperature`). Literals also carry a value: the lexeme `32.5` is text,
the value `32.5` is a Python float.

**Finite automaton (DFA).** A lexer is a DFA: it is in a state ("reading a number"),
reads a character, and moves to another state or stops. In our code each `read_*`
method is one path through the automaton. For example, `read_number` stays in the
"integer" state while it sees digits, moves to the "float" state on `.` followed by a
digit, and stops at anything else.

**Lookahead.** `peek(1)` looks one character further ahead. After `3` and `.`, the
lexer peeks at the next character to decide whether `3.5` is a valid float or `3.`
is a malformed number.

**Maximal munch.** The lexer always takes the longest possible token. `<=` is one
token, not `<` and `=`; `letter` is one identifier, not `let` + `ter`. For symbols,
this is why two-character symbols are checked before one-character ones.

**Keywords are reserved words.** Words are read the same way, then looked up in
`KEYWORDS`. That's simpler than writing a separate DFA path for each keyword, and
it's what most real lexers do.

**Lexical errors** are found here: invalid characters (`@`, `#`), unterminated strings,
invalid escapes (`\q`), and malformed numbers (`3.`, `3abc`). Every error carries
the line and column where the bad token starts.

### Likely review questions
- *Why does the token list end with EOF?* So the parser can always look at "the
  next token" without checking whether the list has run out.
- *Why is `3abc` an error and not `3` followed by `abc`?* An identifier can't start
  with a digit, so this is almost certainly a typo, and reporting it here gives a
  clearer message than a confusing syntax error later.
- *Why not use regular expressions?* Each token's rules map directly onto a few lines
  of code, which shows how the automaton works. Regex would hide it.

### Exercise
1. Run `.venv/bin/python -m flowlang examples/billing.flow --tokens` and find the
   `ARROW` token and the `FLOAT_LITERAL` tokens. Check that their line:column match
   the file.
2. Add a new operator to the lexer: `^` for "power", as `TokenType.CARET`. You need
   one line in `tokens.py` and one in `lexer.py`. Then add a test like
   `test_two_character_operators_are_one_token` that checks `2 ^ 3` gives
   `[INT_LITERAL, CARET, INT_LITERAL]`. Run the tests. (Remove it afterwards, or keep
   it and we'll add it to the grammar too.)
3. Commit:
   ```bash
   git add . && git commit -m "Stage 1: hand-written lexer with --tokens flag"
   ```

---

## Stage 2: Parser and AST

### What we built
- `flowlang/ast_nodes.py`: one `@dataclass` per construct (`VarDecl`, `IfStmt`,
  `BinaryOp`, ...). All inherit `line` and `column` from `Node`.
- `flowlang/parser.py`: the recursive-descent parser, one `parse_*` method per
  grammar rule.
- `flowlang/ast_printer.py`: draws the tree for the `--ast` flag.
- `ParseError` in `errors.py` (phase "syntax"), and 62 tests in total.

### What the parser does
Two jobs at once: it **checks the grammar** (wrong order of tokens → syntax error)
and **builds the abstract syntax tree**. "Abstract" because punctuation like `;`,
`:` and `( )` doesn't appear in the tree; only the structure and meaning remain.

```
let score: int = 2 + 3 * 4;

VarDecl name='score' type='int'
└── value: BinaryOp op='+'
    ├── left: Literal value=2 type='int'
    └── right: BinaryOp op='*'
        ├── left: Literal value=3 type='int'
        └── right: Literal value=4 type='int'
```

### Concepts (and how to explain them)

**Recursive descent.** Each grammar rule is one method. The parser starts at
`parse_program` and *descends* through the rules: program → statement → expression
→ ... → primary. It is *recursive* because rules contain themselves: a block holds
an `if`, which holds a block; `(` inside an expression calls `parse_expression` again.

| Grammar | Code |
|---|---|
| `"let"` | `self.expect(T.LET, ...)` |
| `rule` | `self.parse_rule()` |
| `( ... )*` | `while self.check(...)` |
| `( ... )?` | `if self.match(...)` |
| `a \| b` | `if`/`elif` on the current token |

**Top-down, LL(1).** Recursive descent is a *top-down* parser: it builds the tree
from the root (Program) down to the leaves. *LL(1)* means it reads the input
**L**eft to right, builds a **L**eftmost derivation, and needs **1** token of
lookahead. In `parse_statement` the first token alone picks the rule: `let` →
declaration, `if` → if-statement, a name → assignment.

**Precedence from the call chain.** Expression methods are ordered from loosest to
tightest: `||` → `&&` → `== !=` → `< > <= >=` → `+ -` → `* / %` → unary → primary.
Each level calls the next one for its operands, so tighter operators are built
first and end up deeper in the tree, which means they are evaluated first. No
precedence table is needed: the grammar *is* the precedence.

**Left associativity from the `while` loop.** In `10 - 4 - 3`, the loop builds
`(10 - 4)` first and then uses that as the left side of `- 3`. So the result is
`(10 - 4) - 3 = 3`, not `10 - (4 - 3) = 9`.

**Left factoring.** A variable and a function call both start with a name. Instead
of guessing, `parse_primary` reads the name, then checks if `(` follows. Rewriting
a grammar so common beginnings are read once is called *left factoring*.

**No left recursion.** A rule like `additive ::= additive "+" multiplicative` would
make `parse_additive` call itself first, forever. Our grammar uses `*` repetition
instead, which becomes a loop. This is why the grammar suits recursive descent.

**Syntax errors.** `expect()` either consumes the required token or raises a
`ParseError` that says what was expected and what was found. A missing `;` is only
noticed at the next token (often on the next line), so `error_missing` points back
to the end of the previous token, where the `;` belongs. The parser stops at the
first syntax error (no error recovery).

### Likely review questions
- *Top-down or bottom-up?* Top-down (recursive descent, LL(1)). Yacc/Bison generate
  bottom-up LALR(1) parsers instead.
- *How do you handle precedence?* One method per precedence level; lower in the
  chain = binds tighter. Show `2 + 3 * 4` with `--ast`.
- *How is `else if` handled?* The `else` branch holds another `IfStmt`, so no special
  node is needed. Show `examples/billing.flow` with `--ast`.
- *Why are parentheses not in the tree?* The tree's shape already shows the grouping:
  `(2 + 3) * 4` puts the `+` under the `*`.
- *What is the difference between a parse tree and an AST?* A parse tree has a node
  for every grammar rule and token, including `;` and `(`. An AST keeps only what
  later phases need.

### Exercise
1. Run `.venv/bin/python -m flowlang examples/billing.flow --ast`. Find the `else if`
   chain and check that it is an `IfStmt` inside another `IfStmt`'s `else_branch`.
2. In `playground.flow`, write `emit (1 + 2) * 3;` and `emit 1 + 2 * 3;`. Compare the
   two trees with `--ast` and explain the difference out loud, as if to your teacher.
3. Break the playground on purpose: delete a `;`, then a `}`, then write
   `turn_on("fan");` without `call`. Read each syntax error and its position.
4. Commit:
   ```bash
   git add . && git commit -m "Stage 2: recursive-descent parser with --ast flag"
   ```

---

## Stage 2½: The `^` power operator

- Added `power ::= primary ( "^" unary )?` between `unary` and `primary`.
- **Right-associative:** `2 ^ 3 ^ 2` is `2 ^ (3 ^ 2)`. Left-associative operators
  use a `while` loop that keeps adding to the *left* side. `parse_power` has no
  loop; its right side calls `parse_unary`, which comes back to `parse_power`, so
  the recursion keeps nesting on the *right*.
- **Precedence:** tighter than `*` and unary `-` (`-2 ^ 2` is `-(2 ^ 2)`), as in maths.
- Type rule: `int ^ int` is an `int`; any float makes it a `float`.

---

## Stage 3: Semantic analysis

### What we built
- `flowlang/symbols.py`: `Symbol` (name, kind, type, parameter types, line, scope)
  and `SymbolTable`, a stack of scopes.
- `flowlang/semantic.py`: the `Analyzer`, which walks the tree and checks the rules
  in section 3 of `docs/language.md`.
- Expression nodes got a `type` field that the analyzer fills in.
- `SemanticError` in `errors.py`, a `--symbols` flag, and 131 tests in total.

### Concepts (and how to explain them)

**Syntax vs semantics.** `let count: int = "five";` has perfect grammar, so the
parser accepts it. It is wrong in *meaning*: a string can't go in an int. Semantic
analysis finds the errors that grammar can't express.

**Symbol table.** A record of every declared name: what kind of thing it is
(variable, parameter, function, event, built-in), its type, and where it was
declared. Show it with `--symbols`.

**Scopes as a stack.** The table is a list of dictionaries. Entering a block pushes
a new dictionary; leaving it pops it, so names declared inside are gone. Lookup
searches from the innermost scope outwards. In `billing.flow`, `--symbols` shows two
`amount`s, a parameter in `fn category` and a later global, with no conflict.

**No shadowing.** A name can't be declared while the same name is visible from an
outer scope. Python scopes are per function, not per block, so allowing shadowing
would make the generated Python behave differently from the FlowLang program.

**Two passes.** Pass 1 only collects function and event names, so they can be used
before their declaration and can call each other (including recursion). Pass 2
checks everything top to bottom.

**Type checking.** Each expression's type is computed bottom-up: leaves first
(a literal knows its type, a variable gets its type from the symbol table), then
each operator combines its operands' types using `binary_result_type`. The only
automatic conversion is int → float (*widening*), checked by `is_compatible`.

**Annotated AST.** The analyzer writes each expression's type into its node. The
code generator needs this: `7 / 2` becomes `7 // 2` in Python only when both sides
are ints.

**Return checking.** A function with a return type must return on every path:
`always_returns` checks that the last statement is a `return`, or an if/else whose
branches all return. An `if` without `else` doesn't count, since it might be skipped.

**Global writes.** When a function or event assigns to a global variable, the
analyzer records it (`global_writes`). In Stage 4 this becomes a Python `global`
statement, without which Python raises `UnboundLocalError`.

### Likely review questions
- *What is a symbol table and how do you handle scopes?* A stack of dictionaries;
  push on entering a block, pop on leaving, look up from the top.
- *Why two passes?* So functions can be called before they are declared, and
  recursive or mutually recursive functions work.
- *Which conversions are implicit?* Only int → float. Float → int would lose data,
  so it is an error.
- *Static or dynamic typing?* Static: every type is known and checked at compile time,
  before the program runs. (Python itself is dynamically typed.)
- *What can't your analyzer detect?* See "known limitations" in `docs/language.md`.

### Exercise
1. Run `.venv/bin/python -m flowlang examples/billing.flow --symbols`. Find the two
   `amount` symbols and explain why they don't conflict.
2. In `playground.flow`, write one program for each of these and read the error:
   - `let x: int = 2.5;` (float → int is not allowed)
   - `let y: float = 2;` (int → float is fine; no error)
   - an `if` block that declares a variable, then use it after the block
   - a function `fn f(x: int) -> int { if x > 0 { return 1; } }`
3. Write a recursive `fn power(base: int, exp: int) -> int` that computes the same
   thing as `^`, and emit `power(2, 10) == 2 ^ 10`. It should pass all checks.
4. Commit:
   ```bash
   git add . && git commit -m "Stage 3: semantic analysis with symbol table and --symbols flag"
   ```

---

## Stage 4: Code generation

### What we built
- `flowlang/codegen.py`: the `CodeGenerator`, which walks the annotated tree and
  writes Python, one method per node type.
- `main.py`: compiling now writes `build/<name>.py`. New flags: `-o` (output file),
  `--python` (print the code), `--run` (compile, then run it).
- `Assign` nodes now also record the variable's type. 168 tests in total; the
  codegen tests compile programs, run the Python, and check what they print.

### Layout of a generated file
1. A header comment saying it was generated.
2. The built-in functions (`turn_on`, `turn_off`): the *runtime support* every
   FlowLang program can use.
3. All functions and events as `def`s, so they exist before anything calls them.
4. The top-level statements, in source order, under `if __name__ == "__main__":`.

### Concepts (and how to explain them)

**Back end and target code.** Lexer, parser and semantic analysis are the *front end*:
they understand FlowLang. Code generation is the *back end*: it produces the *target
language*, here Python source. Because the target is another high-level language,
FlowLang's compiler is a *source-to-source compiler* (transpiler).

**Tree-walking code generation.** Like the semantic checker, the generator visits
every node and has one method per node type. Instead of checking types, each method
writes the Python for its node; statements call `write()` with the current indent.

**Code generation can't fail.** By this phase every error has been found, so the
generator can assume the tree is valid (e.g. every called function exists).

**Using the annotated AST.** The types stored by semantic analysis drive several
decisions: `int / int` → `//`, `int ^ int` → `int(a ** b)`, a widened int → `2.0` or
`float(x)`, and a bool `emit` prints `true`/`false`. Without Stage 3's types, the
generator couldn't make these choices.

**Precedence when generating code.** The tree has no parentheses; its shape is the
grouping. The generator puts parentheses back only where Python needs them. Each
expression method returns its code *and* its operator's precedence, and a parent
wraps a child that binds looser than itself. Two Python quirks need extra care:
`not` binds looser than `==`, and comparisons chain (`a < b == c`). So `!a == b`
becomes `(not a) == b`.

**Semantic gaps between source and target.** The interesting part of a translator is
where the languages differ: blocks vs indentation (`pass` for empty blocks), integer
division, Python's `global` rule, and names that are Python keywords (`class` →
`class_`). Each is handled in one clearly named place in `codegen.py`.

### Likely review questions
- *What does your compiler output?* Python 3 source code. Show `--python`, then `--run`.
- *How do you handle Python's indentation?* An indent counter: `block()` increases it,
  writes the statements, and decreases it. Empty blocks get `pass`.
- *Why does the event have `global alert_count`?* In Python, assigning to a name
  inside a function makes it local, so `alert_count + 1` would fail with
  `UnboundLocalError`. Semantic analysis recorded which globals each event assigns.
- *Why do you need types in the code generator?* `7 / 2` means different things in
  FlowLang (3) and Python (3.5). Only the type tells the generator to use `//`.
- *Did you do optimisation?* No: there's no optimisation phase. Python is the
  target, and its own compiler optimises the bytecode. A possible extension is
  constant folding (computing `2 + 3` at compile time).

### Exercise
1. Run each example with `--python` and then `--run`. For `smart_home.flow`, find the
   `global` line and explain why it's there.
2. In `playground.flow`, write `let a: int = 7;` and `emit a / 2;`, then change `a`
   to a `float`. Look at the generated Python with `--python` each time: one uses
   `//`, the other `/`.
3. Delete `global alert_count` from `build/smart_home.py` by hand and run
   `.venv/bin/python build/smart_home.py`. Read the `UnboundLocalError`: that's the
   bug the compiler protects you from. (Recompile to restore the file.)
4. Commit:
   ```bash
   git add . && git commit -m "Stage 4: Python code generation with --python and --run"
   ```

---

## Stage 4½: Three-address code (intermediate code)

### What we built
- `flowlang/tac.py`: `Quad` (one instruction), `TACUnit` (the code of one function,
  event or the main program), the `TACGenerator`, and two display functions.
- `--tac` prints the TAC; `--quads` prints it as quadruple tables.
- `tests/test_tac.py`, including a small TAC interpreter used only in tests. 192 tests.

### Concepts (and how to explain them)

**Intermediate representation (IR).** A form of the program between the source and
the target. Real compilers (GCC, LLVM) translate to an IR first, because it is
simple, close to machine code, and independent of both the source language and
the target machine. Optimisations are usually done on the IR.

**Three-address code.** Each instruction has at most one operator and at most three
addresses: `result = arg1 op arg2`. Nested expressions are flattened into a sequence
of steps, using **temporaries** for partial results:
`2 + 3 * 4` → `t1 = 3 * 4`, `t2 = 2 + t1`. The order of the instructions follows the
tree from the bottom up, so precedence is already resolved.

**Quadruples.** The record format TAC is stored in: `(op, arg1, arg2, result)`. Our
`Quad` dataclass is exactly that. (Triples are the other textbook format: they drop
the result field and refer to earlier instructions by number instead.)

**Lowering control flow.** TAC has no `if` or loops, only labels and jumps. `if`
becomes `ifFalse cond goto L_else`, the then-part, `goto L_end`, and the else-part.
`repeat` becomes a counter, a comparison, a conditional jump out, and a `goto` back
to the start.

**Short-circuit evaluation.** In `a && b`, if `a` is false the result is false
without looking at `b`. The TAC jumps over `b`'s code. This matters when `b` calls a
function that does something.

**How it was tested.** A small interpreter in `tests/test_tac.py` executes the TAC
instruction by instruction. For every example, the TAC prints exactly the same
output as the generated Python, so both back ends agree on what the program means.

### Likely review questions
- *Why use an intermediate representation?* It separates the front end from the back
  end, it is the natural place for optimisation, and one IR could feed many targets.
- *Is the Python generated from the TAC?* No. Both are generated from the annotated
  AST. Python has structured `if` and loops but no `goto`, so generating it from the
  tree keeps the output readable. TAC shows how the program would be lowered for a
  machine-like target. (Answer this honestly if asked.)
- *What is a temporary?* A compiler-made variable that holds an intermediate result.
- *Quadruples vs triples?* Quadruples name the result explicitly (`t2`); triples
  refer to it by instruction number. Quadruples are easier to reorder and optimise.
- *Where would optimisation go?* On the TAC: constant folding (`t1 = 3 * 4` → `12`),
  copy propagation, and removing dead code like the `goto L2` after `return
  "Premium"` in `billing.flow`, which can never run.

### Exercise
1. Run `.venv/bin/python -m flowlang examples/security.flow --tac` and find the
   `repeat` loop: which temporary is the counter, and which label is the loop's start?
2. In `playground.flow`, write `emit (2 + 3) * (4 - 1);`. Before running `--tac`, write
   the TAC you expect on paper, then compare.
3. Run `--quads` on the same program and match each row to a TAC line.
4. In `billing.flow`'s TAC, find the dead `goto` after a `return`. Explain why it can
   never run.
5. Commit:
   ```bash
   git add . && git commit -m "Add three-address code generation with --tac and --quads"
   ```

---

## Stage 4¾: Code optimisation (optional)

### What we built
- `flowlang/optimizer.py`: seven small passes over the TAC, run repeatedly until
  nothing changes, plus a report of what each pass did.
- `--optimize` / `-O` applies them to `--tac` or `--quads`. Without it, the TAC is
  printed as generated. The Python output doesn't change either way.
- TAC units now record their temporaries, and temporaries skip names the program
  already uses (a variable called `t1` no longer clashes).
- The TAC interpreter moved to `tests/tac_interpreter.py`. 227 tests in total.

### See it
```bash
.venv/bin/python -m flowlang examples/security.flow --tac
.venv/bin/python -m flowlang examples/security.flow --tac --optimize
```
26 → 16 instructions: the `&&` condition is worked out at compile time
(4 >= 3 and not false), so both jumps disappear, and `2 + 3 * 4` becomes `14`.

### Concepts (and how to explain them)

**The golden rule.** An optimisation must not change what the program does. Our
tests run the TAC before and after optimising and check the output is identical.

**Constant folding.** Work out operations on constants at compile time:
`t1 = 3 * 4` → `t1 = 12`. It must use the *source language's* rules (FlowLang's
`7 / 2` is 3), and must not crash the compiler: `1 / 0` is left for run time.

**Constant propagation.** If `x = 5`, a later `t2 = x * 2` can become `t2 = 5 * 2`,
which folding then turns into `10`. The two passes feed each other, which is why the
optimiser repeats all passes until nothing changes (a *fixed point*).

**Basic blocks.** A run of instructions with no labels inside, so it always runs from
top to bottom. Known values are only trusted inside a block: at a label, several
paths meet, possibly with different values, so everything is forgotten.

**Calls.** A called function or event may change global variables, so after a call
only temporaries keep their known values. In `smart_home.flow`, `emit alert_count`
stays as it is: the event changes `alert_count` in between.

**Dead code elimination.** Code that can't run (after `goto`/`return`) or whose
result is never used (an unread temporary) is removed. The program's own variables
are kept, because another function or event might read them.

**Constant conditions.** `ifFalse true goto L` never jumps, so it's removed;
`ifFalse false goto L` always jumps, so it becomes `goto L`. The unused branch then
becomes unreachable and is removed by the next pass.

### Likely review questions
- *How do you know the optimiser is correct?* Tests run the TAC before and after
  optimisation with an interpreter and compare the output, for every example program.
- *Why isn't `emit alert_count` replaced by `emit 0` in smart_home?* The call in
  between may change it; values are forgotten at calls.
- *What is a basic block?* A straight-line sequence of instructions with one entry
  (the first instruction) and one exit (the last).
- *Local or global optimisation?* Local: propagation works within basic blocks.
  Global optimisation would need data-flow analysis across blocks.
- *Does optimisation affect the Python output?* No. The Python is generated from the
  AST, and the optimiser only works on the TAC.

### Exercise
1. Run `security.flow` with `--tac`, then with `--tac --optimize`. For each instruction
   that disappeared, say which pass removed it (use the summary counts as a guide).
2. In `playground.flow`, write `let x: int = 10;`, `emit x / 3 + x % 3;` and check that
   the optimised TAC is `emit 4`.
3. Add `trigger` of an event that changes `x` between the `let` and the `emit`, and
   see that the optimiser no longer folds the emit. Explain why.
4. Commit:
   ```bash
   git add . && git commit -m "Add optional TAC optimiser with --optimize"
   ```
