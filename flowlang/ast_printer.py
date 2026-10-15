"""Draws an AST as a text tree (the --ast flag).

    Program name='Demo'
    └── VarDecl name='x' type='int'
        └── value: BinaryOp op='+'
            ├── left: Literal value=2 type='int'
            └── right: Literal value=3 type='int'

For each node, plain fields (names, types, operators) go on the node's own
line, and fields holding other nodes become its children. Drawing a child
calls the same function again: a tree is drawn recursively.
"""

from dataclasses import fields

from flowlang.ast_nodes import Node

POSITION_FIELDS = ("line", "column")


def format_ast(root: Node) -> str:
    """Return the whole tree as a multi-line string."""
    lines = [node_label(root)]
    add_children(root, "", lines)
    return "\n".join(lines)


def node_label(node: Node) -> str:
    """The node's class name plus its plain fields, e.g. VarDecl name='x' type='int'.

    Fields that are None (no else branch, no type yet) are left out.
    """
    parts = [type(node).__name__]
    for field in fields(node):
        value = getattr(node, field.name)
        if field.name in POSITION_FIELDS or value is None or isinstance(value, (Node, list)):
            continue
        parts.append(f"{field.name}={value!r}")
    return " ".join(parts)


def child_nodes(node: Node) -> list[tuple[str | None, Node]]:
    """The node's children as (field name, child) pairs.

    Single children are labelled with their field name ("condition: ...").
    Items of a list (statements, arguments) are not labelled.
    """
    children = []
    for field in fields(node):
        value = getattr(node, field.name)
        if isinstance(value, Node):
            children.append((field.name, value))
        elif isinstance(value, list):
            children.extend((None, item) for item in value)
    return children


def add_children(node: Node, prefix: str, lines: list[str]):
    """Append one line per child (and, recursively, the child's children)."""
    children = child_nodes(node)
    for index, (field_name, child) in enumerate(children):
        is_last = index == len(children) - 1
        branch = "└── " if is_last else "├── "
        label = node_label(child) if field_name is None else f"{field_name}: {node_label(child)}"
        lines.append(prefix + branch + label)
        # Children of the last child need no vertical line on their left.
        add_children(child, prefix + ("    " if is_last else "│   "), lines)
