"""
Visual Python - a node-graph editor (Unreal-Blueprint style) that lets you build
Python programs by connecting nodes with wires instead of typing code.

Run:  python visual_python.py        (needs Python with Tkinter; cross-platform)

Basics:
  - Add nodes from the left NODES palette (double-click) or right-click canvas.
  - Drag a node by its title bar to move it.
  - Drag from an OUTPUT pin (right side) to an INPUT pin (left side) to wire them.
    White triangle pins = the order things run.   Blue round pins = a value.
  - Double-click a node to edit all its settings in one popup.
  - Select a node and press Delete to remove it.
  - Press Run. Every program starts at the green Start node.

Beginner mode (on by default) hides the advanced extras: the Debug button,
clickable code breakpoints, and wire reroute points. Untick it to reveal them.
"""

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog
import io
import os
import sys
import json
import contextlib
import traceback
import platform


def _platform_fonts():
    """Pick fonts that exist on the current OS (Tk falls back otherwise)."""
    s = platform.system()
    if s == "Windows":
        return "Segoe UI", "Consolas"
    if s == "Darwin":
        return "Helvetica Neue", "Menlo"
    return "DejaVu Sans", "DejaVu Sans Mono"


UI_FONT, MONO_FONT = _platform_fonts()

__version__ = "1.0.0"

# ----------------------------------------------------------------------------
# Layout / theme constants
# ----------------------------------------------------------------------------
NODE_W = 180
HEADER_H = 26
PROP_H = 18
ROW_H = 24
PIN_R = 6
KNOT_R = 5
STEP_LIMIT = 2_000_000          # safety net against infinite loops

COL_BG = "#1e1f26"
COL_GRID = "#272832"
COL_NODE = "#2d2f3a"
COL_NODE_SEL = "#3a3d4d"
COL_TEXT = "#e6e6e6"
COL_EXEC = "#f4f4f4"
COL_DATA = "#4ea1ff"
COL_WIRE_EXEC = "#cfcfcf"
COL_WIRE_DATA = "#4ea1ff"

# category key -> (palette/header label, header colour). Order = palette order.
CATEGORY_META = [
    ("event", "Events", "#4caf50"),
    ("flow", "Flow", "#7e57c2"),
    ("var", "Variables", "#5c6bc0"),
    ("value", "Values", "#3f7fb0"),
    ("math", "Math", "#ef6c00"),
    ("logic", "Logic", "#00897b"),
    ("text", "Text", "#c2185b"),
    ("list", "Lists", "#8d6e63"),
    ("io", "Input / Output", "#26a69a"),
]
CATEGORY_COLORS = {k: c for k, _, c in CATEGORY_META}
CATEGORY_LABELS = {k: lbl for k, lbl, _ in CATEGORY_META}


# ----------------------------------------------------------------------------
# Model: Pins, Wires, Nodes
# ----------------------------------------------------------------------------
class Pin:
    def __init__(self, node, name, direction, kind, default=None):
        self.node = node
        self.name = name
        self.direction = direction      # 'in' or 'out'
        self.kind = kind                # 'exec' or 'data'
        self.default = default          # expression used when an input is unwired
        self.wx = 0.0
        self.wy = 0.0


class Wire:
    def __init__(self, src, dst):
        self.src = src                  # output pin
        self.dst = dst                  # input pin
        self.points = []                # reroute knots (world coords) src->dst


_NODE_ID = 0


def _next_id():
    global _NODE_ID
    _NODE_ID += 1
    return _NODE_ID


class Node:
    type_name = "node"
    title = "Node"
    category = "value"

    def __init__(self, x=60, y=60):
        self.id = _next_id()
        self.x = float(x)
        self.y = float(y)
        self.height = HEADER_H
        self.inputs = []
        self.outputs = []
        self.props = dict(self.default_props())
        self.build_pins()

    def default_props(self):
        return {}

    def prop_specs(self):
        return []

    def prop_choices(self):
        return {}

    def build_pins(self):
        pass

    def summary(self):
        return ""

    def imports(self):
        return ()

    def emit(self, gen, indent):
        pass

    def expr(self, gen, pin):
        raise NotImplementedError(f"{self.type_name} has no expr()")

    def add_in(self, name, kind, default=None):
        p = Pin(self, name, "in", kind, default)
        self.inputs.append(p)
        return p

    def add_out(self, name, kind):
        p = Pin(self, name, "out", kind)
        self.outputs.append(p)
        return p

    def pin(self, name):
        for p in self.inputs + self.outputs:
            if p.name == name:
                return p
        raise KeyError(name)

    def layout(self):
        rows = max(len(self.inputs), len(self.outputs), 1)
        top = self.y + HEADER_H + (PROP_H if self.summary() else 0)
        for i, p in enumerate(self.inputs):
            p.wx = self.x
            p.wy = top + i * ROW_H + ROW_H / 2
        for i, p in enumerate(self.outputs):
            p.wx = self.x + NODE_W
            p.wy = top + i * ROW_H + ROW_H / 2
        self.height = (HEADER_H + (PROP_H if self.summary() else 0)
                       + rows * ROW_H + 8)

    def contains(self, wx, wy):
        return (self.x <= wx <= self.x + NODE_W
                and self.y <= wy <= self.y + self.height)

    def in_header(self, wx, wy):
        return (self.x <= wx <= self.x + NODE_W
                and self.y <= wy <= self.y + HEADER_H)


def _ident(name, fallback="var"):
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in name.strip())
    if not out or out[0].isdigit():
        out = "_" + out
    return out or fallback


# ----------------------------------------------------------------------------
# Concrete node types
# ----------------------------------------------------------------------------
class StartNode(Node):
    type_name = "start"
    title = "Start"
    category = "event"

    def build_pins(self):
        self.add_out("Then", "exec")

    def emit(self, gen, indent):
        gen.follow(self.pin("Then"), indent)


class PrintNode(Node):
    type_name = "print"
    title = "Print"
    category = "io"

    def build_pins(self):
        self.add_in("In", "exec")
        self.add_in("Value", "data", default='""')
        self.add_out("Then", "exec")

    def emit(self, gen, indent):
        gen.line(indent, f"print({gen.expr(self.pin('Value'))})")
        gen.follow(self.pin("Then"), indent)


class InputNode(Node):
    type_name = "input"
    title = "Ask (Input)"
    category = "io"

    def default_props(self):
        return {"prompt": "Enter a value: "}

    def prop_specs(self):
        return [("prompt", "Prompt text")]

    def build_pins(self):
        self.add_out("Value", "data")

    def summary(self):
        return repr(self.props["prompt"])

    def expr(self, gen, pin):
        return f"input({self.props['prompt']!r})"


