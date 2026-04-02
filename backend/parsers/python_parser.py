# backend/parsers/python_parser.py

import ast
from collections import defaultdict


class CFGBuilder(ast.NodeVisitor):
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.loops = []
        self.conditionals = []
        self.call_edges = []         # inter-procedural: call site → function header
        self.node_id = 0
        self.last_node = None
        self.defined_funcs = set()   # names of functions defined in this code
        self.called_funcs  = set()   # names that appear in call expressions
        self.call_graph = defaultdict(set)
        self.current_function = None
        self.top_level_calls = set()
        self.func_node_ids = {}      # function name → node id for inter-proc edges
        self.const_values: dict = {} # var_name → constant value (for dead-branch detection)
        self._dead_branch_depth: int = 0  # >0 means currently inside an always-false branch

    def _line_of(self, node):
        return getattr(node, "lineno", None)

    def new_node(self, label, line=None):
        node = {"id": f"n{self.node_id}", "label": label}
        if line is not None:
            node["line"] = line
        # Tag every node with the function it belongs to for multi-CFG layout
        node["func"] = self.current_function or "__toplevel__"
        if self._dead_branch_depth:
            node["dead"] = True   # inside an always-false (unreachable) branch
        self.nodes.append(node)
        self.node_id += 1
        return node

    def connect(self, node, edge_type="normal"):
        if self.last_node:
            edge = {"from": self.last_node["id"], "to": node["id"]}
            if edge_type == "loop":
                self.loops.append(edge)
            elif edge_type == "conditional":
                self.conditionals.append(edge)
            else:
                self.edges.append(edge)
        self.last_node = node

    def _record_call(self, name):
        # Always record in call_graph so unused-function analysis counts
        # syntactic calls even inside dead branches (they are still "used" code).
        self.called_funcs.add(name)
        if self.current_function:
            self.call_graph[self.current_function].add(name)
        else:
            self.top_level_calls.add(name)

    # ── Constant-condition helpers ─────────────────────────────────────────
    _DEAD_SENTINEL = object()

    def _eval_const(self, node):
        """Try to evaluate a Python AST expression to a Python value.
        Returns the value on success, or _DEAD_SENTINEL if undetermined.
        Handles: Constant, Name (known vars), UnaryOp, BinOp, Compare, BoolOp.
        """
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            v = self.const_values.get(node.id, self._DEAD_SENTINEL)
            return v  # may be _DEAD_SENTINEL
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_const(node.operand)
            if operand is self._DEAD_SENTINEL:
                return self._DEAD_SENTINEL
            if isinstance(node.op, ast.Not):  return not operand
            if isinstance(node.op, ast.USub): return -operand
            if isinstance(node.op, ast.UAdd): return operand
            return self._DEAD_SENTINEL
        if isinstance(node, ast.BinOp):
            lv = self._eval_const(node.left)
            rv = self._eval_const(node.right)
            if lv is self._DEAD_SENTINEL or rv is self._DEAD_SENTINEL:
                return self._DEAD_SENTINEL
            try:
                if isinstance(node.op, ast.Add):  return lv + rv
                if isinstance(node.op, ast.Sub):  return lv - rv
                if isinstance(node.op, ast.Mult): return lv * rv
                if isinstance(node.op, ast.Div):  return lv / rv if rv else self._DEAD_SENTINEL
                if isinstance(node.op, ast.Mod):  return lv % rv if rv else self._DEAD_SENTINEL
            except Exception:
                pass
            return self._DEAD_SENTINEL
        if isinstance(node, ast.Compare):
            lv = self._eval_const(node.left)
            if lv is self._DEAD_SENTINEL:
                return self._DEAD_SENTINEL
            result = True
            current = lv
            for op, comparator in zip(node.ops, node.comparators):
                rv = self._eval_const(comparator)
                if rv is self._DEAD_SENTINEL:
                    return self._DEAD_SENTINEL
                try:
                    if isinstance(op, ast.Eq):    step = (current == rv)
                    elif isinstance(op, ast.NotEq): step = (current != rv)
                    elif isinstance(op, ast.Lt):   step = (current < rv)
                    elif isinstance(op, ast.Gt):   step = (current > rv)
                    elif isinstance(op, ast.LtE):  step = (current <= rv)
                    elif isinstance(op, ast.GtE):  step = (current >= rv)
                    elif isinstance(op, ast.Is):   step = (current is rv)
                    elif isinstance(op, ast.IsNot):step = (current is not rv)
                    else: return self._DEAD_SENTINEL
                except Exception:
                    return self._DEAD_SENTINEL
                result = result and step
                current = rv
            return result
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                v = True  # identity for AND (empty → truthy)
                for v_node in node.values:
                    v = self._eval_const(v_node)
                    if v is self._DEAD_SENTINEL: return self._DEAD_SENTINEL
                    if not v: return v
                return v
            if isinstance(node.op, ast.Or):
                v = False  # identity for OR (empty → falsy)
                for v_node in node.values:
                    v = self._eval_const(v_node)
                    if v is self._DEAD_SENTINEL: return self._DEAD_SENTINEL
                    if v: return v
                return v
        return self._DEAD_SENTINEL

    def _is_always_false(self, test_node) -> bool:
        """Return True when the condition always evaluates to falsy."""
        v = self._eval_const(test_node)
        if v is self._DEAD_SENTINEL:
            return False
        return not v

    def _is_always_true(self, test_node) -> bool:
        """Return True when the condition always evaluates to truthy."""
        v = self._eval_const(test_node)
        if v is self._DEAD_SENTINEL:
            return False
        return bool(v)

    def reachable_functions(self):
        reachable = set()
        stack = [name for name in self.top_level_calls if name in self.defined_funcs]
        # __init__ (and other dunder methods) are implicit entry points — they are
        # called by Python itself on class instantiation, comparison, etc.  Seed
        # their direct callees so methods invoked from __init__ are not falsely
        # reported as unused.
        for dunder in ('__init__', '__new__', '__post_init__',
                       '__enter__', '__exit__', '__call__'):
            for callee in self.call_graph.get(dunder, set()):
                if callee in self.defined_funcs and callee not in stack:
                    stack.append(callee)
        while stack:
            func = stack.pop()
            if func in reachable:
                continue
            reachable.add(func)
            for callee in self.call_graph.get(func, set()):
                if callee in self.defined_funcs and callee not in reachable:
                    stack.append(callee)
        return reachable

    def visit_FunctionDef(self, node):
        self.defined_funcs.add(node.name)
        # Scan decorators so decorated calls are counted as "used"
        for decorator in node.decorator_list:
            self._scan_calls(decorator)
        # Scan default argument values (e.g. def f(x=helper()) )
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
            self._scan_calls(default)
        # Save outer context and enter the function scope BEFORE creating the header
        # node so the header is tagged to its own function group.
        prev_function = self.current_function
        prev_last = self.last_node
        self.current_function = node.name
        fn = self.new_node(f"function: {node.name}", self._line_of(node))
        self.func_node_ids[node.name] = fn["id"]
        # Each function is an isolated sub-graph — do NOT connect to outer flow.
        self.last_node = fn
        for stmt in node.body:
            self.visit(stmt)
        self.current_function = prev_function
        # Restore outer flow to where it was BEFORE this function def so the
        # next top-level statement doesn't chain through the function header.
        self.last_node = prev_last

    def visit_If(self, node):
        """Build the full if / elif / else chain.
        All elif and else branches fan out directly from the first 'if' node
        so the graph shows a decision tree, not a linear chain.

        Constant-condition pruning: when the condition is a known-falsy value
        (or a variable assigned a falsy constant) the then-body is marked dead
        and its calls are excluded from the reachability graph.  The complement
        applies when the condition is always-truthy (else-body becomes dead).
        """
        first_cond = self.new_node("if condition", self._line_of(node))
        self.connect(first_cond, "conditional")
        # Scan condition for calls (e.g. if is_valid(x):)
        self._scan_calls(node.test)
        self._emit_call_edges(first_cond, node.test)
        save = self.last_node   # = first_cond (set by connect)

        always_false = self._is_always_false(node.test)
        always_true  = self._is_always_true(node.test)

        # True body — connect from first_cond
        self.last_node = first_cond
        if always_false:
            self._dead_branch_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        if always_false:
            self._dead_branch_depth -= 1

        # Walk the orelse chain: every elif/else branches from first_cond
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                # elif: create a node and branch from first_cond
                elif_node = orelse[0]
                elif_cond = self.new_node("elif condition", self._line_of(elif_node))
                elif_edge = {"from": first_cond["id"], "to": elif_cond["id"]}
                self.conditionals.append(elif_edge)
                self.last_node = elif_cond
                if always_true:
                    self._dead_branch_depth += 1
                for stmt in elif_node.body:
                    self.visit(stmt)
                if always_true:
                    self._dead_branch_depth -= 1
                orelse = elif_node.orelse
            else:
                # else block: branch from first_cond
                else_n = self.new_node("else", self._line_of(orelse[0]) if orelse else None)
                else_edge = {"from": first_cond["id"], "to": else_n["id"]}
                self.conditionals.append(else_edge)
                self.last_node = else_n
                if always_true:
                    self._dead_branch_depth += 1
                for stmt in orelse:
                    self.visit(stmt)
                if always_true:
                    self._dead_branch_depth -= 1
                orelse = []

        # Restore so the statement after the entire if/elif/else block
        # connects from first_cond (standard CFG convergence point)
        self.last_node = save

    def _scan_calls(self, node):
        """Walk any Python AST subtree and record all function references.

        Two categories are tracked:
        1. Direct calls  — ast.Call nodes (foo(), obj.method())
        2. Name references — ast.Name nodes whose id is a defined function.
           This catches higher-order usages like map(foo, items),
           callback = foo, and [handler1, handler2] that never use call syntax.

        defined_funcs must be pre-populated (done in parse()) before this
        helper is invoked so that category-2 lookups are accurate.
        """
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = (getattr(child.func, "id", None)
                        or getattr(child.func, "attr", None))
                if name:
                    self._record_call(name)
            elif isinstance(child, ast.Name) and child.id in self.defined_funcs:
                # Function referenced by name without being called directly
                # (passed as argument, stored in variable, used in list, etc.)
                self._record_call(child.id)

    def visit_For(self, node):
        try:
            condition = ast.unparse(node.target) + " in " + ast.unparse(node.iter)
        except Exception:
            condition = "for ... in ..."
        loop = self.new_node("for loop", self._line_of(node))
        loop["loop_type"] = "for"
        loop["loop_condition"] = condition
        loop["is_infinite"] = False
        self.connect(loop, "loop")
        prev = self.last_node
        # Scan iterator expression for calls (e.g. for x in get_items():)
        self._scan_calls(node.iter)
        self._emit_call_edges(loop, node.iter)
        for stmt in node.body:
            self.visit(stmt)
        # Back-edge from end of loop body to loop header
        if (self.last_node
                and self.last_node["id"] != loop["id"]
                and self.last_node["label"] not in ("return", "break", "continue")):
            self.loops.append({"from": self.last_node["id"], "to": loop["id"]})
        self.last_node = prev

    def visit_While(self, node):
        try:
            cond_text = ast.unparse(node.test)
        except Exception:
            cond_text = "..."
        # Infinite if condition is an always-truthy constant (True, 1, etc.)
        is_inf = isinstance(node.test, ast.Constant) and bool(node.test.value)
        loop = self.new_node("while loop", self._line_of(node))
        loop["loop_type"] = "while"
        loop["loop_condition"] = cond_text
        loop["is_infinite"] = is_inf
        self.connect(loop, "loop")
        prev = self.last_node
        # Scan loop condition for calls (e.g. while has_more():)
        self._scan_calls(node.test)
        self._emit_call_edges(loop, node.test)
        for stmt in node.body:
            self.visit(stmt)
        # Back-edge from end of loop body to loop header
        if (self.last_node
                and self.last_node["id"] != loop["id"]
                and self.last_node["label"] not in ("return", "break", "continue")):
            self.loops.append({"from": self.last_node["id"], "to": loop["id"]})
        self.last_node = prev

    def visit_Expr(self, node):
        """Handle bare expression statements (e.g. standalone function calls
        like foo() or print('hi') at any scope level).
        Without this, module-level calls are invisible to the CFG.
        """
        if isinstance(node.value, ast.Call):
            # Delegate to visit_Call
            self.visit_Call(node.value)
        else:
            # Other expressions — just scan for references
            self._scan_calls(node.value)

    def _emit_call_edges(self, from_node, ast_expr):
        """Walk ast_expr and add call_edges from from_node to every user-defined
        function that is called within that expression. Handles forward references
        by relying on func_node_ids being pre-populated via _defined_funcs."""
        for child in ast.walk(ast_expr):
            if isinstance(child, ast.Call):
                name = (getattr(child.func, "id", None)
                        or getattr(child.func, "attr", None))
                if name and name in self.func_node_ids:
                    self.call_edges.append(
                        {"from": from_node["id"], "to": self.func_node_ids[name]}
                    )

    def visit_Call(self, node):
        name = getattr(node.func, "id", getattr(node.func, "attr", "call"))
        self._record_call(name)
        call = self.new_node(f"call: {name}", self._line_of(node))
        self.connect(call)
        # Inter-procedural edge: call site → function header (user-defined only)
        if name in self.func_node_ids:
            self.call_edges.append({"from": call["id"], "to": self.func_node_ids[name]})
        # Scan arguments for nested calls (e.g. print(calculate(x)))
        for arg in node.args:
            self._scan_calls(arg)
        for kw in node.keywords:
            self._scan_calls(kw.value)

    def visit_Assign(self, node):
        # Track simple `name = <constant>` for dead-branch detection.
        # Non-constant assignments invalidate any previously known value.
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            var = node.targets[0].id
            if isinstance(node.value, ast.Constant):
                self.const_values[var] = node.value.value
            else:
                self.const_values.pop(var, None)
        assign = self.new_node("assignment", self._line_of(node))
        self.connect(assign)
        # Scan RHS for function calls (e.g. x = foo(y))
        if node.value:
            self._scan_calls(node.value)
            # Add inter-procedural edges for inline calls (e.g. x = helper(y))
            self._emit_call_edges(assign, node.value)

    def visit_Return(self, node):
        ret = self.new_node("return", self._line_of(node))
        self.connect(ret)
        # Scan return value for function calls (e.g. return compute(x))
        if node.value:
            self._scan_calls(node.value)
            # Add inter-procedural edges for inline calls (e.g. return helper(x))
            self._emit_call_edges(ret, node.value)

    def visit_Break(self, node):
        brk = self.new_node("break", self._line_of(node))
        self.connect(brk)

    def visit_Continue(self, node):
        cont = self.new_node("continue", self._line_of(node))
        self.connect(cont)

    def visit_AsyncFunctionDef(self, node):
        self.defined_funcs.add(node.name)
        # Scan decorators and default argument values
        for decorator in node.decorator_list:
            self._scan_calls(decorator)
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
            self._scan_calls(default)
        prev_function = self.current_function
        prev_last = self.last_node
        self.current_function = node.name
        fn = self.new_node(f"function: {node.name}", self._line_of(node))
        self.func_node_ids[node.name] = fn["id"]
        # Isolated sub-graph — do NOT connect to outer flow.
        self.last_node = fn
        for stmt in node.body:
            self.visit(stmt)
        self.current_function = prev_function
        self.last_node = prev_last

    def visit_Lambda(self, node):
        """Scan lambda body for calls — prevents false unused-function reports."""
        self._scan_calls(node.body)

    def visit_ListComp(self, node):
        self._scan_calls(node.elt)
        for gen in node.generators:
            self._scan_calls(gen.iter)
            for cond in gen.ifs:
                self._scan_calls(cond)

    def visit_SetComp(self, node):
        self._scan_calls(node.elt)
        for gen in node.generators:
            self._scan_calls(gen.iter)
            for cond in gen.ifs:
                self._scan_calls(cond)

    def visit_DictComp(self, node):
        self._scan_calls(node.key)
        self._scan_calls(node.value)
        for gen in node.generators:
            self._scan_calls(gen.iter)
            for cond in gen.ifs:
                self._scan_calls(cond)

    def visit_GeneratorExp(self, node):
        self._scan_calls(node.elt)
        for gen in node.generators:
            self._scan_calls(gen.iter)
            for cond in gen.ifs:
                self._scan_calls(cond)

    def visit_Try(self, node):
        try_n = self.new_node("try block", self._line_of(node))
        self.connect(try_n)
        save = self.last_node
        for stmt in node.body:
            self.visit(stmt)
        for handler in node.handlers:
            handler_label = "except"
            if handler.type:
                try:
                    handler_label = f"except {ast.unparse(handler.type)}"
                except Exception:
                    pass
            h_n = self.new_node(handler_label, self._line_of(handler))
            self.conditionals.append({"from": try_n["id"], "to": h_n["id"]})
            self.last_node = h_n
            for stmt in handler.body:
                self.visit(stmt)
        # Handle else clause (executes if no exception was raised)
        if node.orelse:
            else_n = self.new_node("try-else", self._line_of(node.orelse[0]) if node.orelse else None)
            self.edges.append({"from": try_n["id"], "to": else_n["id"]})
            self.last_node = else_n
            for stmt in node.orelse:
                self.visit(stmt)
        # Handle finally block (always executes)
        if node.finalbody:
            fin_n = self.new_node("finally", self._line_of(node.finalbody[0]) if node.finalbody else None)
            self.edges.append({"from": try_n["id"], "to": fin_n["id"]})
            self.last_node = fin_n
            for stmt in node.finalbody:
                self.visit(stmt)
        self.last_node = save

    def visit_ClassDef(self, node):
        cls_n = self.new_node(f"class: {node.name}", self._line_of(node))
        self.connect(cls_n)
        save = self.last_node
        self.last_node = cls_n
        for stmt in node.body:
            self.visit(stmt)
        self.last_node = save

    def visit_With(self, node):
        items = []
        for item in node.items:
            try:
                ctx = ast.unparse(item.context_expr)
            except Exception:
                ctx = "..."
            items.append(ctx)
        label = "with " + ", ".join(items)
        with_n = self.new_node(label, self._line_of(node))
        self.connect(with_n)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AsyncWith(self, node):
        items = []
        for item in node.items:
            try:
                ctx = ast.unparse(item.context_expr)
            except Exception:
                ctx = "..."
            items.append(ctx)
        label = "async with " + ", ".join(items)
        with_n = self.new_node(label, self._line_of(node))
        self.connect(with_n)
        for stmt in node.body:
            self.visit(stmt)


