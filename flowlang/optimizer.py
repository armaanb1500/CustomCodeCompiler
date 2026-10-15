"""Code optimisation: simplifies three-address code without changing what it does.

Used only when asked for (--optimize). Each pass looks for one pattern:

    constant folding         t1 = 3 * 4             ->  t1 = 12
    constant propagation     x = 5 ... t2 = x * 2   ->  t2 = 5 * 2
    constant conditions      ifFalse true goto L1   ->  (removed)
    unreachable code         return x; goto L2      ->  return x
    redundant jumps          goto L2; L2:           ->  L2:
    unused labels            a label nothing jumps to is removed
    unused temporaries       t8 = 14, t8 never read ->  (removed)

The passes run again and again until none of them changes anything, because
one simplification often makes another possible.

The rule for every pass: the optimised code must print exactly the same output.
Known values are only used inside a basic block (between labels), and are
forgotten at a call, because the called function or event may change globals.
"""

import json
import math
from dataclasses import dataclass, field, replace

from flowlang.tac import Quad, TACUnit, tac_literal

JUMPS = ("goto", "if", "ifFalse")
UNARY_OPS = ("uminus", "!", "inttofloat")
NOT_BINARY = ("=", "label", "goto", "if", "ifFalse", "param", "call", "return", "emit") + UNARY_OPS

PASS_NAMES = {
    "fold": "constant folding",
    "propagate": "constant propagation",
    "conditions": "constant conditions",
    "unreachable": "unreachable code removed",
    "redundant_jumps": "redundant jumps removed",
    "labels": "unused labels removed",
    "temps": "unused temporaries removed",
}


@dataclass
class OptimizationReport:
    """How many instructions there were, and how often each pass changed something."""

    before: int = 0
    after: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {name: 0 for name in PASS_NAMES})


# ---- Constants -------------------------------------------------------------


def is_constant(address: str | None) -> bool:
    """Constants start with a digit, a minus sign or a quote, or are true/false."""
    if not address:
        return False
    return address[0] in '"-0123456789' or address in ("true", "false")


def constant_value(address: str) -> int | float | str | bool:
    if address.startswith('"'):
        return json.loads(address)
    if address in ("true", "false"):
        return address == "true"
    try:
        return int(address)
    except ValueError:
        return float(address)


def evaluate(op: str, a, b):
    """Compute `a op b` the way FlowLang does, or None if it shouldn't be folded."""
    both_ints = type(a) is int and type(b) is int
    if op in ("/", "%") and b == 0:
        return None  # leave division by zero for run time; the compiler must not crash
    if op == "/":
        return a // b if both_ints else a / b
    if op == "^":
        if abs(b) > 64:
            return None  # don't build enormous numbers at compile time
        try:
            result = a ** b
        except (OverflowError, ZeroDivisionError):
            return None
        if isinstance(result, complex):
            return None
        return int(result) if both_ints else result
    operations = {
        "+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "%": lambda: a % b,
        "<": lambda: a < b, ">": lambda: a > b, "<=": lambda: a <= b, ">=": lambda: a >= b,
        "==": lambda: a == b, "!=": lambda: a != b,
    }
    return operations[op]()


def fold(quad: Quad) -> Quad | None:
    """If the instruction only uses constants, return `result = <answer>`, else None."""
    if quad.op in UNARY_OPS and is_constant(quad.arg1):
        value = constant_value(quad.arg1)
        answer = {"uminus": lambda: -value, "!": lambda: not value, "inttofloat": lambda: float(value)}[quad.op]()
    elif quad.op not in NOT_BINARY and is_constant(quad.arg1) and is_constant(quad.arg2):
        answer = evaluate(quad.op, constant_value(quad.arg1), constant_value(quad.arg2))
        if answer is None:
            return None
    else:
        return None
    if isinstance(answer, float) and not math.isfinite(answer):
        return None
    return Quad("=", tac_literal(answer), None, quad.result)


def reads(quad: Quad) -> list[str]:
    """The addresses an instruction reads. (A call's arg1 is a function name, not a value.)"""
    if quad.op in ("label", "goto", "call"):
        return []
    return [address for address in (quad.arg1, quad.arg2) if address is not None]


# ---- The passes --------------------------------------------------------------
# Each pass takes a list of instructions and returns (new list, number of changes).


