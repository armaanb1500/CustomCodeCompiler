# FlowLang: presentation guide

Everything you need for the review: what the project is, how every part works,
the order to present it in, and answers to likely questions.

All commands are run from the project folder:

```bash
cd ~/Documents/FlowLang
```

---

## 1. FlowLang in one minute

**What it is.** FlowLang is a small domain-specific language (DSL) for
event-driven rules, like "when the sensors update, if it's hot, turn on the fan".
`flowc` is its compiler: it checks a `.flow` program for errors and translates it
into Python.

**Who it's for.** People who need to write automation rules (smart homes, IoT
devices, alerts, simple workflows) without learning a full programming language.
It's in the same family as Home Assistant automations or IFTTT rules. In this
project the devices are simulated, because the focus is the compiler.

**How it's built.** In Python, using only the standard library. The lexer and
parser are hand-written (no Lex/Yacc), so every phase is ordinary code that can be
read and explained. 233 automated tests check every phase.

---

## 2. The big picture

A compiler is a pipeline of phases. Each phase takes the previous phase's output,
transforms it, and passes it on. The first error found stops compilation.

```
 .flow source text
       │
       ▼
 1. Lexical analysis      lexer.py       characters  → tokens             --tokens
       │
       ▼
 2. Syntax analysis       parser.py      tokens      → syntax tree (AST)  --ast
       │
       ▼
 3. Semantic analysis     semantic.py    AST         → annotated AST      --symbols
       │                                 + symbol table
       ├──────────────────────────────┐
       ▼                              ▼
 4. Intermediate code     tac.py      6. Code generation   codegen.py
    three-address code    --tac          annotated AST → Python    --python
       │                  --quads               │
       ▼                                        ▼
 5. Optimisation (optional)               7. Execution               --run
    optimizer.py          --tac -O          runs the generated Python
```

**Front end vs back end.** Phases 1–3 are the *front end*: they understand and
check FlowLang. Phases 4–6 are the *back end*: they produce output. Errors can only
be found in the front end; by the back end, the program is known to be valid.

**Two outputs from the annotated tree.** The TAC and the Python are both generated
from the checked tree. Python has no `goto`, so generating it from the tree keeps it
readable; the TAC shows how the program is lowered for a machine-like target and is
where optimisation happens. Say this plainly if asked.

---

## 3. One program through every phase

`examples/demo.flow` (after two comment lines at the top, so `program` is on line 3):

```
program Demo {
    let temperature: float = 32.5;

    event check {
        if temperature > 30.0 {
            call turn_on("fan");
        }
    }

    let score: int = 2 + 3 * 4;
    trigger check;
    emit score;
}
```

### Phase 1: Lexical analysis (`lexer.py`, `tokens.py`)

**Job:** group characters into **tokens**, the "words" of the language. Spaces and
comments are thrown away.

```bash
.venv/bin/python -m flowlang examples/demo.flow --tokens | head -12
```
```
LINE:COL  TYPE            LEXEME
3:1       PROGRAM         program
3:9       IDENTIFIER      Demo
3:14      LBRACE          {
4:5       LET             let
4:9       IDENTIFIER      temperature
4:20      COLON           :
4:22      FLOAT           float
4:28      EQUAL           =
4:30      FLOAT_LITERAL   32.5
4:34      SEMICOLON       ;
```

**How it works.** `next_token()` looks at the first character of each token and
picks a method: a letter → `read_word` (then the `KEYWORDS` table decides keyword or
identifier), a digit → `read_number`, a quote → `read_string`, anything else →
`read_symbol`. Each method keeps reading while the characters still fit.

**Terms to use:**
- *token* (the category, `IDENTIFIER`) vs *lexeme* (the text, `temperature`)
- *finite automaton (DFA)*: each `read_*` method is one path through it
- *lookahead*: `peek()` looks at the next character without consuming it
- *maximal munch*: always take the longest token, so `>=` is one token and
  `letter` is not `let` + `ter`

**Errors caught:** invalid characters (`@`), unterminated strings, malformed numbers
(`3.`, `3abc`).

### Phase 2: Syntax analysis (`parser.py`, `ast_nodes.py`)

