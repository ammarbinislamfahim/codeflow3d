# backend/parsers/js_parser.py
"""
JavaScript / TypeScript CFG parser powered by tree-sitter.

Supports both JS and TS via distinct Language instances.
Falls back to an empty-graph stub if tree-sitter packages are missing.
"""

from __future__ import annotations

from collections import defaultdict

try:
    import tree_sitter_javascript as _tsjs
    import tree_sitter_typescript as _tsts
    from tree_sitter import Language, Parser as _TSParser

    _JS_LANG = Language(_tsjs.language())
    _TS_LANG = Language(_tsts.language_typescript())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


# ──────────────────────────── AST helpers ─────────────────────────────────

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node) -> int:
    return node.start_point[0] + 1


def _call_name(node, src: bytes):
    """Extract callee name string from a call_expression node."""
    func = node.child_by_field_name("function")
    if func is None:
        return None
    t = func.type
    if t == "identifier":
        return _text(func, src)
    if t == "member_expression":
        prop = func.child_by_field_name("property")
        return _text(prop, src) if prop else None
    return None


def _collect_calls(node, src: bytes, out: list):
    """Recursively collect all call_expression names under node."""
    if node.type == "call_expression":
        name = _call_name(node, src)
        if name:
            out.append(name)
    for child in node.children:
        _collect_calls(child, src, out)