class ConvertNode(Node):
    type_name = "convert"
    title = "Convert"
    category = "io"

    FUNCS = ["int", "float", "str"]

    def default_props(self):
        return {"func": "int"}

    def prop_specs(self):
        return [("func", "Convert to")]

    def prop_choices(self):
        return {"func": self.FUNCS}

    def build_pins(self):
        self.add_in("Value", "data", default='""')
        self.add_out("Result", "data")

    def summary(self):
        return f"{self.props['func']}( ... )"

    def expr(self, gen, pin):
        func = self.props["func"] if self.props["func"] in self.FUNCS else "int"
        return f"{func}({gen.expr(self.pin('Value'))})"


class NumberNode(Node):
    type_name = "number"
    title = "Number"
    category = "value"

    def default_props(self):
        return {"value": "0"}

    def prop_specs(self):
        return [("value", "Number value")]

    def build_pins(self):
        self.add_out("Value", "data")

    def summary(self):
        return str(self.props["value"])

    def expr(self, gen, pin):
        v = str(self.props["value"]).strip()
        try:
            float(v)
            return v
        except ValueError:
            return "0"


class StringNode(Node):
    type_name = "string"
    title = "Text"
    category = "value"

    def default_props(self):
        return {"text": "hello"}

    def prop_specs(self):
        return [("text", "Text value")]

    def build_pins(self):
        self.add_out("Value", "data")

    def summary(self):
        return repr(self.props["text"])

    def expr(self, gen, pin):
        return repr(self.props["text"])


class BoolNode(Node):
    type_name = "bool"
    title = "True / False"
    category = "value"

    def default_props(self):
        return {"value": "True"}

    def prop_specs(self):
        return [("value", "Value")]

    def prop_choices(self):
        return {"value": ["True", "False"]}

    def build_pins(self):
        self.add_out("Value", "data")

    def summary(self):
        return self.props["value"]

    def expr(self, gen, pin):
        return "True" if str(self.props["value"]) == "True" else "False"


class VarGetNode(Node):
    type_name = "var_get"
    title = "Get Variable"
    category = "var"

    def default_props(self):
        return {"name": "x"}

    def prop_specs(self):
        return [("name", "Variable name")]

    def build_pins(self):
        self.add_out("Value", "data")

    def summary(self):
        return _ident(self.props["name"])

    def expr(self, gen, pin):
        return _ident(self.props["name"])


class VarSetNode(Node):
    type_name = "var_set"
    title = "Set Variable"
    category = "var"

    def default_props(self):
        return {"name": "x"}

    def prop_specs(self):
        return [("name", "Variable name")]

    def build_pins(self):
        self.add_in("In", "exec")
        self.add_in("Value", "data", default="0")
        self.add_out("Then", "exec")

    def summary(self):
        return _ident(self.props["name"]) + " = ..."

    def emit(self, gen, indent):
        name = _ident(self.props["name"])
        gen.line(indent, f"{name} = {gen.expr(self.pin('Value'))}")
        gen.follow(self.pin("Then"), indent)


class MathNode(Node):
    type_name = "math"
    title = "Math"
    category = "math"

    OPS = ["+", "-", "*", "/", "//", "%", "**"]

    def default_props(self):
        return {"op": "+"}

    def prop_specs(self):
        return [("op", "Operator")]

    def prop_choices(self):
        return {"op": self.OPS}

    def build_pins(self):
        self.add_in("A", "data", default="0")
        self.add_in("B", "data", default="0")
        self.add_out("Result", "data")

    def summary(self):
        return f"A {self.props['op']} B"

    def expr(self, gen, pin):
        op = self.props["op"] if self.props["op"] in self.OPS else "+"
        return f"({gen.expr(self.pin('A'))} {op} {gen.expr(self.pin('B'))})"


class CompareNode(Node):
    type_name = "compare"
    title = "Compare"
    category = "math"

    OPS = ["==", "!=", "<", ">", "<=", ">="]

    def default_props(self):
        return {"op": "=="}

    def prop_specs(self):
        return [("op", "Operator")]

    def prop_choices(self):
        return {"op": self.OPS}

    def build_pins(self):
        self.add_in("A", "data", default="0")
        self.add_in("B", "data", default="0")
        self.add_out("Result", "data")

    def summary(self):
        return f"A {self.props['op']} B"

    def expr(self, gen, pin):
        op = self.props["op"] if self.props["op"] in self.OPS else "=="
        return f"({gen.expr(self.pin('A'))} {op} {gen.expr(self.pin('B'))})"


class RandomNode(Node):
    type_name = "random"
    title = "Random Number"
    category = "math"

    def default_props(self):
        return {}

    def build_pins(self):
        self.add_in("Min", "data", default="1")
        self.add_in("Max", "data", default="6")
        self.add_out("Value", "data")

    def summary(self):
        return "random whole number"

    def imports(self):
        return ("random",)

    def expr(self, gen, pin):
        return (f"random.randint({gen.expr(self.pin('Min'))}, "
                f"{gen.expr(self.pin('Max'))})")


class LogicNode(Node):
    type_name = "logic"
    title = "And / Or"
    category = "logic"

    OPS = ["and", "or"]

    def default_props(self):
        return {"op": "and"}

    def prop_specs(self):
        return [("op", "Operator")]

    def prop_choices(self):
        return {"op": self.OPS}

    def build_pins(self):
        self.add_in("A", "data", default="False")
        self.add_in("B", "data", default="False")
        self.add_out("Result", "data")

    def summary(self):
        return f"A {self.props['op']} B"

    def expr(self, gen, pin):
        op = self.props["op"] if self.props["op"] in self.OPS else "and"
        return f"({gen.expr(self.pin('A'))} {op} {gen.expr(self.pin('B'))})"


class NotNode(Node):
    type_name = "not"
    title = "Not"
    category = "logic"

    def build_pins(self):
        self.add_in("Value", "data", default="False")
        self.add_out("Result", "data")

    def summary(self):
        return "not ..."

    def expr(self, gen, pin):
        return f"(not {gen.expr(self.pin('Value'))})"


class CombineTextNode(Node):
    type_name = "text_join"
    title = "Combine Text"
    category = "text"

    def build_pins(self):
        self.add_in("A", "data", default='""')
        self.add_in("B", "data", default='""')
        self.add_out("Result", "data")

    def summary(self):
        return "A + B"

    def expr(self, gen, pin):
        return (f"(str({gen.expr(self.pin('A'))}) + "
                f"str({gen.expr(self.pin('B'))}))")


