# backend/parsers/cpp_parser.py
"""
C++ CFG parser powered by tree-sitter-cpp.

Falls back to an empty-graph stub if tree-sitter-cpp is not installed.
"""

from __future__ import annotations

from collections import defaultdict

try:
    import tree_sitter_cpp as _tscpp
    from tree_sitter import Language, Parser as _TSParser

    _CPP_LANG = Language(_tscpp.language())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


# ──────────────────────────── AST helpers ─────────────────────────────────

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node) -> int:
    return node.start_point[0] + 1


def _find_func_declarator(node):
    """Recursively find function_declarator inside pointer/ref wrappers."""
    for child in node.children:
        if child.type == "function_declarator":
            return child
        if child.type in ("pointer_declarator", "reference_declarator"):
            result = _find_func_declarator(child)
            if result:
                return result
    return None


def _declarator_name(decl, src: bytes) -> str | None:
    """Return the plain function name from a function_declarator node."""
    if decl is None:
        return None
    for child in decl.children:
        t = child.type
        if t == "identifier":
            return _text(child, src)
        if t == "qualified_identifier":
            name_child = child.child_by_field_name("name")
            if name_child:
                return _text(name_child, src)
            for gc in reversed(child.named_children):
                if gc.type in ("identifier", "type_identifier"):
                    return _text(gc, src)
        if t == "destructor_name":
            return _text(child, src)        # ~Foo
        if t == "operator_name":
            return _text(child, src)        # operator+
    return None


def _call_name(node, src: bytes) -> str | None:
    """Extract the callee name string from a call_expression node."""
    func = node.child_by_field_name("function")
    if func is None and node.children:
        func = node.children[0]
    if func is None:
        return None
    t = func.type
    if t == "identifier":
        return _text(func, src)
    if t == "field_expression":
        field = func.child_by_field_name("field")
        return _text(field, src) if field else None
    if t in ("qualified_identifier", "template_function"):
        name = func.child_by_field_name("name")
        return _text(name, src) if name else None
    return None


def _collect_calls(node, src: bytes, out: list):
    """Recursively collect all call_expression names under node."""
    if node.type == "call_expression":
        name = _call_name(node, src)
        if name:
            out.append(name)
    for child in node.children:
        _collect_calls(child, src, out)


# ──────────────────────────── CFG builder ─────────────────────────────────