**Job:** check the tokens follow the grammar, and build the **abstract syntax tree**.

```bash
.venv/bin/python -m flowlang examples/demo.flow --ast
```
```
├── VarDecl name='score' type='int'
│   └── value: BinaryOp op='+'
│       ├── left: Literal value=2 type='int'
│       └── right: BinaryOp op='*'
│           ├── left: Literal value=3 type='int'
│           └── right: Literal value=4 type='int'
```

**How it works.** A *recursive-descent* parser: each grammar rule in
`docs/language.md` is one `parse_*` method, and they call each other the way the
rules refer to each other. It decides which rule applies by looking at the current
token only (*LL(1)*).

**Precedence:** the `*` is *deeper* in the tree than the `+`, so it's calculated
first. This comes from the call chain: `parse_additive` calls `parse_multiplicative`
for its operands, so multiplication is built first. Lower in the chain = binds
tighter. The `while` loops make operators left-associative (`10 - 4 - 3` is
`(10 - 4) - 3`); `^` is right-associative and uses recursion instead.

**Terms:** recursive descent, top-down, LL(1), left factoring (a name is read first,
then `(` decides variable vs call), no left recursion, abstract vs parse tree.

**Errors caught:** missing `;`, missing `}`, missing types, misplaced keywords.

### Phase 3: Semantic analysis (`semantic.py`, `symbols.py`)

**Job:** check the program *makes sense*: names exist, types match, calls are right.

```bash
.venv/bin/python -m flowlang examples/demo.flow --symbols
```
```
NAME         KIND      TYPE      SCOPE   LINE
turn_on      builtin   (string)  global  -
turn_off     builtin   (string)  global  -
check        event     -         global  6
temperature  variable  float     global  4
score        variable  int       global  12
```
(For scopes, `examples/billing.flow --symbols` is better: it shows two different
`amount`s, a parameter inside `fn category` and a later global.)

**How it works.**
- The **symbol table** is a stack of dictionaries, one per scope. Entering a block
  pushes one, leaving pops it, and a lookup searches from the innermost outwards.
- **Two passes:** pass 1 collects every function and event name, so they can be used
  before they are declared; pass 2 checks every statement in order.
- **Type checking** works bottom-up: a literal knows its type, a variable gets its type
  from the symbol table, and each operator combines its operands' types using
  `binary_result_type()`. The only automatic conversion is int → float.
- It writes each expression's type into the tree (an **annotated AST**) and records
  which globals each event/function assigns. The back end needs both.

**Errors caught:** undeclared or redeclared names, type mismatches, wrong argument
count or types, `return` outside a function, missing returns, `trigger` on a
non-event.

### Phase 4: Intermediate code (`tac.py`)

**Job:** lower the program to **three-address code**: at most one operation per
instruction, with temporaries for partial results, and jumps instead of `if`/loops.

```bash
.venv/bin/python -m flowlang examples/demo.flow --tac
```
```
event check:
    t1 = temperature > 30.0
    ifFalse t1 goto L1
    param "fan"
    call turn_on, 1
  L1:

main Demo:
    temperature = 32.5
    t2 = 3 * 4
    t3 = 2 + t2
    score = t3
    call check, 0
    emit score
```

**How it works.** Each expression method adds its instructions and returns the
*address* holding its value (a constant, a name, or a new temporary `t1, t2, ...`).
`if` becomes `ifFalse ... goto`, `repeat` becomes a counter and a jump back, and
`&&`/`||` jump over their right side when the left side already decides the result
(*short-circuit evaluation*).

`--quads` shows the same instructions as **quadruples** `(op, arg1, arg2, result)`,
which is how they are stored.

### Phase 5: Optimisation, optional (`optimizer.py`)

**Job:** make the TAC do less work **without changing what it prints**.

```bash
.venv/bin/python -m flowlang examples/demo.flow --tac -O
```
```
main Demo:
    temperature = 32.5
    score = 14
    call check, 0
    emit score

Optimisation: 11 -> 9 instructions
  constant folding            2
  constant propagation        2
  unused temporaries removed  2
```