class ChangeCaseNode(Node):
    type_name = "text_case"
    title = "Change Case"
    category = "text"

    CASES = ["upper", "lower", "title"]

    def default_props(self):
        return {"case": "upper"}

    def prop_specs(self):
        return [("case", "Make it")]

    def prop_choices(self):
        return {"case": self.CASES}

    def build_pins(self):
        self.add_in("Value", "data", default='""')
        self.add_out("Result", "data")

    def summary(self):
        return f"{self.props['case']} case"

    def expr(self, gen, pin):
        case = self.props["case"] if self.props["case"] in self.CASES else "upper"
        return f"str({gen.expr(self.pin('Value'))}).{case}()"


class LengthNode(Node):
    type_name = "length"
    title = "Length"
    category = "text"

    def build_pins(self):
        self.add_in("Value", "data", default='""')
        self.add_out("Length", "data")

    def summary(self):
        return "how many"

    def expr(self, gen, pin):
        return f"len({gen.expr(self.pin('Value'))})"


class MakeListNode(Node):
    type_name = "list_new"
    title = "Make List"
    category = "list"

    def build_pins(self):
        self.add_out("List", "data")

    def summary(self):
        return "a new empty list"

    def expr(self, gen, pin):
        return "[]"


class ListAppendNode(Node):
    type_name = "list_append"
    title = "Add to List"
    category = "list"

    def build_pins(self):
        self.add_in("In", "exec")
        self.add_in("List", "data", default="[]")
        self.add_in("Item", "data", default="0")
        self.add_out("Then", "exec")

    def summary(self):
        return "list.append(item)"

    def emit(self, gen, indent):
        gen.line(indent, f"{gen.expr(self.pin('List'))}"
                         f".append({gen.expr(self.pin('Item'))})")
        gen.follow(self.pin("Then"), indent)


class GetItemNode(Node):
    type_name = "list_get"
    title = "Get Item"
    category = "list"

    def build_pins(self):
        self.add_in("List", "data", default="[]")
        self.add_in("Index", "data", default="0")
        self.add_out("Item", "data")

    def summary(self):
        return "list[index]"

    def expr(self, gen, pin):
        return f"{gen.expr(self.pin('List'))}[{gen.expr(self.pin('Index'))}]"


class IfNode(Node):
    type_name = "if"
    title = "If / Else"
    category = "flow"

    def build_pins(self):
        self.add_in("In", "exec")
        self.add_in("Condition", "data", default="True")
        self.add_out("True", "exec")
        self.add_out("False", "exec")

    def emit(self, gen, indent):
        gen.line(indent, f"if {gen.expr(self.pin('Condition'))}:")
        gen.follow_block(self.pin("True"), indent + 1)
        gen.line(indent, "else:")
        gen.follow_block(self.pin("False"), indent + 1)


class ForNode(Node):
    type_name = "for"
    title = "Repeat (For)"
    category = "flow"

    def default_props(self):
        return {"var": "i", "count": "10"}

    def prop_specs(self):
        return [("var", "Index variable name"), ("count", "Times to repeat")]

    def build_pins(self):
        self.add_in("In", "exec")
        self.add_in("Count", "data", default="10")
        self.add_out("Body", "exec")
        self.add_out("Index", "data")
        self.add_out("Done", "exec")

    def summary(self):
        return f"for {_ident(self.props['var'], 'i')} in range(...)"

    def expr(self, gen, pin):
        return _ident(self.props["var"], "i")

    def emit(self, gen, indent):
        var = _ident(self.props["var"], "i")
        self.pin("Count").default = str(self.props["count"]).strip() or "10"
        gen.line(indent, f"for {var} in range({gen.expr(self.pin('Count'))}):")
        gen.follow_block(self.pin("Body"), indent + 1)
        gen.follow(self.pin("Done"), indent)


class WhileNode(Node):
    type_name = "while"
    title = "Repeat While"
    category = "flow"

    def build_pins(self):
        self.add_in("In", "exec")
        self.add_in("Condition", "data", default="False")
        self.add_out("Body", "exec")
        self.add_out("Done", "exec")

    def summary(self):
        return "while condition:"

    def emit(self, gen, indent):
        gen.line(indent, f"while {gen.expr(self.pin('Condition'))}:")
        gen.follow_block(self.pin("Body"), indent + 1)
        gen.follow(self.pin("Done"), indent)


NODE_REGISTRY = [
    StartNode,
    IfNode, ForNode, WhileNode,
    VarSetNode, VarGetNode,
    NumberNode, StringNode, BoolNode,
    MathNode, CompareNode, RandomNode,
    LogicNode, NotNode,
    CombineTextNode, ChangeCaseNode, LengthNode,
    MakeListNode, ListAppendNode, GetItemNode,
    PrintNode, InputNode, ConvertNode,
]

NODE_BY_TYPE = {cls.type_name: cls for cls in NODE_REGISTRY}


# ----------------------------------------------------------------------------
# Code generation
# ----------------------------------------------------------------------------
class CodeGen:
    def __init__(self, editor):
        self.editor = editor
        self.lines = []
        self._emitted = set()
        self._expr_active = set()

    def line(self, indent, text):
        self.lines.append("    " * indent + text)

    def expr(self, in_pin):
        wire = self.editor.wire_to(in_pin)
        if not wire:
            return in_pin.default if in_pin.default is not None else "None"
        src = wire.src
        if src.node.id in self._expr_active:
            return in_pin.default if in_pin.default is not None else "None"
        self._expr_active.add(src.node.id)
        try:
            return src.node.expr(self, src)
        finally:
            self._expr_active.discard(src.node.id)

    def follow(self, out_pin, indent):
        wire = self.editor.wire_from(out_pin)
        if not wire:
            return
        target = wire.dst.node
        if target.id in self._emitted:
            self.line(indent, f"# (already runs above: {target.title})")
            return
        self._emitted.add(target.id)
        target.emit(self, indent)

    def follow_block(self, out_pin, indent):
        before = len(self.lines)
        self.follow(out_pin, indent)
        if len(self.lines) == before:
            self.line(indent, "pass")


