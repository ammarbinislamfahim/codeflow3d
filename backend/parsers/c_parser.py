# backend/parsers/c_parser.py

from collections import defaultdict

from pycparser import c_parser as pyc_parser, c_ast, c_generator as pyc_generator


class CFGBuilder(c_ast.NodeVisitor):
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.loops = []
        self.conditionals = []
        self.call_edges = []         # inter-procedural: call site → function header
        self._pending_call_edges = []  # deferred (call_node_id, callee_name) resolved after full traversal
        self.node_id = 0
        self.last_node = None
        self.last_switch_node = None  # tracks switch for case/default branching
        self.defined_funcs = set()   # function names defined in this code
        self.called_funcs  = set()   # function names that appear in call sites
        self.call_graph = defaultdict(set)
        self.current_function = None
        self.func_node_ids = {}      # function name → node id for inter-proc edges
        # Track nodes already visited so we don't create duplicate nodes
        # when visit_FuncCall fires for calls already handled by _scan_calls
        self._visiting_compound = False
        self.const_values: dict = {} # var_name → constant value (for dead-branch detection)
        self._dead_branch_depth: int = 0  # >0 means inside an always-false branch
        self._called_ptr_vars: set = set()  # local variable names invoked as fp() / arr[i]()

    def _line_of(self, node):
        coord = getattr(node, "coord", None)
        return getattr(coord, "line", None)

    def new_node(self, label, line=None):
        node = {
            "id": f"n{self.node_id}",
            "label": label,
            # Tag every node with the function it belongs to for multi-CFG layout
            "func": self.current_function or "__toplevel__"
        }
        if line is not None:
            node["line"] = line
        if self._dead_branch_depth:
            node["dead"] = True   # inside an always-false (unreachable) branch
        self.nodes.append(node)
        self.node_id += 1
        return node

    def add_edge(self, from_node, to_node, edge_type="normal"):
        edge = {
            "from": from_node["id"],
            "to": to_node["id"]
        }
        if edge_type == "loop":
            self.loops.append(edge)
        elif edge_type == "conditional":
            self.conditionals.append(edge)
        else:
            self.edges.append(edge)

    def generic_connect(self, node):
        if self.last_node:
            self.add_edge(self.last_node, node)
        self.last_node = node

    def _record_call(self, name):
        self.called_funcs.add(name)
        # Record in the call graph regardless of dead-branch depth so that
        # functions referenced inside statically-dead blocks are still counted
        # as "syntactically used" (consistent with Python/JS/C++ parsers).
        if self.current_function:
            self.call_graph[self.current_function].add(name)

    # ── Constant-condition helpers ─────────────────────────────────────────
    _DEAD_SENTINEL = object()

    def _eval_const_c(self, cond_node):
        """Try to evaluate a C AST expression to a Python numeric/bool value.
        Returns the value on success, or _DEAD_SENTINEL if it cannot be resolved.
        Handles: Constant, ID (known vars), BinaryOp (+−*/% ==!=<><=>= && ||),
        UnaryOp (! - +), and nested combinations thereof.
        """
        if cond_node is None:
            return self._DEAD_SENTINEL
        if isinstance(cond_node, c_ast.Constant):
            try:
                # Strip integer suffixes like UL, u, L, etc.
                raw = cond_node.value.rstrip('uUlLfF')
                return float(raw)
            except (ValueError, TypeError):
                s = cond_node.value.lower()
                if s == 'true':  return 1.0
                if s == 'false': return 0.0
                return self._DEAD_SENTINEL
        if isinstance(cond_node, c_ast.ID):
            v = self.const_values.get(cond_node.name, self._DEAD_SENTINEL)
            if v is self._DEAD_SENTINEL:
                return self._DEAD_SENTINEL
            try:
                raw = str(v).rstrip('uUlLfF')
                return float(raw)
            except (ValueError, TypeError):
                return self._DEAD_SENTINEL
        if isinstance(cond_node, c_ast.UnaryOp):
            operand = self._eval_const_c(cond_node.expr)
            if operand is self._DEAD_SENTINEL:
                return self._DEAD_SENTINEL
            if cond_node.op == '!':  return float(not operand)
            if cond_node.op == '-':  return -operand
            if cond_node.op == '+':  return operand
            return self._DEAD_SENTINEL
        if isinstance(cond_node, c_ast.BinaryOp):
            lv = self._eval_const_c(cond_node.left)
            rv = self._eval_const_c(cond_node.right)
            if lv is self._DEAD_SENTINEL or rv is self._DEAD_SENTINEL:
                return self._DEAD_SENTINEL
            op = cond_node.op
            try:
                if op == '+':  return lv + rv
                if op == '-':  return lv - rv
                if op == '*':  return lv * rv
                if op == '/':  return lv / rv if rv != 0 else self._DEAD_SENTINEL
                if op == '%':  return float(int(lv) % int(rv)) if rv != 0 else self._DEAD_SENTINEL
                if op == '==': return float(lv == rv)
                if op == '!=': return float(lv != rv)
                if op == '<':  return float(lv < rv)
                if op == '>':  return float(lv > rv)
                if op == '<=': return float(lv <= rv)
                if op == '>=': return float(lv >= rv)
                if op == '&&': return float(lv and rv)
                if op == '||': return float(lv or rv)
            except Exception:
                pass
            return self._DEAD_SENTINEL
        return self._DEAD_SENTINEL

    def _is_always_false_c(self, cond_node) -> bool:
        """Return True when the C condition always evaluates to zero/false."""
        v = self._eval_const_c(cond_node)
        if v is self._DEAD_SENTINEL:
            return False
        return v == 0.0

    def _is_always_true_c(self, cond_node) -> bool:
        """Return True when the C condition always evaluates to non-zero/true."""
        v = self._eval_const_c(cond_node)
        if v is self._DEAD_SENTINEL:
            return False
        return v != 0.0

    def reachable_functions(self):
        reachable = set()
        stack = ["main"] if "main" in self.defined_funcs else []
        # Also seed from any function called at top level (outside any function)
        for callee in self.call_graph.get('__top_level__', set()):
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

    def _collect_called_ptr_vars(self, body_node) -> set:
        """Pre-scan a function body and return the set of local variable names
        that are actually invoked as a function pointer:  var()  or  arr[i]().

        Only variables present in this set should have the function identifiers
        from their initializers recorded as reachable.  A local pointer variable
        that is assigned but never called (e.g. `fp = foo; /* fp() never used */`)
        does NOT make `foo` reachable.
        """
        called: set = set()
        self._scan_called_ptr_vars(body_node, called)
        return called

    def _scan_called_ptr_vars(self, node, called: set):
        if isinstance(node, c_ast.FuncCall):
            callee = node.name
            # Direct variable call: fp()
            if isinstance(callee, c_ast.ID) and callee.name not in self.defined_funcs:
                called.add(callee.name)
            # Array variable call: arr[i]()
            elif isinstance(callee, c_ast.ArrayRef):
                base = callee.name
                if isinstance(base, c_ast.ID):
                    called.add(base.name)
        for _, child in node.children():
            self._scan_called_ptr_vars(child, called)

    def visit_FuncDef(self, node):
        self.defined_funcs.add(node.decl.name)
        # Save outer state — function body is a separate subgraph.
        # Set current_function BEFORE new_node so the header is tagged to its
        # own function group.
        prev_last = self.last_node
        prev_switch = self.last_switch_node
        prev_function = self.current_function
        prev_called_ptr_vars = self._called_ptr_vars
        self.last_switch_node = None
        self.current_function = node.decl.name
        # Pre-scan: find local variables that are actually invoked as fp()/arr[i](),
        # so visit_Decl can skip ID-reference recording for unused pointer variables.
        self._called_ptr_vars = self._collect_called_ptr_vars(node.body)
        # Entry-point function (main) becomes the green START node
        label = "START" if node.decl.name == "main" else f"Function: {node.decl.name}"
        func_node = self.new_node(label, self._line_of(node.decl))
        self.func_node_ids[node.decl.name] = func_node["id"]
        self.generic_connect(func_node)
        self.visit(node.body)
        # Restore outer state
        self.current_function = prev_function
        self.last_switch_node = prev_switch
        self.last_node = prev_last
        self._called_ptr_vars = prev_called_ptr_vars

    def visit_If(self, node):
        cond_node = self.new_node("if condition", self._line_of(node))
        self.generic_connect(cond_node)
        # Scan condition for calls (e.g. if (check() > 0))
        if node.cond:
            self._scan_calls(node.cond)
        save = self.last_node

        always_false = self._is_always_false_c(node.cond)
        always_true  = self._is_always_true_c(node.cond)

        if node.iftrue:
            true_node = self.new_node("if-true", self._line_of(node.iftrue))
            self.add_edge(cond_node, true_node, "conditional")
            self.last_node = true_node
            if always_false:
                self._dead_branch_depth += 1
            self.visit(node.iftrue)
            if always_false:
                self._dead_branch_depth -= 1

        if node.iffalse:
            false_node = self.new_node("if-false", self._line_of(node.iffalse))
            self.add_edge(cond_node, false_node, "conditional")
            self.last_node = false_node
            if always_true:
                self._dead_branch_depth += 1
            self.visit(node.iffalse)
            if always_true:
                self._dead_branch_depth -= 1

        self.last_node = save

    def visit_For(self, node):
        # for(;;) with no condition is an infinite loop
        is_inf = (node.cond is None)
        try:
            gen = pyc_generator.CGenerator()
            cond_str = gen.visit(node.cond) if node.cond else "(none — infinite)"
        except Exception:
            cond_str = "(no condition)" if is_inf else "for condition"
        loop_node = self.new_node("for loop", self._line_of(node))
        loop_node["loop_type"] = "for"
        loop_node["loop_condition"] = cond_str
        loop_node["is_infinite"] = is_inf
        if self.last_node:
            self.add_edge(self.last_node, loop_node, "loop")
        self.last_node = loop_node
        # Scan all loop-header expressions for calls (init, condition, increment)
        for expr in [node.init, node.cond, node.next]:
            if expr:
                self._scan_calls(expr)
        prev = self.last_node
        self.last_node = loop_node
        # If the condition is statically false the body is unreachable dead code.
        always_false = self._is_always_false_c(node.cond) if node.cond else False
        if always_false:
            self._dead_branch_depth += 1
        self.visit(node.stmt)
        if always_false:
            self._dead_branch_depth -= 1
        # Back-edge from end of loop body to loop header
        # Skip if the body ended on a return/break — those exit the loop.
        if (self.last_node
                and self.last_node["id"] != loop_node["id"]
                and self.last_node["label"] not in ("return", "break", "continue")):
            self.add_edge(self.last_node, loop_node, "loop")
        self.last_node = prev

    def visit_While(self, node):
        is_inf = False
        cond_str = "..."
        try:
            gen = pyc_generator.CGenerator()
            cond_str = gen.visit(node.cond) if node.cond else "..."
            if node.cond is not None and isinstance(node.cond, c_ast.Constant):
                try:
                    is_inf = int(node.cond.value) != 0
                except (ValueError, TypeError):
                    is_inf = str(node.cond.value).lower() in ("true", "1")
        except Exception:
            pass
        loop_node = self.new_node("while loop", self._line_of(node))
        loop_node["loop_type"] = "while"
        loop_node["loop_condition"] = cond_str
        loop_node["is_infinite"] = is_inf
        if self.last_node:
            self.add_edge(self.last_node, loop_node, "loop")
        self.last_node = loop_node
        # Scan condition for calls (e.g. while (has_more()))
        if node.cond:
            self._scan_calls(node.cond)
        prev = self.last_node
        self.last_node = loop_node
        # If the condition is statically false the body is unreachable dead code.
        always_false = self._is_always_false_c(node.cond) if node.cond else False
        if always_false:
            self._dead_branch_depth += 1
        self.visit(node.stmt)
        if always_false:
            self._dead_branch_depth -= 1
        if (self.last_node
                and self.last_node["id"] != loop_node["id"]
                and self.last_node["label"] not in ("return", "break", "continue")):
            self.add_edge(self.last_node, loop_node, "loop")
        self.last_node = prev

    def visit_DoWhile(self, node):
        is_inf = False
        cond_str = "..."
        try:
            gen = pyc_generator.CGenerator()
            cond_str = gen.visit(node.cond) if node.cond else "..."
            if node.cond is not None and isinstance(node.cond, c_ast.Constant):
                try:
                    is_inf = int(node.cond.value) != 0
                except (ValueError, TypeError):
                    is_inf = str(node.cond.value).lower() in ("true", "1")
        except Exception:
            pass
        # Body-entry node — this is where execution enters the loop
        loop_node = self.new_node("do-while loop", self._line_of(node))
        loop_node["loop_type"] = "do-while"
        loop_node["loop_condition"] = cond_str
        loop_node["is_infinite"] = is_inf
        if self.last_node:
            self.add_edge(self.last_node, loop_node, "loop")
        self.last_node = loop_node
        self.last_node = loop_node
        # Visit the loop body
        self.visit(node.stmt)
        # Condition-check node at the bottom of the body (the actual while(cond) test)
        cond_line = self._line_of(node.cond) if node.cond else self._line_of(node)
        cond_check = self.new_node(f"while ({cond_str})", cond_line)
        if self.last_node and self.last_node["id"] != cond_check["id"]:
            self.add_edge(self.last_node, cond_check)
        # Scan condition for any function calls (e.g. do { } while (check()))
        if node.cond:
            self._scan_calls(node.cond)
        # Back-edge: condition true → back to body entry
        self.add_edge(cond_check, loop_node, "loop")
        # Sequential exit: condition false → next statement after the loop
        self.last_node = cond_check

    def visit_Switch(self, node):
        switch_node = self.new_node("switch", self._line_of(node))
        self.generic_connect(switch_node)
        prev_switch = self.last_switch_node
        self.last_switch_node = switch_node
        self.last_node = switch_node
        # Visit the body — Case/Default visitors will branch from last_switch_node
        self.visit(node.stmt)
        self.last_switch_node = prev_switch

    def visit_Case(self, node):
        try:
            val = node.expr.value
        except Exception:
            val = "?"
        case_node = self.new_node(f"case {val}", self._line_of(node))
        if self.last_switch_node:
            edge = {"from": self.last_switch_node["id"], "to": case_node["id"]}
            self.conditionals.append(edge)
        else:
            self.generic_connect(case_node)
        self.last_node = case_node
        for stmt in node.stmts or []:
            self.visit(stmt)

    def visit_Default(self, node):
        default_node = self.new_node("default", self._line_of(node))
        if self.last_switch_node:
            edge = {"from": self.last_switch_node["id"], "to": default_node["id"]}
            self.conditionals.append(edge)
        else:
            self.generic_connect(default_node)
        self.last_node = default_node
        for stmt in node.stmts or []:
            self.visit(stmt)

    def _scan_calls(self, node, skip_id_refs: bool = False):
        """Recursively collect function references from any C AST subtree.

        Two categories are tracked:
        1. FuncCall nodes  — direct calls: foo(args)
        2. ID nodes whose name is a defined function — references without a
           call: function pointer assignments, callbacks passed as arguments
           (e.g. qsort(arr, n, sizeof(int), compare)).

        skip_id_refs=True disables category-2 recording.  Used by visit_Decl
        when the declared variable is never actually invoked as a function
        pointer, so its initializer should not pull target functions into the
        reachability graph.

        defined_funcs must be pre-populated (done in parse()) before this
        helper is invoked so that category-2 lookups are accurate.
        """
        if isinstance(node, c_ast.FuncCall):
            try:
                name = node.name.name
                self._record_call(name)
                # Also emit a pending call_edge for nested calls (e.g. add() inside printf() args)
                if self.last_node and name in self.defined_funcs:
                    self._pending_call_edges.append((self.last_node["id"], name))
            except Exception:
                pass
        elif (not skip_id_refs
              and isinstance(node, c_ast.ID)
              and node.name in self.defined_funcs):
            # Function referenced by name without being called directly
            self._record_call(node.name)
        for _, child in node.children():
            self._scan_calls(child, skip_id_refs=skip_id_refs)

    def visit_FuncCall(self, node):
        try:
            name = node.name.name
        except Exception:
            name = "func_call"
        self._record_call(name)
        call_node = self.new_node(f"call: {name}", self._line_of(node))
        self.generic_connect(call_node)
        # Defer inter-procedural edge resolution until after all FuncDefs are visited,
        # so forward calls (main calls foo defined below) are captured correctly.
        self._pending_call_edges.append((call_node["id"], name))
        # Scan arguments for function-pointer references passed as callbacks,
        # e.g. qsort(arr, n, sizeof(int), compare)  or  callIndirect(stealthFn)
        if node.args:
            self._scan_calls(node.args)

    def visit_Return(self, node):
        ret_node = self.new_node("return", self._line_of(node))
        self.generic_connect(ret_node)
        # Visit return expression to catch calls (e.g. return sum(a, b))
        # AND scan for function-pointer references returned by value
        # (e.g. return weirdTarget;  or  return condition ? fnA : fnB)
        if node.expr:
            self.visit(node.expr)
            self._scan_calls(node.expr)

    def visit_Goto(self, node):
        goto_node = self.new_node(f"goto {node.name}", self._line_of(node))
        self.generic_connect(goto_node)

    def visit_Break(self, node):
        brk = self.new_node("break", self._line_of(node))
        self.generic_connect(brk)

    def visit_Continue(self, node):
        cont = self.new_node("continue", self._line_of(node))
        self.generic_connect(cont)

    def visit_Compound(self, node):
        for stmt in node.block_items or []:
            self.visit(stmt)

    def visit_Decl(self, node):
        # Skip unnamed declarations (e.g. anonymous struct fields)
        if node.name is None:
            return
        # Skip function prototype declarations (int add(int, int);)
        if isinstance(node.type, c_ast.FuncDecl):
            return
        decl_node = self.new_node(f"decl: {node.name}", self._line_of(node))
        self.generic_connect(decl_node)
        # Track simple constant initialisers (e.g. int y = 0) for dead-branch detection
        if node.init and isinstance(node.init, c_ast.Constant):
            self.const_values[node.name] = node.init.value
        elif node.init is not None:
            self.const_values.pop(node.name, None)
        # Visit initializer to catch function calls (e.g. int x = compute(y))
        # AND scan for function-pointer assignments (e.g. void (*fp)() = myFunc).
        # Only record bare function-name ID references from the initializer when
        # the declared variable is actually invoked somewhere in this function
        # body (fp() or arr[i]()).  Variables that are assigned a function pointer
        # but never called do NOT make the target function reachable.
        if node.init:
            self.visit(node.init)
            skip = node.name not in self._called_ptr_vars
            self._scan_calls(node.init, skip_id_refs=skip)

    def visit_Assignment(self, node):
        assign_node = self.new_node("assignment", self._line_of(node))
        self.generic_connect(assign_node)
        # Track simple constant assignments (e.g. y = 0) for dead-branch detection
        if (node.op == '=' and isinstance(node.lvalue, c_ast.ID)
                and isinstance(node.rvalue, c_ast.Constant)):
            self.const_values[node.lvalue.name] = node.rvalue.value
        elif node.op == '=' and isinstance(node.lvalue, c_ast.ID):
            self.const_values.pop(node.lvalue.name, None)
        # Visit RHS to catch function calls AND scan for function-pointer
        # assignments (e.g. fp = myFunc  or  fp = &myFunc)
        if node.rvalue:
            self.visit(node.rvalue)
            self._scan_calls(node.rvalue)

    def visit_UnaryOp(self, node):
        # Handle standalone unary operations like i++ as statements
        try:
            gen = pyc_generator.CGenerator()
            text = gen.visit(node)
        except Exception:
            text = f"{node.op}"
        un_node = self.new_node(f"expr: {text}", self._line_of(node))
        self.generic_connect(un_node)