def _dedup_edges(edge_list):
    """Remove duplicate edges from a list, preserving order."""
    seen = set()
    result = []
    for e in edge_list:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def parse(code: str):
    """Unified interface - Returns dict with nodes, edges, loops, conditionals"""
    tree = ast.parse(code)

    cfg = CFGBuilder()

    # Pre-populate defined_funcs with a first pass so that _scan_calls can
    # detect Name references (e.g. map(foo, items)) during the main traversal.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cfg.defined_funcs.add(node.name)

    # Always start with a START node so the graph has a clear entry point
    start = cfg.new_node("START")
    cfg.last_node = start

    # Visit each top-level statement manually so both function defs
    # and standalone expressions (calls, assignments) get proper flow edges.
    for stmt in tree.body:
        cfg.visit(stmt)

    # Unused = defined but never explicitly called.
    # Exclude dunder methods (__init__, __str__, etc.) — called implicitly by Python.
    unused = sorted(
        f for f in (cfg.defined_funcs - cfg.reachable_functions())
        if not (f.startswith("__") and f.endswith("__"))
    )

    # Deduplicate all edge lists
    cfg.edges = _dedup_edges(cfg.edges)
    cfg.loops = _dedup_edges(cfg.loops)
    cfg.conditionals = _dedup_edges(cfg.conditionals)
    cfg.call_edges = _dedup_edges(cfg.call_edges)

    # ── Recursion detection ────────────────────────────────────────────────
    direct_recursion = set()
    mutual_recursion = set()
    for func in cfg.defined_funcs:
        callees = cfg.call_graph.get(func, set())
        if func in callees:
            direct_recursion.add(func)
        # Check indirect recursion via call-graph DFS
        visited = set()
        stack = [c for c in callees if c in cfg.defined_funcs and c != func]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            if func in cfg.call_graph.get(current, set()):
                mutual_recursion.add(func)
                break
            for callee in cfg.call_graph.get(current, set()):
                if callee in cfg.defined_funcs and callee not in visited:
                    stack.append(callee)

    # Mark recursive call nodes for frontend highlighting
    all_recursive = direct_recursion | mutual_recursion
    for n in cfg.nodes:
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

    # Build function_groups: func_name → [node_ids]
    # Every node carries a "func" tag set during creation.
    groups = defaultdict(list)
    for n in cfg.nodes:
        groups[n.get("func", "__toplevel__")].append(n["id"])
    function_groups = dict(groups)

    return {
        "nodes": cfg.nodes,
        "edges": cfg.edges,
        "loops": cfg.loops,
        "conditionals": cfg.conditionals,
        "call_edges": cfg.call_edges,
        "function_groups": function_groups,
        "unused_functions": unused,
        "recursion": {
            "direct": sorted(direct_recursion),
            "mutual": sorted(mutual_recursion),
        }
    }