# ----------------------------------------------------------------------------
# The editor canvas
# ----------------------------------------------------------------------------
class NodeEditor(tk.Canvas):
    def __init__(self, master, **kw):
        super().__init__(master, bg=COL_BG, highlightthickness=0, **kw)
        self.nodes = []
        self.wires = []
        self.breakpoints = set()
        self.selected = None
        self.cam_x = 0.0
        self.cam_y = 0.0
        self.allow_reroute = False

        self.mode = None
        self.drag_node = None
        self.drag_knot = None
        self.drag_dx = 0.0
        self.drag_dy = 0.0
        self.pan_x = 0
        self.pan_y = 0
        self.wire_anchor = None
        self.mouse = (0, 0)

        self.bind("<Button-1>", self.on_press)
        self.bind("<B1-Motion>", self.on_drag)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Double-Button-1>", self.on_double)
        self.bind("<Button-3>", self.on_right)
        self.bind("<Configure>", lambda e: self.redraw())

    def to_world(self, sx, sy):
        return sx - self.cam_x, sy - self.cam_y

    def to_screen(self, wx, wy):
        return wx + self.cam_x, wy + self.cam_y

    def wire_from(self, out_pin):
        for w in self.wires:
            if w.src is out_pin:
                return w
        return None

    def wire_to(self, in_pin):
        for w in self.wires:
            if w.dst is in_pin:
                return w
        return None

    def add_node(self, cls, wx=None, wy=None):
        if wx is None:
            wx = -self.cam_x + 80 + (len(self.nodes) % 6) * 18
            wy = -self.cam_y + 80 + (len(self.nodes) % 6) * 18
        n = cls(wx, wy)
        self.nodes.append(n)
        self.selected = n
        self.redraw()
        return n

    def delete_node(self, node):
        self.wires = [w for w in self.wires
                      if w.src.node is not node and w.dst.node is not node]
        self.nodes = [n for n in self.nodes if n is not node]
        if self.selected is node:
            self.selected = None
        self.redraw()

    def connect(self, a, b):
        if a.direction == "out" and b.direction == "in":
            out_pin, in_pin = a, b
        elif a.direction == "in" and b.direction == "out":
            out_pin, in_pin = b, a
        else:
            return False
        if out_pin.kind != in_pin.kind:
            return False
        if out_pin.node is in_pin.node:
            return False
        self.wires = [w for w in self.wires if w.dst is not in_pin]
        if out_pin.kind == "exec":
            self.wires = [w for w in self.wires if w.src is not out_pin]
        self.wires.append(Wire(out_pin, in_pin))
        return True

    def to_dict(self):
        return {
            "type": "visual-python-script",
            "version": 1,
            "cam": {"x": self.cam_x, "y": self.cam_y},
            "nodes": [
                {"id": n.id, "type": n.type_name,
                 "x": n.x, "y": n.y, "props": n.props}
                for n in self.nodes
            ],
            "wires": [
                {"src": w.src.node.id, "src_pin": w.src.name,
                 "dst": w.dst.node.id, "dst_pin": w.dst.name,
                 "points": [[x, y] for (x, y) in w.points]}
                for w in self.wires
            ],
            "breakpoints": sorted(self.breakpoints),
        }

    def from_dict(self, d):
        self.nodes = []
        self.wires = []
        self.selected = None
        idmap = {}
        for nd in d.get("nodes", []):
            cls = NODE_BY_TYPE.get(nd.get("type"))
            if cls is None:
                continue
            n = cls(nd.get("x", 60), nd.get("y", 60))
            n.props.update(nd.get("props", {}))
            self.nodes.append(n)
            idmap[nd.get("id")] = n
        for wd in d.get("wires", []):
            a = idmap.get(wd.get("src"))
            b = idmap.get(wd.get("dst"))
            if not a or not b:
                continue
            try:
                wire = Wire(a.pin(wd["src_pin"]), b.pin(wd["dst_pin"]))
                wire.points = [tuple(p) for p in wd.get("points", [])]
                self.wires.append(wire)
            except KeyError:
                pass
        cam = d.get("cam", {})
        self.cam_x = cam.get("x", 0.0)
        self.cam_y = cam.get("y", 0.0)
        self.breakpoints = set(d.get("breakpoints", []))
        self.redraw()

    def pin_at(self, wx, wy):
        for n in self.nodes:
            n.layout()
            for p in n.inputs + n.outputs:
                if (wx - p.wx) ** 2 + (wy - p.wy) ** 2 <= (PIN_R + 5) ** 2:
                    return p
        return None

    def node_at(self, wx, wy):
        for n in reversed(self.nodes):
            if n.contains(wx, wy):
                return n
        return None

    def knot_at(self, wx, wy):
        for w in self.wires:
            for i, (kx, ky) in enumerate(w.points):
                if (wx - kx) ** 2 + (wy - ky) ** 2 <= (KNOT_R + 4) ** 2:
                    return w, i
        return None

    def wire_at(self, wx, wy):
        best = None
        best_d = (KNOT_R + 5) ** 2
        for w in self.wires:
            anchors = ([(w.src.wx, w.src.wy)] + list(w.points)
                       + [(w.dst.wx, w.dst.wy)])
            for seg, ((ax, ay), (bx, by)) in enumerate(zip(anchors, anchors[1:])):
                for i in range(0, 13):
                    px, py = self._seg_point(ax, ay, bx, by, i / 12)
                    d = (wx - px) ** 2 + (wy - py) ** 2
                    if d < best_d:
                        best_d = d
                        best = (w, seg)
        return best

    def on_press(self, e):
        self.mouse = (e.x, e.y)
        wx, wy = self.to_world(e.x, e.y)
        pin = self.pin_at(wx, wy)
        if pin is not None:
            if pin.direction == "in":
                w = self.wire_to(pin)
                if w:
                    self.wires.remove(w)
                    self.wire_anchor = w.src
                    self.mode = "wire"
                    self.redraw()
                    return
            self.wire_anchor = pin
            self.mode = "wire"
            return
        knot = self.knot_at(wx, wy)
        if knot is not None:
            self.mode = "knot"
            self.drag_knot = knot
            return
        node = self.node_at(wx, wy)
        if node is not None:
            self.selected = node
            if node.in_header(wx, wy):
                self.mode = "node"
                self.drag_node = node
                self.drag_dx = wx - node.x
                self.drag_dy = wy - node.y
            self.redraw()
            return
        self.selected = None
        self.mode = "pan"
        self.pan_x = e.x
        self.pan_y = e.y
        self.redraw()

    def on_drag(self, e):
        self.mouse = (e.x, e.y)
        if self.mode == "node" and self.drag_node:
            wx, wy = self.to_world(e.x, e.y)
            self.drag_node.x = wx - self.drag_dx
            self.drag_node.y = wy - self.drag_dy
            self.redraw()
        elif self.mode == "knot" and self.drag_knot:
            w, i = self.drag_knot
            w.points[i] = self.to_world(e.x, e.y)
            self.redraw()
        elif self.mode == "pan":
            self.cam_x += e.x - self.pan_x
            self.cam_y += e.y - self.pan_y
            self.pan_x, self.pan_y = e.x, e.y
            self.redraw()
        elif self.mode == "wire":
            self.redraw()

    def on_release(self, e):
        if self.mode == "wire" and self.wire_anchor is not None:
            wx, wy = self.to_world(e.x, e.y)
            target = self.pin_at(wx, wy)
            if target is not None and target is not self.wire_anchor:
                self.connect(self.wire_anchor, target)
        self.mode = None
        self.drag_node = None
        self.drag_knot = None
        self.wire_anchor = None
        self.redraw()

    def edit_node(self, node):
        if not node.prop_specs():
            return
        dlg = PropDialog(self, node)
        self.wait_window(dlg)
        if dlg.result:
            self.redraw()

    def on_double(self, e):
        wx, wy = self.to_world(e.x, e.y)
        knot = self.knot_at(wx, wy)
        if knot is not None:
            w, i = knot
            del w.points[i]
            self.redraw()
            return
        node = self.node_at(wx, wy)
        if node is not None:
            self.edit_node(node)
            return
        if self.allow_reroute:
            hit = self.wire_at(wx, wy)
            if hit is not None:
                w, seg = hit
                w.points.insert(seg, (wx, wy))
                self.redraw()

    def on_right(self, e):
        wx, wy = self.to_world(e.x, e.y)
        menu = tk.Menu(self, tearoff=0)
        knot = self.knot_at(wx, wy)
        if knot is not None:
            w, i = knot
            menu.add_command(label="Remove reroute point",
                             command=lambda: (w.points.pop(i), self.redraw()))
            menu.tk_popup(e.x_root, e.y_root)
            return
        node = self.node_at(wx, wy)
        if node is not None:
            if node.prop_specs():
                menu.add_command(label="Edit…",
                                 command=lambda: self.edit_node(node))
            menu.add_command(label=f"Delete '{node.title}'",
                             command=lambda: self.delete_node(node))
            menu.add_separator()
        add = tk.Menu(menu, tearoff=0)
        for key, label, _ in CATEGORY_META:
            members = [c for c in NODE_REGISTRY if c.category == key]
            if not members:
                continue
            sub = tk.Menu(add, tearoff=0)
            for c in members:
                sub.add_command(label=c.title,
                                command=lambda c=c: self.add_node(c, wx, wy))
            add.add_cascade(label=label, menu=sub)
        menu.add_cascade(label="Add node", menu=add)
        menu.tk_popup(e.x_root, e.y_root)

    def redraw(self):
        self.delete("all")
        self.draw_grid()
        for w in self.wires:
            self.draw_wire(w)
        for n in self.nodes:
            self.draw_node(n)
        if self.mode == "wire" and self.wire_anchor is not None:
            ax, ay = self.to_screen(self.wire_anchor.wx, self.wire_anchor.wy)
            color = (COL_WIRE_EXEC if self.wire_anchor.kind == "exec"
                     else COL_WIRE_DATA)
            self.draw_curve(ax, ay, self.mouse[0], self.mouse[1], color)
        self.draw_legend()

    def draw_grid(self):
        w = self.winfo_width()
        h = self.winfo_height()
        step = 28
        ox = int(self.cam_x) % step
        oy = int(self.cam_y) % step
        for x in range(ox, w, step):
            self.create_line(x, 0, x, h, fill=COL_GRID)
        for y in range(oy, h, step):
            self.create_line(0, y, w, y, fill=COL_GRID)

    def draw_legend(self):
        h = self.winfo_height()
        x, y = 12, h - 50
        self.create_rectangle(x - 6, y - 8, x + 168, y + 34,
                              fill="#15161c", outline="#2d2f3a")
        self.create_polygon(x + 3, y - 2, x + 13, y + 4, x + 3, y + 10,
                            fill=COL_EXEC, outline=COL_EXEC)
        self.create_text(x + 22, y + 4, anchor="w", fill="#b9c0d4",
                         text="white = run order", font=(UI_FONT, 8))
        self.create_oval(x + 3, y + 17, x + 13, y + 27,
                         fill=COL_DATA, outline="#dfe9ff")
        self.create_text(x + 22, y + 22, anchor="w", fill="#b9c0d4",
                         text="blue = a value", font=(UI_FONT, 8))

    @staticmethod
    def _seg_point(x1, y1, x2, y2, t):
        dx = max(40, abs(x2 - x1) * 0.5)
        mt = 1 - t
        cx1, cy1 = x1 + dx, y1
        cx2, cy2 = x2 - dx, y2
        bx = (mt**3 * x1 + 3 * mt**2 * t * cx1
              + 3 * mt * t**2 * cx2 + t**3 * x2)
        by = (mt**3 * y1 + 3 * mt**2 * t * cy1
              + 3 * mt * t**2 * cy2 + t**3 * y2)
        return bx, by

    def draw_curve(self, x1, y1, x2, y2, color, width=2):
        pts = []
        for i in range(0, 21):
            bx, by = self._seg_point(x1, y1, x2, y2, i / 20)
            pts.extend([bx, by])
        self.create_line(*pts, fill=color, width=width, smooth=True)

    def draw_wire(self, w):
        color = COL_WIRE_EXEC if w.src.kind == "exec" else COL_WIRE_DATA
        anchors = ([(w.src.wx, w.src.wy)] + list(w.points)
                   + [(w.dst.wx, w.dst.wy)])
        for (ax, ay), (bx, by) in zip(anchors, anchors[1:]):
            sx1, sy1 = self.to_screen(ax, ay)
            sx2, sy2 = self.to_screen(bx, by)
            self.draw_curve(sx1, sy1, sx2, sy2, color)
        for (kx, ky) in w.points:
            sx, sy = self.to_screen(kx, ky)
            self.create_oval(sx - KNOT_R, sy - KNOT_R, sx + KNOT_R, sy + KNOT_R,
                             fill=color, outline="#11121a")

    def draw_pin(self, p):
        x, y = self.to_screen(p.wx, p.wy)
        if p.kind == "exec":
            self.create_polygon(x - 5, y - 6, x + 5, y, x - 5, y + 6,
                                 fill=COL_EXEC, outline=COL_EXEC)
        else:
            self.create_oval(x - PIN_R, y - PIN_R, x + PIN_R, y + PIN_R,
                             fill=COL_DATA, outline="#dfe9ff")
        if p.direction == "in":
            self.create_text(x + 12, y, text=p.name, anchor="w",
                             fill=COL_TEXT, font=(UI_FONT, 8))
        else:
            self.create_text(x - 12, y, text=p.name, anchor="e",
                             fill=COL_TEXT, font=(UI_FONT, 8))

    def draw_node(self, n):
        n.layout()
        sx, sy = self.to_screen(n.x, n.y)
        body = COL_NODE_SEL if n is self.selected else COL_NODE
        self.create_rectangle(sx, sy, sx + NODE_W, sy + n.height,
                              fill=body, outline="#11121a", width=2)
        cat = CATEGORY_COLORS.get(n.category, "#5c6bc0")
        self.create_rectangle(sx, sy, sx + NODE_W, sy + HEADER_H,
                              fill=cat, outline=cat)
        self.create_text(sx + 10, sy + HEADER_H / 2, text=n.title,
                         anchor="w", fill="#ffffff",
                         font=(UI_FONT, 10, "bold"))
        if n.summary():
            self.create_text(sx + 10, sy + HEADER_H + PROP_H / 2,
                             text=n.summary(), anchor="w",
                             fill="#b9c0d4", font=(MONO_FONT, 8))
        for p in n.inputs + n.outputs:
            self.draw_pin(p)

    def find_start(self):
        for n in self.nodes:
            if isinstance(n, StartNode):
                return n
        return None

    def generate_code(self):
        start = self.find_start()
        if start is None:
            return None, "No 'Start' node found. Add one to begin your program."
        gen = CodeGen(self)
        gen._emitted.add(start.id)
        start.emit(gen, 0)
        imports = sorted({m for n in self.nodes for m in n.imports()})
        lines = [f"import {m}" for m in imports]
        if lines and gen.lines:
            lines.append("")
        lines += gen.lines
        if not lines:
            return "", None
        return "\n".join(lines), None