def _strip_directives(code: str) -> str:
    """Remove preprocessor directives and comments that pycparser cannot handle.

    pycparser parses clean C only — no preprocessor lines, no comments.
    Steps (order matters):
      1. Multi-line comments  /* ... */
      2. Single-line comments // ...
      3. Multi-line macros    #define FOO \\<newline>
      4. Single-line directives #include / #define / #pragma / etc.
    """
    import re
    # 1. Multi-line comments (non-greedy, DOTALL)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    # 2. Single-line comments
    code = re.sub(r'//[^\n]*', '', code)
    # 3. Multi-line macros (line ends with \)
    code = re.sub(r'#[^\n]*\\\n', '', code)
    # 4. Remaining single-line directives
    code = re.sub(r'^\s*#[^\n]*', '', code, flags=re.MULTILINE)
    return code


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
    """Unified interface for main.py - Returns dict with nodes, edges, loops, conditionals"""
    parser = pyc_parser.CParser()

    cleaned = _strip_directives(code)

    cfg = CFGBuilder()

    ast = parser.parse(cleaned)

    # Pre-populate defined_funcs so _scan_calls can detect ID references
    # (function pointers, callbacks) during the main traversal.
    for ext in ast.ext:
        if isinstance(ext, c_ast.FuncDef):
            cfg.defined_funcs.add(ext.decl.name)

    # last_node = None: each top-level FuncDef starts its own independent subgraph.
    cfg.last_node = None
    cfg.visit(ast)

    # Resolve pending call edges now that func_node_ids is fully populated
    # (handles forward references: main calling foo defined later in the file).
    for call_id, callee_name in cfg._pending_call_edges:
        if callee_name in cfg.func_node_ids:
            cfg.call_edges.append({"from": call_id, "to": cfg.func_node_ids[callee_name]})

    # Build function_groups: func_name → [node_ids]
    groups = defaultdict(list)
    for n in cfg.nodes:
        groups[n.get("func", "__toplevel__")].append(n["id"])
    function_groups = dict(groups)

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

    return {
        "nodes": cfg.nodes,
        "edges": cfg.edges,
        "loops": cfg.loops,
        "conditionals": cfg.conditionals,
        "call_edges": cfg.call_edges,
        "function_groups": function_groups,
        "unused_functions": sorted(
            f for f in (cfg.defined_funcs - cfg.reachable_functions())
            if f not in ("main",)  # entry points are called by the runtime
        ),
        "recursion": {
            "direct": sorted(direct_recursion),
            "mutual": sorted(mutual_recursion),
        }
    }
