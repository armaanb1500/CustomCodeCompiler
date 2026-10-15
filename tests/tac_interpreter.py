"""A small TAC interpreter, used only by the tests.

It executes three-address code instruction by instruction, so tests can check
that the TAC (optimised or not) prints the same output as the generated Python.
"""

import json


def run_tac(units):
    """Execute TAC instruction by instruction and return the printed lines."""
    by_name = {unit.name: unit for unit in units}
    global_vars = {}
    output = []

    def read(address, local_vars):
        if address.startswith('"'):
            return json.loads(address)
        if address in ("true", "false"):
            return address == "true"
        try:
            return int(address)
        except ValueError:
            pass
        try:
            return float(address)
        except ValueError:
            pass
        return local_vars[address] if address in local_vars else global_vars[address]

    def run_unit(unit, args):
        local_vars = dict(zip(unit.params, args))
        is_main = unit.kind == "main"
        labels = {q.result: i for i, q in enumerate(unit.code) if q.op == "label"}
        params = []
        pc = 0
        while pc < len(unit.code):
            q = unit.code[pc]
            pc += 1
            if q.op == "label":
                continue
            if q.op == "goto":
                pc = labels[q.result]
                continue
            if q.op in ("if", "ifFalse"):
                if read(q.arg1, local_vars) == (q.op == "if"):
                    pc = labels[q.result]
                continue
            if q.op == "param":
                params.append(read(q.arg1, local_vars))
                continue
            if q.op == "return":
                return read(q.arg1, local_vars) if q.arg1 else None
            if q.op == "emit":
                value = read(q.arg1, local_vars)
                output.append(str(value).lower() if isinstance(value, bool) else str(value))
                continue

            if q.op == "call":
                args, params = params, []
                if q.arg1 in ("turn_on", "turn_off"):
                    output.append(f"[{args[0]} switched {q.arg1[5:]}]")
                    value = None
                else:
                    value = run_unit(by_name[q.arg1], args)
                if q.result is None:
                    continue
            elif q.op == "=":
                value = read(q.arg1, local_vars)
            elif q.op == "uminus":
                value = -read(q.arg1, local_vars)
            elif q.op == "!":
                value = not read(q.arg1, local_vars)
            elif q.op == "inttofloat":
                value = float(read(q.arg1, local_vars))
            else:
                value = binary(q.op, read(q.arg1, local_vars), read(q.arg2, local_vars))

            # Main writes globals. Elsewhere, an existing global is updated; anything else is local.
            if is_main or (q.result in global_vars and q.result not in local_vars):
                global_vars[q.result] = value
            else:
                local_vars[q.result] = value
        return None

    run_unit(units[-1], [])
    return output


def binary(op, a, b):
    both_ints = type(a) is int and type(b) is int
    if op == "/":
        return a // b if both_ints else a / b
    if op == "^":
        return int(a ** b) if both_ints else a ** b
    operations = {
        "+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "%": lambda: a % b,
        "<": lambda: a < b, ">": lambda: a > b, "<=": lambda: a <= b, ">=": lambda: a >= b,
        "==": lambda: a == b, "!=": lambda: a != b,
    }
    return operations[op]()