# ----------------------------------------------------------------------------
# One-popup node property editor
# ----------------------------------------------------------------------------
class PropDialog(tk.Toplevel):
    def __init__(self, master, node):
        super().__init__(master)
        self.node = node
        self.result = False
        self.vars = {}
        self.title(f"Edit {node.title}")
        self.configure(bg=COL_BG)
        self.resizable(False, False)

        choices = node.prop_choices()
        specs = node.prop_specs()
        for r, (key, label) in enumerate(specs):
            tk.Label(self, text=label, bg=COL_BG, fg=COL_TEXT,
                     font=(UI_FONT, 9)).grid(row=r, column=0, sticky="w",
                                             padx=12, pady=6)
            var = tk.StringVar(value=str(node.props.get(key, "")))
            self.vars[key] = var
            if key in choices:
                ttk.Combobox(self, textvariable=var, values=choices[key],
                             state="readonly", width=18
                             ).grid(row=r, column=1, padx=12, pady=6)
            else:
                e = tk.Entry(self, textvariable=var, bg="#101117", fg=COL_TEXT,
                             insertbackground="#fff", width=22, relief="flat")
                e.grid(row=r, column=1, padx=12, pady=6)
                if r == 0:
                    e.focus_set()
                    e.select_range(0, "end")

        btns = tk.Frame(self, bg=COL_BG)
        btns.grid(row=len(specs), column=0, columnspan=2, pady=(6, 10))
        tk.Button(btns, text="OK", command=self._ok, bg="#3a7d3a", fg="#fff",
                  relief="flat", padx=18, pady=4).pack(side="left", padx=5)
        tk.Button(btns, text="Cancel", command=self.destroy, bg="#2d2f3a",
                  fg=COL_TEXT, relief="flat", padx=14, pady=4).pack(side="left")

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.transient(master.winfo_toplevel())
        self.grab_set()

    def _ok(self):
        for key, var in self.vars.items():
            self.node.props[key] = var.get()
        self.result = True
        self.destroy()