**Passes** (repeated until nothing changes): constant folding (`3 * 4` → `12`),
constant propagation (a known value replaces its name), constant conditions,
unreachable code after `goto`/`return`, redundant jumps, unused labels, unused
temporaries.

**Safety rule, worth pointing out:** `emit score` was *not* turned into `emit 14`,
because `call check` runs in between and could change globals. Known values are
forgotten at every call and at every label (where several paths meet). Values are
only trusted inside a *basic block*.

**Best demos:** `security.flow` (26 → 16: the whole `&&` condition is decided at
compile time) and `smart_home.flow` ("nothing to optimise", correctly, because the
event changes `alert_count`).

### Phase 6: Code generation (`codegen.py`)

**Job:** write the equivalent Python, walking the annotated tree.

```bash
.venv/bin/python -m flowlang examples/demo.flow --python
```
```python
def check() -> None:
    if temperature > 30.0:
        turn_on('fan')


if __name__ == "__main__":
    temperature: float = 32.5
    score: int = 2 + 3 * 4
    check()
    print(score)
```

**How it works.** One method per node type; an indent counter handles Python's
indentation. Functions and events are written before the main code, so they exist
when called. Where FlowLang and Python differ, the generator adapts:

| Difference | Handling |
|---|---|
| `{ }` blocks vs indentation | indent counter; `pass` for empty blocks |
| FlowLang `7 / 2` is 3, Python's is 3.5 | uses the types from phase 3: `int / int` → `//` |
| Python's `not` and chained comparisons | adds parentheses only where needed |
| assigning a global inside a function | adds `global x` (see `smart_home.flow`) |
| names like `class` or `print` | renamed to `class_`, `print_` |
| int stored in a float | written as `2.0` or `float(x)` |

### Phase 7: Execution

```bash
.venv/bin/python -m flowlang examples/demo.flow --run
```
```
[fan switched on]
14
```
The generated file is saved in `build/` and run with the Python interpreter.

### Errors, phase by phase

```bash
.venv/bin/python -m flowlang examples/errors/lexical_error.flow       # '@' is not a valid character
.venv/bin/python -m flowlang examples/errors/syntax_error.flow        # missing ';'
.venv/bin/python -m flowlang examples/errors/type_mismatch.flow       # string stored in an int
.venv/bin/python -m flowlang examples/errors/undeclared_variable.flow # 'humidity' never declared
.venv/bin/python -m flowlang examples/errors/wrong_argument_count.flow
```
```
semantic error at line 4, column 8: 'humidity' is not declared
   4 |     if humidity > 80.0 {
     |        ^
```
Every error names its phase and shows the line, column and a caret. A missing `;` is
reported at the end of the line where it belongs, not on the next line.

---

## 4. Where everything lives

| File | Phase | One line |
|---|---|---|
| `flowlang/tokens.py` | 1 | Token types, keyword table, `Token` class |
| `flowlang/lexer.py` | 1 | The scanner: characters → tokens |
| `flowlang/ast_nodes.py` | 2 | Node classes of the tree (`VarDecl`, `IfStmt`, `BinaryOp`, ...) |
| `flowlang/parser.py` | 2 | Recursive-descent parser: tokens → tree |
| `flowlang/ast_printer.py` | 2 | Draws the tree for `--ast` |
| `flowlang/symbols.py` | 3 | Symbol table: a stack of scopes |
| `flowlang/semantic.py` | 3 | Name and type checks; annotates the tree |
| `flowlang/tac.py` | 4 | Three-address code and quadruples |
| `flowlang/optimizer.py` | 5 | Optional optimisation passes |
| `flowlang/codegen.py` | 6 | Annotated tree → Python |
| `flowlang/errors.py` | all | Error classes with line, column and caret display |
| `flowlang/main.py` | all | Command line: runs the phases in order, handles flags |
| `docs/language.md` | | The language specification, including the grammar (EBNF) |
| `examples/` | | Example programs; `examples/errors/` has one error each |
| `tests/` | | 233 tests, one file per phase |

