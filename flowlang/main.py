"""Command-line entry point for the FlowLang compiler (flowc).

The compiler phases are added stage by stage. Each stage adds a flag that
shows that phase's output, so every phase can be demonstrated on its own.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from flowlang.ast_printer import format_ast
from flowlang.codegen import generate
from flowlang.errors import CompileError
from flowlang.lexer import tokenize
from flowlang.optimizer import format_report, optimize
from flowlang.parser import parse
from flowlang.semantic import analyze
from flowlang.symbols import Symbol
from flowlang.tac import format_quadruples, format_tac, generate_tac
from flowlang.tokens import Token


def read_source(path: Path) -> str:
    """Read a .flow source file, or raise ValueError with a readable message."""
    if path.suffix != ".flow":
        raise ValueError(f"expected a .flow file, got '{path.name}'")
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


def print_tokens(tokens: list[Token]):
    """Print the lexer's output as a table (the --tokens flag)."""
    print(f"{'LINE:COL':<10}{'TYPE':<16}LEXEME")
    for token in tokens:
        position = f"{token.line}:{token.column}"
        print(f"{position:<10}{token.type.name:<16}{token.lexeme}")


def print_symbols(symbols: list[Symbol]):
    """Print the symbol table as a table (the --symbols flag)."""
    rows = [("NAME", "KIND", "TYPE", "SCOPE", "LINE")]
    for symbol in symbols:
        line = str(symbol.line) if symbol.line else "-"
        rows.append((symbol.name, symbol.kind, symbol.describe_type(), symbol.scope, line))

    widths = [max(len(row[i]) for row in rows) + 2 for i in range(4)]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths)]
        print("".join(cells) + row[4])


def main(argv: list[str] | None = None) -> int:
    """Run the compiler. Returns the process exit code (0 = success)."""
    cli = argparse.ArgumentParser(
        prog="flowc",
        description="Compile a FlowLang (.flow) program to Python.",
    )
    cli.add_argument("source", type=Path, help="the .flow file to compile")
    cli.add_argument("--tokens", action="store_true", help="print the tokens from the lexer")
    cli.add_argument("--ast", action="store_true", help="print the syntax tree from the parser")
    cli.add_argument("--symbols", action="store_true", help="print the symbol table from semantic analysis")
    cli.add_argument("--tac", action="store_true", help="print the three-address code (intermediate code)")
    cli.add_argument("--quads", action="store_true", help="print the three-address code as quadruples")
    cli.add_argument("-O", "--optimize", action="store_true", help="optimise the three-address code before printing it")
    cli.add_argument("--python", action="store_true", help="print the generated Python instead of saving it")
    cli.add_argument("--run", action="store_true", help="compile, then run the generated Python")
    cli.add_argument("-o", "--output", type=Path, help="where to save the Python file (default: build/<name>.py)")
    args = cli.parse_args(argv)

    try:
        source = read_source(args.source)
    except ValueError as error:
        print(f"flowc: error: {error}", file=sys.stderr)
        return 1

    # Run the phases in order. The first phase to find an error stops compilation.
    try:
        tokens = tokenize(source)  # Phase 1: lexical analysis
        if args.tokens:
            print_tokens(tokens)
            return 0

        program = parse(tokens)  # Phase 2: syntax analysis
        if args.ast:
            print(format_ast(program))
            return 0

        analysis = analyze(program)  # Phase 3: semantic analysis
        if args.symbols:
            print_symbols(analysis.symbols)
            return 0
    except CompileError as error:
        print(error.format(source), file=sys.stderr)
        return 1

    if args.tac or args.quads or args.optimize:
        units = generate_tac(program, analysis)  # Intermediate code (three-address code)
        report = None
        if args.optimize:
            units, report = optimize(units)  # Optional: code optimisation
        show_tac = args.tac or not args.quads  # --optimize on its own shows the TAC

        if show_tac:
            print(format_tac(units))
        if show_tac and args.quads:
            print()
        if args.quads:
            print(format_quadruples(units))
        if report is not None:
            print()
            print(format_report(report))
        return 0

    python_code = generate(program, analysis)  # Phase 4: code generation
    if args.python:
        print(python_code, end="")
        return 0

    output = args.output or Path("build") / f"{args.source.stem}.py"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(python_code, encoding="utf-8")
    print(f"Compiled {args.source.name} -> {output}", file=sys.stderr if args.run else sys.stdout)

    if args.run:
        # Hand the generated file to the Python interpreter, like running `python file.py`.
        return subprocess.run([sys.executable, str(output)]).returncode
    return 0