class _Builder:
    def __init__(self, src: bytes):
        self.src = src
        self.nodes: list = []
        self.edges: list = []
        self.loops: list = []
        self.conditionals: list = []
        self.call_edges: list = []
        self._nid = 0
        self.last = None
        self.current_func = None
        self.defined_funcs: set = set()
        self.func_nodes: dict = {}
        self.call_graph: dict = defaultdict(set)
        self.top_level: set = set()
        self._pending: list = []

    # ── Primitives ────────────────────────────────────────────────────────

    def _new(self, label, line=None):
        n = {"id": f"n{self._nid}", "label": label,
             "func": self.current_func or "__toplevel__"}
        if line is not None:
            n["line"] = line
        self.nodes.append(n)
        self._nid += 1
        return n

    def _edge(self, node, kind="normal"):
        if self.last and self.last.get("func") == node.get("func"):
            e = {"from": self.last["id"], "to": node["id"]}
            if kind == "loop":
                self.loops.append(e)
            elif kind == "conditional":
                self.conditionals.append(e)
            else:
                self.edges.append(e)
        self.last = node

    def _record(self, name, call_nid):
        if self.current_func:
            self.call_graph[self.current_func].add(name)
        else:
            self.top_level.add(name)
        self._pending.append((call_nid, name))

    # ── Top-level walk ────────────────────────────────────────────────────

    def walk(self, node):
        t = node.type
        if t == "translation_unit":
            for c in node.children:
                self.walk(c)
        elif t == "function_definition":
            self._func(node)
        elif t == "namespace_definition":
            body = node.child_by_field_name("body")
            target = body if body else node
            for c in target.children:
                self.walk(c)
        elif t in ("class_specifier", "struct_specifier"):
            self._class(node)
        elif t == "declaration_list":
            for c in node.children:
                self.walk(c)

    def _class(self, node):
        body = node.child_by_field_name("body")
        if body is None:
            for c in node.children:
                if c.type in ("field_declaration_list", "declaration_list"):
                    body = c
                    break
        if body:
            for c in body.children:
                if c.type == "function_definition":
                    self._func(c)
                elif c.type in ("class_specifier", "struct_specifier"):
                    self._class(c)

    # ── Function subgraph ─────────────────────────────────────────────────

    def _func(self, node):
        decl = _find_func_declarator(node)
        name = _declarator_name(decl, self.src)
        if not name:
            return
        self.defined_funcs.add(name)
        prev_func, prev_last = self.current_func, self.last
        self.current_func = name
        label = "START" if name == "main" else f"function: {name}"
        fn = self._new(label, _line(node))
        self.func_nodes[name] = fn["id"]
        self.last = fn
        # Process member initializer list if present (constructors)
        init_list = next(
            (c for c in node.children if c.type == "field_initializer_list"), None
        )
        if init_list:
            for init in init_list.named_children:
                init_n = self._new("init", _line(init))
                self._edge(init_n)
        body = node.child_by_field_name("body") or next(
            (c for c in node.children if c.type == "compound_statement"), None
        )
        if body:
            self._block(body)
        self.current_func, self.last = prev_func, prev_last

    # ── Statement dispatch ────────────────────────────────────────────────

    def _block(self, node):
        for c in node.named_children:
            self._stmt(c)

    def _stmt(self, node):
        t = node.type
        if t == "function_definition":
            self._func(node)
        elif t == "if_statement":
            self._if(node)
        elif t in ("for_statement", "for_range_loop"):
            self._for(node)
        elif t == "while_statement":
            self._while(node)
        elif t == "do_statement":
            self._do(node)
        elif t == "switch_statement":
            self._switch(node)
        elif t == "try_statement":
            self._try(node)
        elif t == "return_statement":
            ret_n = self._new("return", _line(node))
            self._edge(ret_n)
            # Scan return expression for calls (e.g. return factorial(n-1))
            for c in node.named_children:
                self._scan_expr(c, ret_n["id"])
        elif t == "break_statement":
            self._edge(self._new("break", _line(node)))
        elif t == "continue_statement":
            self._edge(self._new("continue", _line(node)))
        elif t == "expression_statement":
            self._expr_calls(node)
        elif t == "declaration":
            self._decl_calls(node)
        elif t == "compound_statement":
            self._block(node)
        elif t == "lambda_expression":
            self._edge(self._new("lambda", _line(node)))
        elif t in ("class_specifier", "struct_specifier"):
            self._class(node)

    def _scan_expr(self, expr_node, anchor_nid: str):
        """Record calls found in an expression without creating CFG nodes."""
        if expr_node is None:
            return
        calls: list = []
        _collect_calls(expr_node, self.src, calls)
        for name in calls:
            self._record(name, anchor_nid)

    # ── Control flow nodes ────────────────────────────────────────────────

    def _cond_text(self, cond_node):
        if cond_node is None:
            return ""
        if cond_node.type == "condition_clause":
            inner = (cond_node.named_children[0]
                     if cond_node.named_children else cond_node)
            return _text(inner, self.src)[:60]
        return _text(cond_node, self.src)[:60]

    def _if(self, node):
        cond = self._cond_text(node.child_by_field_name("condition"))
        if_n = self._new(f"if ({cond})", _line(node))
        self._edge(if_n, "conditional")
        self._scan_expr(node.child_by_field_name("condition"), if_n["id"])
        save = self.last
        consequence = node.child_by_field_name("consequence")
        if consequence:
            self.last = save
            self._stmt(consequence)
        alt = node.child_by_field_name("alternative")
        if alt:
            self.last = save
            else_n = self._new("else", _line(alt))
            self.conditionals.append({"from": save["id"], "to": else_n["id"]})
            self.last = else_n
            for c in alt.named_children:
                self._stmt(c)
        self.last = save

    def _for(self, node):
        cond = node.child_by_field_name("condition")
        cond_text = _text(cond, self.src)[:50] if cond else "..."
        is_range = node.type == "for_range_loop"
        loop_n = self._new(f"for ({cond_text})", _line(node))
        loop_n["loop_type"] = "for-range" if is_range else "for"
        loop_n["loop_condition"] = cond_text
        loop_n["is_infinite"] = (cond is None and not is_range)
        self._edge(loop_n, "loop")
        for part_name in ("initializer", "condition", "update"):
            part = node.child_by_field_name(part_name)
            if part:
                calls = []
                _collect_calls(part, self.src, calls)
                for name in calls:
                    self._record(name, loop_n["id"])
        save = self.last
        body = node.child_by_field_name("body")
        if body:
            self.last = loop_n
            self._stmt(body)
        # Back-edge from end of loop body to loop header
        if (self.last and self.last["id"] != loop_n["id"]
                and self.last["label"] not in ("return", "break", "continue")):
            self.loops.append({"from": self.last["id"], "to": loop_n["id"]})
        self.last = save

    def _while(self, node):
        cond = self._cond_text(node.child_by_field_name("condition"))
        is_inf = cond.strip() in ("true", "1", "TRUE")
        loop_n = self._new(f"while ({cond})", _line(node))
        loop_n["loop_type"] = "while"
        loop_n["loop_condition"] = cond
        loop_n["is_infinite"] = is_inf
        self._edge(loop_n, "loop")
        self._scan_expr(node.child_by_field_name("condition"), loop_n["id"])
        save = self.last
        body = node.child_by_field_name("body")
        if body:
            self.last = loop_n
            self._stmt(body)
        # Back-edge from end of loop body to loop header
        if (self.last and self.last["id"] != loop_n["id"]
                and self.last["label"] not in ("return", "break", "continue")):
            self.loops.append({"from": self.last["id"], "to": loop_n["id"]})
        self.last = save

    def _do(self, node):
        loop_n = self._new("do-while", _line(node))
        loop_n["loop_type"] = "do-while"
        loop_n["loop_condition"] = "..."
        loop_n["is_infinite"] = False
        self._edge(loop_n, "loop")
        save = self.last
        body = node.child_by_field_name("body")
        if body:
            self.last = loop_n
            self._stmt(body)
        cond = node.child_by_field_name("condition")
        if cond:
            inner = (cond.named_children[0]
                     if cond.named_children else cond)
            cond_text = _text(inner, self.src)[:50]
            loop_n["label"] = f"do-while ({cond_text})"
            loop_n["loop_condition"] = cond_text
            loop_n["is_infinite"] = cond_text.strip() in ("true", "1", "TRUE")
            self._scan_expr(cond, loop_n["id"])
        # Back-edge from end of do-while body to loop header
        if (self.last and self.last["id"] != loop_n["id"]
                and self.last["label"] not in ("return", "break", "continue")):
            self.loops.append({"from": self.last["id"], "to": loop_n["id"]})
        self.last = save

    def _switch(self, node):
        cond = self._cond_text(node.child_by_field_name("condition"))
        sw_n = self._new(f"switch ({cond})", _line(node))
        self._edge(sw_n, "conditional")
        self._scan_expr(node.child_by_field_name("condition"), sw_n["id"])
        save = self.last
        body = node.child_by_field_name("body") or next(
            (c for c in node.named_children if c.type == "compound_statement"), None
        )
        if body:
            for c in body.named_children:
                if c.type == "case_statement":
                    is_default = c.children[0].type == "default"
                    if is_default:
                        label = "default"
                        body_stmts = c.named_children
                    else:
                        val = c.child_by_field_name("value")
                        val_text = _text(val, self.src)[:30] if val else "?"
                        label = f"case {val_text}"
                        body_stmts = c.named_children[1:]
                    case_n = self._new(label, _line(c))
                    self.conditionals.append({"from": sw_n["id"], "to": case_n["id"]})
                    self.last = case_n
                    for stmt in body_stmts:
                        if stmt.type != "break_statement":
                            self._stmt(stmt)
        self.last = save

    def _try(self, node):
        try_n = self._new("try", _line(node))
        self._edge(try_n)
        save = self.last
        for c in node.named_children:
            if c.type == "compound_statement":
                self.last = try_n
                self._block(c)
            elif c.type == "catch_clause":
                self.last = save
                catch_n = self._new("catch", _line(c))
                self.conditionals.append({"from": save["id"], "to": catch_n["id"]})
                self.last = catch_n
                body = c.child_by_field_name("body")
                if body:
                    self._block(body)
        self.last = save

    def _expr_calls(self, node):
        calls = []
        _collect_calls(node, self.src, calls)
        if calls:
            for name in calls:
                call_n = self._new(f"call: {name}", _line(node))
                self._edge(call_n)
                self._record(name, call_n["id"])
        else:
            # Non-call expression (operator<<, assignment, etc.) — still part of the flow
            stmt_n = self._new("statement", _line(node))
            self._edge(stmt_n)

    def _decl_calls(self, node):
        calls = []
        _collect_calls(node, self.src, calls)
        for name in calls:
            call_n = self._new(f"call: {name}", _line(node))
            self._edge(call_n)
            self._record(name, call_n["id"])

    # ── Output assembly ───────────────────────────────────────────────────

    def _reachable(self):
        stack = ["main"] if "main" in self.defined_funcs else []
        stack += [n for n in self.top_level if n in self.defined_funcs]
        seen = set()
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            for callee in self.call_graph.get(f, set()):
                if callee in self.defined_funcs and callee not in seen:
                    stack.append(callee)
        return seen

    def build(self):
        for call_nid, callee in self._pending:
            if callee in self.func_nodes:
                self.call_edges.append({"from": call_nid, "to": self.func_nodes[callee]})

        def _dedup(lst):
            seen, out = set(), []
            for e in lst:
                k = (e["from"], e["to"])
                if k not in seen:
                    seen.add(k)
                    out.append(e)
            return out

        groups = {}
        for n in self.nodes:
            groups.setdefault(n.get("func", "__toplevel__"), []).append(n["id"])

        reachable = self._reachable()

        # ── Recursion detection ────────────────────────────────────────
        direct_recursion = set()
        mutual_recursion = set()
        for func in self.defined_funcs:
            callees = self.call_graph.get(func, set())
            if func in callees:
                direct_recursion.add(func)
            visited = set()
            stack = [c for c in callees if c in self.defined_funcs and c != func]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                if func in self.call_graph.get(current, set()):
                    mutual_recursion.add(func)
                    break
                for callee in self.call_graph.get(current, set()):
                    if callee in self.defined_funcs and callee not in visited:
                        stack.append(callee)

        all_recursive = direct_recursion | mutual_recursion
        for n in self.nodes:
            label = n.get("label", "")
            if label.startswith("call: "):
                called_name = label[6:]
                func_scope = n.get("func", "")
                if func_scope in direct_recursion and called_name == func_scope:
                    n["recursive"] = True
                    n["recursion_type"] = "direct"
                elif called_name in all_recursive:
                    n["recursive"] = True
                    n["recursion_type"] = "mutual"

        return {
            "nodes": self.nodes,
            "edges": _dedup(self.edges),
            "loops": _dedup(self.loops),
            "conditionals": _dedup(self.conditionals),
            "call_edges": _dedup(self.call_edges),
            "function_groups": groups,
            "unused_functions": sorted(
                f for f in self.defined_funcs - reachable if f != "main"
            ),
            "recursion": {
                "direct": sorted(direct_recursion),
                "mutual": sorted(mutual_recursion),
            },
        }


# ──────────────────────────── public API ──────────────────────────────────

def parse(code: str) -> dict:
    if not _TS_AVAILABLE:
        return {
            "nodes": [], "edges": [], "loops": [], "conditionals": [],
            "call_edges": [], "function_groups": {}, "unused_functions": [],
            "error": "tree-sitter-cpp not available",
        }
    src = code.encode("utf-8", errors="replace")
    parser = _TSParser(_CPP_LANG)
    tree = parser.parse(src)
    builder = _Builder(src)
    builder.walk(tree.root_node)
    return builder.build()