**Code to know by heart**, in case you're asked to show it:
- `lexer.py` → `next_token()`: picks the token kind from the first character
- `parser.py` → `parse_additive()` / `parse_multiplicative()`: where precedence comes from
- `symbols.py` → `enter_scope`, `exit_scope`, `lookup`: the scope stack
- `semantic.py` → `binary_result_type()`: the typing rules in ~20 lines
- `codegen.py` → `body()`: where `global` lines are added

---

## 5. Presentation flow (about 10 minutes)

**Setup before you start:** large terminal font; `cd ~/Documents/FlowLang`; run
`.venv/bin/python -m pytest -q` once to be sure it works; `clear`. Open VS Code with
`examples/demo.flow`, `playground.flow` and `docs/language.md` in tabs.

| # | Time | Show | Command | Say |
|---|---|---|---|---|
| 1 | 1 min | README diagram | | "FlowLang is a DSL for event-driven rules. My compiler checks a program in three phases, generates three-address code with optional optimisation, and translates it to Python. Lexer and parser are hand-written." |
| 2 | 30 s | `examples/demo.flow` | | "A short program with a variable, an event, an `if`, a built-in call and an expression. I'll follow it through every phase." |
| 3 | 1 min | Tokens | `--tokens \| head -12` | Tokens vs lexemes, positions, maximal munch. |
| 4 | 1 min | Tree | `--ast` | "The `*` is under the `+`, so it's calculated first. That's precedence from recursive descent." |
| 5 | 1 min | Symbol table | `examples/billing.flow --symbols` | "Two `amount`s in different scopes. Scopes are a stack." |
| 6 | 1 min | Errors | the three error files | "Each phase catches its own kind of error, with line and column." |
| 7 | 1 min | TAC | `--tac` (then optionally `--quads`) | "One operation per instruction; `if` becomes a conditional jump." |
| 8 | 1 min | Optimisation | `--tac -O`, then `examples/smart_home.flow --tac -O` | "Folded `2 + 3 * 4` to 14. In smart_home it changes nothing, correctly: the event changes `alert_count`." |
| 9 | 1 min | Python + run | `examples/smart_home.flow --python`, then `--run` | "It added `global alert_count` because the event changes a global. And it runs." |
| 10 | 1 min | Live change | type into `playground.flow` (below), `--run` | Show an error, fix it, run it. Proves nothing is pre-recorded. |
| 11 | 30 s | Tests | `.venv/bin/python -m pytest -q` | "233 tests. The TAC and optimiser tests run the intermediate code and check it prints the same as the Python." |

All commands start with `.venv/bin/python -m flowlang`, except the tests.

**Live change (step 10).** Type this, run it, read the error out loud:
```
program Live {
    fn square(x: int) -> int {
        return x * x;
    }
    let result: int = square(2.5);
    emit result;
}
```
"Semantic error: 2.5 is a float, but `square` takes an int." Change `2.5` to `7`,
save, run again → `49`.

**Closing line:** "So FlowLang goes through every phase of a compiler: lexical, syntax,
semantic, intermediate code, optional optimisation and code generation, and each
phase can be shown on its own."

**If your teacher gives you their own program:** type it into `playground.flow`, run
`--run`. If it fails, explain which phase caught the error and why, since a correct
error is also a working compiler. Then show `--tokens`, `--ast`, `--tac` on it.

---

## 6. Questions and answers

**About the design**

- **Why hand-written instead of Lex/Yacc?** The grammar is LL(1), so each rule maps
  directly to one function, which makes every step visible. GCC and Clang also use
  hand-written parsers, mainly for better error messages.
- **Top-down or bottom-up parser?** Top-down: recursive descent, LL(1). Yacc/Bison
  generate bottom-up LALR(1) parsers.
- **What does LL(1) mean?** Reads input **L**eft to right, builds a **L**eftmost
  derivation, needs **1** token of lookahead.
- **Why is your grammar suitable for recursive descent?** No left recursion
  (repetition uses `*`, which becomes a loop), and it's left-factored.
- **What's the difference between a parse tree and an AST?** A parse tree has a node
  for every rule and token, including `;` and `(`. The AST keeps only the structure
  later phases need.
- **Static or dynamic typing?** Static: every type is checked at compile time, even
  though the target, Python, is dynamically typed.