# ----------------------------------------------------------------------------
# Code view with a breakpoint gutter
# ----------------------------------------------------------------------------
class CodeView(tk.Frame):
    def __init__(self, master, editor):
        super().__init__(master, bg="#0b0c11")
        self.editor = editor
        self.allow_breakpoints = False
        self.gutter = tk.Canvas(self, width=46, bg="#0b0c11",
                                highlightthickness=0)
        self.scroll = tk.Scrollbar(self, command=self._yview)
        self.text = tk.Text(self, bg="#101117", fg="#cfe2ff", height=10,
                            font=(MONO_FONT, 10), relief="flat", wrap="none",
                            insertbackground="#fff", state="disabled",
                            yscrollcommand=self._on_text_scroll)
        self.gutter.pack(side="left", fill="y")
        self.scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_config("bp", background="#5a1f24")
        self.text.bind("<Double-Button-1>", self.on_double)
        self.gutter.bind("<Button-1>", self.on_gutter_click)
        self.text.bind("<MouseWheel>", lambda e: self.after(1, self.redraw_gutter))
        self.text.bind("<Configure>", lambda e: self.redraw_gutter())

    def _yview(self, *args):
        self.text.yview(*args)
        self.redraw_gutter()

    def _on_text_scroll(self, *args):
        self.scroll.set(*args)
        self.redraw_gutter()

    def set_code(self, code):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", code)
        self.text.config(state="disabled")
        self.apply_breakpoints()
        self.after(1, self.redraw_gutter)

    def _toggle(self, line):
        if not self.allow_breakpoints:
            return
        bps = self.editor.breakpoints
        if line in bps:
            bps.discard(line)
        else:
            bps.add(line)
        self.apply_breakpoints()
        self.redraw_gutter()

    def on_double(self, e):
        line = int(self.text.index(f"@{e.x},{e.y}").split(".")[0])
        self._toggle(line)
        return "break"

    def on_gutter_click(self, e):
        idx = self.text.index(f"@0,{e.y}")
        self._toggle(int(idx.split(".")[0]))

    def apply_breakpoints(self):
        self.text.config(state="normal")
        self.text.tag_remove("bp", "1.0", "end")
        last = int(self.text.index("end-1c").split(".")[0])
        for ln in self.editor.breakpoints:
            if ln <= last:
                self.text.tag_add("bp", f"{ln}.0", f"{ln}.0 lineend+1c")
        self.text.config(state="disabled")

    def redraw_gutter(self):
        self.gutter.delete("all")
        try:
            total = int(self.text.index("end-1c").split(".")[0])
        except tk.TclError:
            return
        for ln in range(1, total + 1):
            dl = self.text.dlineinfo(f"{ln}.0")
            if not dl:
                continue
            y = dl[1] + dl[3] / 2
            if self.allow_breakpoints and ln in self.editor.breakpoints:
                self.gutter.create_oval(5, y - 5, 15, y + 5,
                                        fill="#e2455a", outline="")
            self.gutter.create_text(42, y, text=str(ln), anchor="e",
                                    fill="#5b6075", font=(MONO_FONT, 8))


# ----------------------------------------------------------------------------
# Project file list helpers
# ----------------------------------------------------------------------------
FILE_KINDS = [
    (".vpy.json", "◆", "graph"),
    (".py", "▸", "python"),
    ("project.json", "★", "project"),
    (".json", "▢", "data"),
    (".txt", "≡", "text"),
    (".md", "≡", "text"),
]