def propagate_and_fold(code: list[Quad], temps: set[str], counts: dict[str, int]) -> tuple[list[Quad], int]:
    """Constant propagation and constant folding, within each basic block."""
    known: dict[str, str] = {}  # address -> constant it currently holds
    result = []
    changes = 0
    for quad in code:
        if quad.op == "label":
            known.clear()  # several paths can arrive here: forget everything
            result.append(quad)
            continue

        # Propagation: replace addresses whose constant value is known.
        if quad.op != "call":
            arg1 = known.get(quad.arg1, quad.arg1) if quad.arg1 else quad.arg1
            arg2 = known.get(quad.arg2, quad.arg2) if quad.arg2 else quad.arg2
            if (arg1, arg2) != (quad.arg1, quad.arg2):
                quad = replace(quad, arg1=arg1, arg2=arg2)
                counts["propagate"] += 1
                changes += 1

        # Folding: compute operations on constants now.
        folded = fold(quad)
        if folded is not None:
            quad = folded
            counts["fold"] += 1
            changes += 1

        # Update what is known.
        if quad.op == "call":
            # The callee may change any global variable: keep only temporaries.
            known = {name: value for name, value in known.items() if name in temps}
        if quad.result is not None and quad.op not in ("label", "goto", "if", "ifFalse"):
            if quad.op == "=" and is_constant(quad.arg1):
                known[quad.result] = quad.arg1
            else:
                known.pop(quad.result, None)
        result.append(quad)
    return result, changes


def simplify_conditions(code: list[Quad]) -> tuple[list[Quad], int]:
    """A conditional jump on a constant either always jumps (goto) or never does (removed)."""
    result = []
    changes = 0
    for quad in code:
        if quad.op in ("if", "ifFalse") and is_constant(quad.arg1):
            jumps = constant_value(quad.arg1) == (quad.op == "if")
            if jumps:
                result.append(Quad("goto", result=quad.result))
            changes += 1
            continue
        result.append(quad)
    return result, changes


def remove_unreachable(code: list[Quad]) -> tuple[list[Quad], int]:
    """Instructions after a goto or return can't run until the next label."""
    result = []
    changes = 0
    reachable = True
    for quad in code:
        if quad.op == "label":
            reachable = True
        if not reachable:
            changes += 1
            continue
        result.append(quad)
        if quad.op in ("goto", "return"):
            reachable = False
    return result, changes


def remove_redundant_jumps(code: list[Quad]) -> tuple[list[Quad], int]:
    """A jump to a label that comes right after it does nothing."""
    result = []
    changes = 0
    for index, quad in enumerate(code):
        if quad.op in JUMPS:
            following_labels = set()
            for later in code[index + 1:]:
                if later.op != "label":
                    break
                following_labels.add(later.result)
            if quad.result in following_labels:
                changes += 1
                continue
        result.append(quad)
    return result, changes


def remove_unused_labels(code: list[Quad]) -> tuple[list[Quad], int]:
    targets = {quad.result for quad in code if quad.op in JUMPS}
    result = [quad for quad in code if quad.op != "label" or quad.result in targets]
    return result, len(code) - len(result)


def remove_unused_temps(code: list[Quad], temps: set[str]) -> tuple[list[Quad], int]:
    """Dead code: a temporary that is never read doesn't need computing.

    Only the compiler's temporaries are removed, never the program's own variables
    (another function or event might read them), and never calls (they do things).
    """
    used = {address for quad in code for address in reads(quad)}
    result = [
        quad for quad in code
        if not (quad.result in temps and quad.result not in used and quad.op != "call")
    ]
    return result, len(code) - len(result)


# ---- Running the passes ------------------------------------------------------


def optimize_unit(unit: TACUnit, counts: dict[str, int]) -> TACUnit:
    code = list(unit.code)
    while True:
        code, propagated = propagate_and_fold(code, unit.temps, counts)
        code, conditions = simplify_conditions(code)
        code, unreachable = remove_unreachable(code)
        code, redundant = remove_redundant_jumps(code)
        code, labels = remove_unused_labels(code)
        code, temps = remove_unused_temps(code, unit.temps)
        counts["conditions"] += conditions
        counts["unreachable"] += unreachable
        counts["redundant_jumps"] += redundant
        counts["labels"] += labels
        counts["temps"] += temps
        if propagated + conditions + unreachable + redundant + labels + temps == 0:
            return replace(unit, code=code)


def optimize(units: list[TACUnit]) -> tuple[list[TACUnit], OptimizationReport]:
    """Return optimised copies of the units (the originals are not changed) and a report."""
    report = OptimizationReport()
    report.before = sum(len(unit.code) for unit in units)
    optimized = [optimize_unit(unit, report.counts) for unit in units]
    report.after = sum(len(unit.code) for unit in optimized)
    return optimized, report


def format_report(report: OptimizationReport) -> str:
    """A short summary of what the optimiser did (printed after the optimised TAC)."""
    lines = [f"Optimisation: {report.before} -> {report.after} instructions"]
    for key, name in PASS_NAMES.items():
        if report.counts[key]:
            lines.append(f"  {name:<28}{report.counts[key]}")
    if len(lines) == 1:
        lines.append("  nothing to optimise")
    return "\n".join(lines)