- **Which conversions are automatic?** Only int → float. Float → int could lose data,
  so it's an error.
- **Why no shadowing?** Python scopes are per function, not per block, so allowing an
  inner variable to hide an outer one would make the Python behave differently.
- **Why two passes in semantic analysis?** So functions and events can be used before
  they are declared, including recursion.

**About the back end**

- **Is the Python generated from the TAC?** No, both come from the annotated tree.
  Python has no `goto`, so generating it from the tree keeps it readable.
- **Why use an intermediate representation at all?** It separates front end and back
  end, it's where optimisation happens, and one IR could feed several targets.
- **Quadruples vs triples?** Quadruples name the result (`t2`); triples refer to it by
  instruction number. Quadruples are easier to reorder and optimise.
- **How do you know the optimiser is correct?** The tests run the TAC before and after
  optimisation with an interpreter and check the output is identical.
- **What is a basic block?** A straight-line run of instructions with one entry and
  one exit. Our optimiser trusts known values only inside one.
- **Local or global optimisation?** Local (within basic blocks). Global would need
  data-flow analysis across blocks.
- **Why is there a `global` line in the generated Python?** Assigning a name inside a
  Python function makes it local, so `alert_count + 1` would crash with
  `UnboundLocalError`. Semantic analysis recorded which globals each event assigns.
- **Why does the code generator need types?** `7 / 2` is 3 in FlowLang but 3.5 in
  Python. Only the type tells it to use `//`.

**About the project**

- **How is it tested?** 233 pytest tests, one file per phase, plus whole-program tests
  that compile, run and check output.
- **Did you use AI?** Answer honestly. What matters is that you can explain and change
  the code, which the live change demonstrates.
- **Where could it be used?** Automation rules for smart homes, IoT devices, alerts or
  workflows, by people who aren't programmers.

---

## 7. Limitations and future work

Say these yourself before you're asked; it shows you understand the project.

**Limitations**
- No `while` loops, arrays, user input, or mixing strings with numbers.
- Devices are simulated: `turn_on` prints a message.
- Compilation stops at the first error (no error recovery).
- The optimiser is local (basic blocks only), and Python is generated from the tree,
  not from the optimised TAC.
- Triggering an event before a global it uses has been assigned is not detected at
  compile time (it fails at run time with `NameError`).

**Future work**
- Error recovery to report several errors at once.
- `while` loops, lists, and input.
- Global optimisation with data-flow analysis.
- Connecting built-ins to a real smart-home API and firing events from real sensors.
- A web playground showing each phase in tabs.

---

## 8. Checklist and backup plan

**The night before / morning of**
- [ ] Run the full demo once, out loud, timing it.
- [ ] Run `.venv/bin/python -m pytest -q` on the machine you'll present on.
- [ ] Practise writing one small program from scratch in `playground.flow`.
- [ ] Re-read section 6.

**If something goes wrong during the demo**
- Stay calm and run the tests: they show everything else works. Then explain what the
  failing command should have shown, using this guide.
- If a file is in a strange state: `git checkout -- playground.flow` restores it.
- Every example's expected output is in `tests/test_codegen.py` (`EXPECTED_OUTPUT`).

---

## 9. FlowLang quick reference

```
program Name {                              // every program
    let x: int = 5;                         // types: int, float, bool, string
    x = x + 1;                              // assignment: no let, no type
    emit x;                                 // output

    if x > 3 { ... } else if x > 1 { ... } else { ... }
    repeat 3 { ... }                        // the only loop

    fn add(a: int, b: int) -> int { return a + b; }
    fn log(msg: string) { emit msg; }       // no "->": returns nothing
    let total: int = add(2, 3);             // call inside an expression
    call log("hi");                         // call as a statement

    event alarm { call turn_on("siren"); }  // built-ins: turn_on, turn_off
    trigger alarm;                          // fire an event
}
```

Operators, loosest to tightest: `||`, `&&`, `== !=`, `< > <= >=`, `+ -`, `* / %`,
unary `! -`, `^`. Remember: `;` after every statement, braces always required,
`int / int` gives a whole number, `call` for statement calls, `trigger` for events.