def classify_file(fn):
    for suffix, glyph, desc in FILE_KINDS:
        if fn == suffix or (suffix.startswith(".") and fn.endswith(suffix)):
            return glyph, desc
    return "·", "file"


# ----------------------------------------------------------------------------
# Main application window
# ----------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1220x780")
        self.configure(bg=COL_BG)

        self.project_dir = None
        self.current_name = None
        self._files = []
        self._palette_items = []
        self.beginner = tk.BooleanVar(value=True)

        self._build_toolbar()
        self._build_body()
        self._apply_mode()
        self._seed_example()
        self._update_title()

        self.bind("<Delete>", self._delete_selected)
        self.bind("<Control-s>", lambda e: self.save_script())

    def _update_title(self):
        proj = os.path.basename(self.project_dir) if self.project_dir else "(no project)"
        name = self.current_name or "(unsaved)"
        self.title(f"Visual Python  —  {proj}  /  {name}")

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#15161c")
        bar.pack(side="top", fill="x")

        def mk(txt, cmd):
            b = tk.Button(bar, text=txt, command=cmd, bg="#2d2f3a", fg=COL_TEXT,
                          activebackground="#3a3d4d", activeforeground="#fff",
                          relief="flat", padx=12, pady=6,
                          font=(UI_FONT, 9, "bold"))
            b.pack(side="left", padx=3, pady=6)
            return b

        mk("New Project", self.new_project)
        mk("Open Project", self.open_project)
        mk("Save", self.save_script)
        tk.Frame(bar, width=2, bg="#2d2f3a").pack(side="left", fill="y", pady=6, padx=4)
        self.run_btn = mk("▶  Run", self.run_program)
        self.debug_btn = mk("Debug", lambda: self.run_program(debug=True))
        self.code_btn = mk("View Code", self.show_code)
        mk("Delete node", lambda: self._delete_selected(None))

        tk.Checkbutton(bar, text="Beginner mode", variable=self.beginner,
                       command=self._apply_mode, bg="#15161c", fg="#b9c0d4",
                       selectcolor="#15161c", activebackground="#15161c",
                       activeforeground="#fff", font=(UI_FONT, 9),
                       ).pack(side="right", padx=10)

    def _apply_mode(self):
        beginner = self.beginner.get()
        self.editor.allow_reroute = not beginner
        self.codeview.allow_breakpoints = not beginner
        self.codeview.apply_breakpoints()
        self.codeview.redraw_gutter()
        if beginner:
            self.debug_btn.pack_forget()
        else:
            self.debug_btn.pack(before=self.code_btn, side="left",
                                padx=3, pady=6)

    def _build_body(self):
        outer = tk.PanedWindow(self, orient="horizontal", bg="#15161c",
                               sashwidth=4)
        outer.pack(fill="both", expand=True)

        left = tk.PanedWindow(outer, orient="vertical", bg="#15161c",
                              sashwidth=4, width=210)

        ff = tk.Frame(left, bg="#1a1b22")
        hdr = tk.Frame(ff, bg="#1a1b22")
        hdr.pack(fill="x")
        tk.Label(hdr, text="PROJECT FILES", bg="#1a1b22", fg="#7a809a",
                 font=(UI_FONT, 8, "bold")).pack(side="left", padx=10, pady=(8, 2))
        tk.Button(hdr, text="↻", command=self.refresh_files, bg="#1a1b22",
                  fg="#7a809a", activebackground="#2d2f3a", relief="flat",
                  font=(UI_FONT, 9, "bold"), padx=6
                  ).pack(side="right", padx=8, pady=(4, 0))
        self.files_list = tk.Listbox(
            ff, bg="#1a1b22", fg=COL_TEXT, selectbackground="#3a3d4d",
            relief="flat", highlightthickness=0, font=(MONO_FONT, 9),
            activestyle="none")
        self.files_list.pack(fill="both", expand=True, padx=6, pady=6)
        self.files_list.bind("<Double-Button-1>", self.open_selected_file)
        self.files_count = tk.Label(ff, text="no project open", bg="#1a1b22",
                                    fg="#5b6075", font=(UI_FONT, 8),
                                    anchor="w")
        self.files_count.pack(fill="x", padx=10, pady=(0, 4))
        left.add(ff, minsize=120, height=220)

        nf = tk.Frame(left, bg="#1a1b22")
        tk.Label(nf, text="NODES  (double-click to add)", bg="#1a1b22",
                 fg="#7a809a", font=(UI_FONT, 8, "bold")
                 ).pack(anchor="w", padx=10, pady=(8, 2))
        self.palette = tk.Listbox(
            nf, bg="#1a1b22", fg=COL_TEXT, selectbackground="#3a3d4d",
            relief="flat", highlightthickness=0, font=(UI_FONT, 9),
            activestyle="none")
        self._fill_palette()
        self.palette.pack(fill="both", expand=True, padx=6, pady=6)
        self.palette.bind("<Double-Button-1>", self._add_from_palette)
        left.add(nf, minsize=180, stretch="always")

        outer.add(left, minsize=180)

        right = tk.PanedWindow(outer, orient="vertical", bg="#15161c",
                               sashwidth=4)
        self.editor = NodeEditor(right)
        right.add(self.editor, minsize=300, stretch="always")

        out_frame = tk.Frame(right, bg="#15161c")
        nb = ttk.Notebook(out_frame)
        self.output = tk.Text(nb, bg="#101117", fg="#d6f5d6", height=10,
                              font=(MONO_FONT, 10), relief="flat",
                              insertbackground="#fff")
        self.codeview = CodeView(nb, self.editor)
        nb.add(self.output, text="Output")
        nb.add(self.codeview, text="Generated Python")
        nb.pack(fill="both", expand=True)
        out_frame.pack_propagate(False)
        right.add(out_frame, minsize=120, height=220)

        outer.add(right, stretch="always")

    def _fill_palette(self):
        self.palette.delete(0, "end")
        self._palette_items = []
        for key, label, _ in CATEGORY_META:
            members = [c for c in NODE_REGISTRY if c.category == key]
            if not members:
                continue
            self.palette.insert("end", f"  {label.upper()}")
            self._palette_items.append(None)
            self.palette.itemconfig("end", foreground="#7a809a")
            for c in members:
                self.palette.insert("end", "     " + c.title)
                self._palette_items.append(c)

    def _add_from_palette(self, _e):
        sel = self.palette.curselection()
        if sel:
            cls = self._palette_items[sel[0]]
            if cls is not None:
                self.editor.add_node(cls)

    def _delete_selected(self, _e):
        if self.editor.selected:
            self.editor.delete_node(self.editor.selected)

    def new_project(self):
        parent = filedialog.askdirectory(title="Choose where to create the project")
        if not parent:
            return
        name = simpledialog.askstring("New Project", "Project name:", parent=self)
        if not name:
            return
        pdir = os.path.join(parent, _ident(name, "project"))
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "project.json"), "w", encoding="utf-8") as f:
            json.dump({"type": "visual-python-project", "name": name},
                      f, indent=2)
        self.project_dir = pdir
        self.current_name = None
        self.editor.nodes.clear()
        self.editor.wires.clear()
        self.editor.breakpoints.clear()
        self.editor.selected = None
        self.editor.redraw()
        self.refresh_files()
        self._update_title()

    def open_project(self):
        f = filedialog.askopenfilename(
            title="Open a project (pick project.json)",
            filetypes=[("Project file", "project.json"), ("JSON", "*.json")])
        if not f:
            return
        self.project_dir = os.path.dirname(f)
        self.current_name = None
        self.refresh_files()
        self._update_title()
        scripts = [fn for fn in self._files if fn.endswith(".vpy.json")]
        if scripts:
            self.load_script(scripts[0])
            self.files_list.selection_clear(0, "end")
            self.files_list.selection_set(self._files.index(scripts[0]))

    def refresh_files(self):
        self.files_list.delete(0, "end")
        self._files = []
        if not self.project_dir or not os.path.isdir(self.project_dir):
            self.files_count.config(text="no project open")
            return
        entries = [fn for fn in os.listdir(self.project_dir)
                   if os.path.isfile(os.path.join(self.project_dir, fn))]
        scripts = sorted(f for f in entries if f.endswith(".vpy.json"))
        others = sorted(f for f in entries if not f.endswith(".vpy.json"))
        for fn in scripts + others:
            glyph, _ = classify_file(fn)
            self._files.append(fn)
            self.files_list.insert("end", f" {glyph} {fn}")
        self.files_count.config(
            text=f"{len(scripts)} graph(s) · {len(self._files)} file(s) total")

    def open_selected_file(self, _e=None):
        sel = self.files_list.curselection()
        if not sel:
            return
        fn = self._files[sel[0]]
        if fn.endswith(".vpy.json"):
            self.load_script(fn)
        else:
            self.preview_file(fn)

    def preview_file(self, fn):
        path = os.path.join(self.project_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"(could not read this file as text)\n\n{e}"
        top = tk.Toplevel(self)
        top.title(f"Preview — {fn}")
        top.geometry("760x540")
        top.configure(bg=COL_BG)
        bar = tk.Frame(top, bg="#15161c")
        bar.pack(fill="x")
        tk.Label(bar, text=fn, bg="#15161c", fg=COL_TEXT,
                 font=(MONO_FONT, 10, "bold")).pack(side="left", padx=10, pady=6)
        tk.Button(bar, text="Close", command=top.destroy, bg="#2d2f3a",
                  fg=COL_TEXT, relief="flat", padx=12, pady=4
                  ).pack(side="right", padx=8, pady=6)
        txt = tk.Text(top, bg="#101117", fg="#d6e2ff", font=(MONO_FONT, 10),
                      relief="flat", wrap="none", insertbackground="#fff")
        sb = tk.Scrollbar(top, command=txt.yview)
        txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("end", content)
        txt.config(state="disabled")

    def load_script(self, fn):
        path = os.path.join(self.project_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
            return
        self.editor.from_dict(d)
        self.current_name = fn[:-len(".vpy.json")]
        self.show_code()
        self._update_title()

    def save_script(self, save_as=False):
        if not self.project_dir:
            if not messagebox.askyesno("No project",
                                       "No project is open. Create one now?"):
                return
            self.new_project()
            if not self.project_dir:
                return
        name = self.current_name
        if save_as or not name:
            name = simpledialog.askstring("Save script", "Script name:",
                                          parent=self, initialvalue=name or "main")
            if not name:
                return
            name = _ident(name, "main")
        self.current_name = name
        base = os.path.join(self.project_dir, name)
        with open(base + ".vpy.json", "w", encoding="utf-8") as f:
            json.dump(self.editor.to_dict(), f, indent=2)
        code, err = self.editor.generate_code()
        with open(base + ".py", "w", encoding="utf-8") as f:
            f.write(("# " + err) if err else (code or "# (empty program)"))
        self.refresh_files()
        self.show_code()
        self._update_title()
        messagebox.showinfo("Saved", f"Saved:\n  {name}.vpy.json\n  {name}.py")

    def show_code(self):
        code, err = self.editor.generate_code()
        self.codeview.set_code(("# " + err) if err else (code or "# (empty program)"))

    def run_program(self, debug=False):
        code, err = self.editor.generate_code()
        self.codeview.set_code(("# " + err) if err else (code or "# (empty program)"))
        self.output.delete("1.0", "end")
        if err:
            self.output.insert("end", "⚠ " + err)
            return

        def gui_input(prompt=""):
            return simpledialog.askstring("input", str(prompt), parent=self) or ""

        buf = io.StringIO()
        env = {"__builtins__": __builtins__, "input": gui_input}
        bps = set(self.editor.breakpoints)
        steps = [0]

        def tracer(frame, event, arg):
            if event == "line":
                steps[0] += 1
                if steps[0] > STEP_LIMIT:
                    raise RuntimeError(
                        "Stopped: the program ran too long "
                        "(maybe a loop that never ends?).")
                if (debug and bps
                        and frame.f_code.co_filename == "<vpy>"
                        and frame.f_lineno in bps):
                    local = {k: v for k, v in frame.f_locals.items()
                             if not k.startswith("__")}
                    shown = ", ".join(f"{k}={v!r}" for k, v in local.items())
                    print(f"[breakpoint] line {frame.f_lineno} | "
                          f"{shown or '(no variables yet)'}")
            return tracer

        try:
            compiled = compile(code, "<vpy>", "exec")
            with contextlib.redirect_stdout(buf):
                sys.settrace(tracer)
                try:
                    exec(compiled, env)
                finally:
                    sys.settrace(None)
            result = buf.getvalue()
            self.output.insert("end", result if result else "(no output)")
        except Exception:
            sys.settrace(None)
            self.output.insert("end", buf.getvalue())
            self.output.insert("end", "\n❌ Error:\n" + traceback.format_exc())

    def _seed_example(self):
        ed = self.editor
        start = ed.add_node(StartNode, 60, 80)
        pr = ed.add_node(PrintNode, 360, 80)
        txt = ed.add_node(StringNode, 360, 240)
        txt.props["text"] = "Hello! Pick a node on the left to begin."
        ed.connect(start.pin("Then"), pr.pin("In"))
        ed.connect(txt.pin("Value"), pr.pin("Value"))
        ed.selected = None
        ed.redraw()


if __name__ == "__main__":
    App().mainloop()