def _paren_text(paren_node, src: bytes) -> str:
    """Extract inner text from a parenthesized_expression (strips outer parens)."""
    if paren_node is None:
        return ""
    if paren_node.type == "parenthesized_expression" and paren_node.named_children:
        return _text(paren_node.named_children[0], src)[:60]
    return _text(paren_node, src)[:60]


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
        if t == "program":
            for c in node.children:
                self.walk(c)
        elif t == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = _text(name_node, self.src) if name_node else None
            if name:
                self._func_body(name, node)
        elif t in ("lexical_declaration", "variable_declaration"):
            for c in node.named_children:
                if c.type == "variable_declarator":
                    self._var_func(c)
        elif t == "class_declaration":
            self._class(node)
        elif t == "export_statement":
            self._export(node)
        elif t == "expression_statement":
            # Top-level call e.g. `processUsers(users);` — record as top-level seed
            self._expr_calls(node)
        # Other top-level statements (imports, type declarations…) — skip

    def _var_func(self, decl):
        """Handle const/let/var X = arrow_function | function_expression."""
        name_node = decl.child_by_field_name("name")
        value_node = decl.child_by_field_name("value")
        if name_node is None or value_node is None:
            return
        if name_node.type not in ("identifier", "shorthand_property_identifier_pattern"):
            return
        name = _text(name_node, self.src)
        if value_node.type in ("arrow_function", "function_expression"):
            self._func_body(name, value_node)

    def _class(self, node):
        body = node.child_by_field_name("body")
        if body is None:
            return
        for c in body.named_children:
            if c.type == "method_definition":
                name_node = c.child_by_field_name("name")
                body_node = c.child_by_field_name("body")
                if name_node and body_node:
                    name = _text(name_node, self.src)
                    self._func_body(name, c, body_override=body_node)

    def _export(self, node):
        for c in node.children:
            t = c.type
            if t == "function_declaration":
                name_node = c.child_by_field_name("name")
                name = _text(name_node, self.src) if name_node else None
                if name:
                    self._func_body(name, c)
            elif t in ("lexical_declaration", "variable_declaration"):
                for vc in c.named_children:
                    if vc.type == "variable_declarator":
                        self._var_func(vc)
            elif t == "class_declaration":
                self._class(c)

    # ── Function subgraph ─────────────────────────────────────────────────

    def _func_body(self, name: str, node, body_override=None):
        """Build an isolated subgraph for a function."""
        self.defined_funcs.add(name)
        prev_func, prev_last = self.current_func, self.last
        self.current_func = name
        label = "START" if name == "main" else f"function: {name}"
        fn = self._new(label, _line(node))
        self.func_nodes[name] = fn["id"]
        self.last = fn

        if body_override is not None:
            body = body_override
        else:
            body = node.child_by_field_name("body")
            if body is None:
                body = next(
                    (c for c in node.children
                     if c.type in ("statement_block", "expression")), None
                )

        if body:
            if body.type == "statement_block":
                self._block(body)
            else:
                # Arrow function with expression body (implicit return)
                calls = []
                _collect_calls(body, self.src, calls)
                for cname in calls:
                    call_n = self._new(f"call: {cname}", _line(body))
                    self._edge(call_n)
                    self._record(cname, call_n["id"])

        self.current_func, self.last = prev_func, prev_last

    # ── Statement dispatch ────────────────────────────────────────────────

    def _block(self, node):
        for c in node.named_children:
            self._stmt(c)

    def _stmt(self, node):
        t = node.type
        if t == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = _text(name_node, self.src) if name_node else None
            if name:
                self._func_body(name, node)
        elif t in ("lexical_declaration", "variable_declaration"):
            for c in node.named_children:
                if c.type == "variable_declarator":
                    self._var_func(c)
            # Also extract calls from non-function variable initializers
            self._decl_calls(node)
        elif t == "if_statement":
            self._if(node)
        elif t == "for_statement":
            self._for(node)
        elif t == "for_in_statement":
            self._for_in(node)
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
            # Scan return expression for calls (e.g. return arr.filter(u => fn(u)))
            val = next((c for c in node.named_children if c.type not in ("comment",)), None)
            if val:
                self._scan_expr(val, ret_n["id"])
        elif t == "break_statement":
            self._edge(self._new("break", _line(node)))
        elif t == "continue_statement":
            self._edge(self._new("continue", _line(node)))
        elif t == "throw_statement":
            thr_n = self._new("throw", _line(node))
            self._edge(thr_n)
            val = next((c for c in node.named_children if c.type not in ("comment",)), None)
            if val:
                self._scan_expr(val, thr_n["id"])
        elif t == "expression_statement":
            self._expr_calls(node)
        elif t == "statement_block":
            self._block(node)
        elif t == "class_declaration":
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

    def _if(self, node):
        cond = _paren_text(node.child_by_field_name("condition"), self.src)
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
        loop_n = self._new(f"for ({cond_text})", _line(node))
        loop_n["loop_type"] = "for"
        loop_n["loop_condition"] = cond_text
        loop_n["is_infinite"] = (cond is None)
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

    def _for_in(self, node):
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        left_text = _text(left, self.src) if left else "?"
        right_text = _text(right, self.src)[:30] if right else "?"
        loop_n = self._new(f"for ({left_text} of {right_text})", _line(node))
        loop_n["loop_type"] = "for-in"
        loop_n["loop_condition"] = f"{left_text} of {right_text}"
        loop_n["is_infinite"] = False
        self._edge(loop_n, "loop")
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
        cond = _paren_text(node.child_by_field_name("condition"), self.src)
        is_inf = cond.strip() in ("true", "1")
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
        cond_node = node.child_by_field_name("condition")
        cond = _paren_text(cond_node, self.src)
        if cond:
            loop_n["label"] = f"do-while ({cond})"
            loop_n["loop_condition"] = cond
            loop_n["is_infinite"] = cond.strip() in ("true", "1")
        self._scan_expr(cond_node, loop_n["id"])
        # Back-edge from end of do-while body to loop header
        if (self.last and self.last["id"] != loop_n["id"]
                and self.last["label"] not in ("return", "break", "continue")):
            self.loops.append({"from": self.last["id"], "to": loop_n["id"]})
        self.last = save

    def _switch(self, node):
        val = _paren_text(node.child_by_field_name("value"), self.src)
        sw_n = self._new(f"switch ({val})", _line(node))
        self._edge(sw_n, "conditional")
        self._scan_expr(node.child_by_field_name("value"), sw_n["id"])
        save = self.last
        body = node.child_by_field_name("body")
        if body:
            for c in body.named_children:
                if c.type == "switch_case":
                    val_node = c.child_by_field_name("value")
                    val_text = _text(val_node, self.src)[:30] if val_node else "?"
                    label = f"case {val_text}"
                    body_stmts = c.named_children[1:]
                elif c.type == "switch_default":
                    label = "default"
                    body_stmts = c.named_children
                else:
                    continue
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
            if c.type == "statement_block":
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
            elif c.type == "finally_clause":
                self.last = save
                fin_n = self._new("finally", _line(c))
                self.conditionals.append({"from": save["id"], "to": fin_n["id"]})
                self.last = fin_n
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
            # Non-call expression (assignment, etc.) — still part of the flow
            stmt_n = self._new("statement", _line(node))
            self._edge(stmt_n)

    def _decl_calls(self, node):
        """Extract calls from declarations where the value isn't a function."""
        for var_decl in node.named_children:
            if var_decl.type != "variable_declarator":
                continue
            val = var_decl.child_by_field_name("value")
            if val is None or val.type in ("arrow_function", "function_expression"):
                continue  # function bodies handled separately
            calls = []
            _collect_calls(val, self.src, calls)
            for name in calls:
                call_n = self._new(f"call: {name}", _line(var_decl))
                self._edge(call_n)
                self._record(name, call_n["id"])

    # ── Output assembly ───────────────────────────────────────────────────

    def _reachable(self):
        # JS has no single entry point; treat 'main' and all exported/top-level
        # called functions as roots.
        stack = list(self.top_level & self.defined_funcs)
        if "main" in self.defined_funcs:
            stack.append("main")
        # If nothing seeded, everything is potentially reachable from module scope
        if not stack:
            stack = list(self.defined_funcs)
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
                f for f in self.defined_funcs - reachable
                if f not in ("main", "constructor")
            ),
            "recursion": {
                "direct": sorted(direct_recursion),
                "mutual": sorted(mutual_recursion),
            },
        }


# ──────────────────────────── public API ──────────────────────────────────

def parse(code: str, language: str = "javascript") -> dict:
    """Parse JS or TS code and return a CFG dict.

    Args:
        code: Source code string.
        language: ``"javascript"`` (default) or ``"typescript"``.
    """
    if not _TS_AVAILABLE:
        return {
            "nodes": [], "edges": [], "loops": [], "conditionals": [],
            "call_edges": [], "function_groups": {}, "unused_functions": [],
            "error": "tree-sitter-javascript not available",
        }
    lang = _TS_LANG if language == "typescript" else _JS_LANG
    src = code.encode("utf-8", errors="replace")
    parser = _TSParser(lang)
    tree = parser.parse(src)
    builder = _Builder(src)
    builder.walk(tree.root_node)
    return builder.build()
