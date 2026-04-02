# backend/parsers/java_parser.py

from collections import defaultdict

import javalang


# Methods implicitly called by the Java runtime or standard library —
# never flag these as unused regardless of explicit call sites.
_JAVA_IMPLICIT_METHODS = frozenset({
    # Object contract
    'equals', 'hashCode', 'toString', 'compareTo', 'clone', 'finalize',
    # Iterable / Iterator
    'iterator', 'hasNext', 'next', 'remove',
    # Comparable / Comparator
    'compare',
    # Runnable / Callable / Supplier / Consumer / Function / Predicate
    'run', 'call', 'get', 'accept', 'apply', 'test',
    # Servlet
    'doGet', 'doPost', 'doPut', 'doDelete', 'service', 'init', 'destroy',
    # Lifecycle
    'handle', 'execute', 'invoke', 'perform',
})

# Annotations whose presence means the method is invoked by a framework or
# the JVM, not explicitly called from user code.
_IMPLICIT_ANNOTATION_NAMES = frozenset({
    'Override',
    # JUnit 4 / 5
    'Test', 'Before', 'After', 'BeforeClass', 'AfterClass',
    'BeforeEach', 'AfterEach', 'BeforeAll', 'AfterAll',
    # Spring
    'Bean', 'PostConstruct', 'PreDestroy', 'Scheduled',
    'EventListener', 'MessageMapping',
    'RequestMapping', 'GetMapping', 'PostMapping',
    'PutMapping', 'DeleteMapping', 'PatchMapping',
    # JAX-RS
    'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS',
    # CDI / EJB
    'Inject', 'EJB',
    # Android
    'OnClick',
})


def parse(code: str):
    """Unified interface - Returns dict with nodes, edges, loops, conditionals"""
    nodes, edges, loops, conditionals = [], [], [], []

    tree = javalang.parse.parse(code)

    node_id = 0
    last_node = None
    _current_func = [None]  # mutable cell so nested closures can read it

    def line_of(node):
        pos = getattr(node, "position", None)
        if pos is None:
            return None
        if hasattr(pos, "line"):
            return pos.line
        if isinstance(pos, tuple) and pos:
            return pos[0]
        return None

    def new_node(label, line=None):
        nonlocal node_id
        node = {"id": f"n{node_id}", "label": label,
                "func": _current_func[0] or "__toplevel__"}
        if line is not None:
            node["line"] = line
        nodes.append(node)
        node_id += 1
        return node

    def connect(n, edge_type="normal"):
        nonlocal last_node
        if last_node:
            edge = {"from": last_node["id"], "to": n["id"]}
            if edge_type == "loop":
                loops.append(edge)
            elif edge_type == "conditional":
                conditionals.append(edge)
            else:
                edges.append(edge)
        last_node = n

    def _java_expr_str(node):
        """Best-effort string serialization of a javalang expression node."""
        if node is None:
            return ""
        if hasattr(node, 'value'):
            return str(node.value)
        if hasattr(node, 'member'):
            qualifier = getattr(node, 'qualifier', None)
            if qualifier:
                return f"{qualifier}.{node.member}"
            return str(node.member)
        if hasattr(node, 'operand') and hasattr(node, 'operator'):
            return f"{node.operator}{_java_expr_str(node.operand)}"
        if hasattr(node, 'operandl') and hasattr(node, 'operator'):
            r = getattr(node, 'operandr', None)
            return f"{_java_expr_str(node.operandl)} {node.operator} {_java_expr_str(r)}"
        return type(node).__name__

    def _in_else(path):
        """True if the current node is inside the else_statement of the nearest
        enclosing IfStatement."""
        for i in range(len(path) - 1, -1, -1):
            ancestor = path[i]
            if isinstance(ancestor, javalang.tree.IfStatement):
                if i + 1 < len(path):
                    child = path[i + 1]
                    return child is ancestor.else_statement
                return False
        return False

    def _enclosing_callable(path):
        for ancestor in reversed(path):
            if isinstance(ancestor, javalang.tree.MethodDeclaration):
                return ancestor.name
            if isinstance(ancestor, javalang.tree.ConstructorDeclaration):
                return ancestor.name
        return None

    def _reachable_functions(defined_funcs, call_graph, constructor_names,
                             implicit_entry_names):
        """Walk the call graph and return all reachable function names.

        Seed the traversal from:
        1. main()           — standard Java entry point
        2. All constructors — they are called externally when objects are created
        3. implicit_entry_names — methods marked @Override / framework annotations
        4. Field/static initialiser calls stored under '__field_init__'
        """
        reachable = set()
        stack = []

        if "main" in defined_funcs:
            stack.append("main")

        # Constructors are entry points (called externally)
        for name in constructor_names:
            if name in defined_funcs and name not in stack:
                stack.append(name)

        # Framework / polymorphic-dispatched methods
        for name in implicit_entry_names:
            if name in defined_funcs and name not in stack:
                stack.append(name)

        # Field/static initialiser call targets (outside any method body)
        for name in call_graph.get('__field_init__', set()):
            if name in defined_funcs and name not in stack:
                stack.append(name)

        while stack:
            func = stack.pop()
            if func in reachable:
                continue
            reachable.add(func)
            for callee in call_graph.get(func, set()):
                if callee in defined_funcs and callee not in reachable:
                    stack.append(callee)
        return reachable

    # ── Dead-branch helpers (source-position based) ────────────────────────────
    import re as _re

    _FALSY_JAVA_RE = _re.compile(r'^\s*(?:0+\.?0*|false|null|"")\s*$')

    def _find_java_const_vars(src):
        """Return dict of {name: float} for all constant-assigned vars.
        A later non-constant assignment removes the name (conservative).
        """
        consts = {}

        def _parse_val(s):
            s = s.strip()
            if _FALSY_JAVA_RE.match(s):
                return 0.0
            if s == 'true':
                return 1.0
            try:
                return float(s.rstrip('lLfFdD'))
            except ValueError:
                return None

        for m in _re.finditer(
            r'(?:int|boolean|long|short|byte|char|Integer|Boolean|String|Object)\s+(\w+)\s*=\s*([^;,\n]+)',
            src, _re.MULTILINE
        ):
            v = _parse_val(m.group(2))
            if v is not None:
                consts[m.group(1)] = v
            else:
                consts.pop(m.group(1), None)

        for m in _re.finditer(r'(?<![=!<>])=(?!=)\s*([^;,\n]+)', src, _re.MULTILINE):
            val_s = m.group(1).strip()
            pre = src[:m.start()].rstrip()
            nm = _re.search(r'\b(\w+)\s*$', pre)
            if not nm:
                continue
            v = _parse_val(val_s)
            if v is not None:
                consts[nm.group(1)] = v
            else:
                consts.pop(nm.group(1), None)
        return consts

    def _find_java_falsy_vars(src):  # kept for backward compatibility
        return {name for name, val in _find_java_const_vars(src).items() if not val}

    def _eval_java_expr(expr, const_vars):
        """Try to evaluate a simple Java condition string.
        Returns True if condition is always false, None if undetermined.
        """
        expr = expr.strip()
        if _FALSY_JAVA_RE.match(expr):
            return True
        if expr in const_vars and not const_vars[expr]:
            return True

        cmp_m = _re.match(r'^(.+?)\s*(==|!=|<=|>=|<|>)\s*(.+)$', expr)
        if not cmp_m:
            return None

        lhs_s, op, rhs_s = cmp_m.group(1).strip(), cmp_m.group(2), cmp_m.group(3).strip()

        def _resolve(s):
            if _FALSY_JAVA_RE.match(s):
                return 0.0
            if s in const_vars:
                return const_vars[s]
            try:
                return float(s.rstrip('lLfFdD'))
            except ValueError:
                return None

        lv, rv = _resolve(lhs_s), _resolve(rhs_s)
        if lv is None or rv is None:
            return None

        try:
            if op == '==':  result = (lv == rv)
            elif op == '!=': result = (lv != rv)
            elif op == '<':  result = (lv < rv)
            elif op == '>':  result = (lv > rv)
            elif op == '<=': result = (lv <= rv)
            elif op == '>=': result = (lv >= rv)
            else: return None
        except Exception:
            return None

        return not result  # True → condition is always FALSE (dead branch)

    def _find_java_dead_if_line_ranges(src, const_vars):
        """Return list of (start_line, end_line) pairs (1-based, inclusive)
        for the then-body of if-statements whose condition is always false.
        Handles literals, known-falsy vars, and comparisons (x < 0 where x=5).
        """
        ranges = []
        if_pat = _re.compile(r'\bif\s*\(', _re.MULTILINE)
        for m in if_pat.finditer(src):
            paren_start = m.end()
            depth = 1
            cursor = paren_start
            while cursor < len(src) and depth > 0:
                if src[cursor] == '(':   depth += 1
                elif src[cursor] == ')': depth -= 1
                cursor += 1
            condition = src[paren_start:cursor - 1]

            is_dead = _eval_java_expr(condition, const_vars)
            if not is_dead:
                continue

            after = src[cursor - 1 + 1:]
            after_stripped = after.lstrip()
            if after_stripped.startswith('{'):
                brace_abs = (cursor - 1 + 1) + (len(after) - len(after_stripped))
                depth2 = 0
                close_brace = -1
                for idx in range(brace_abs, len(src)):
                    if src[idx] == '{':   depth2 += 1
                    elif src[idx] == '}':
                        depth2 -= 1
                        if depth2 == 0:
                            close_brace = idx
                            break
                if close_brace != -1:
                    start_line = src[:brace_abs].count('\n') + 1
                    end_line   = src[:close_brace].count('\n') + 1
                    ranges.append((start_line, end_line))
        return ranges

    def _in_dead_line_range(lineno, dead_ranges):
        if lineno is None:
            return False
        return any(s <= lineno <= e for s, e in dead_ranges)

    _java_const_vars  = _find_java_const_vars(code)
    _java_dead_ranges = _find_java_dead_if_line_ranges(code, _java_const_vars)

    last_node = None
    last_if_node     = None
    last_switch_node = None
    defined_funcs    = set()
    called_funcs     = set()
    call_graph       = defaultdict(set)
    constructor_names    = set()   # constructors are implicit entry points
    implicit_entry_names = set()   # @Override / framework-annotated methods
    func_node_ids        = {}      # method/constructor name → node id for inter-proc edges
    call_edges           = []      # inter-procedural: call site → function header
    _loop_stack          = []      # [(loop_cfg_node, loop_ast_node), ...]
    _LOOP_AST_TYPES      = (javalang.tree.ForStatement,
                            javalang.tree.WhileStatement,
                            javalang.tree.DoStatement)

    for path, node in tree:
        # Detect when we've exited a loop scope — create back-edge
        while _loop_stack:
            loop_cfg, loop_ast = _loop_stack[-1]
            if any(p is loop_ast for p in path) or node is loop_ast:
                break
            _loop_stack.pop()
            if (last_node and last_node["id"] != loop_cfg["id"]
                    and last_node["label"] not in ("return", "break", "continue")):
                loops.append({"from": last_node["id"], "to": loop_cfg["id"]})
            last_node = loop_cfg
        if isinstance(node, javalang.tree.MethodDeclaration):
            # Skip abstract / interface methods — they have no body
            if node.body is None:
                continue
            defined_funcs.add(node.name)

            # Methods with framework/polymorphism annotations are entry points
            annotation_names = {a.name for a in (node.annotations or [])}
            if annotation_names & _IMPLICIT_ANNOTATION_NAMES:
                implicit_entry_names.add(node.name)

            # Each method is an isolated subgraph — no edge from previous method.
            # Tag this method's nodes by setting _current_func before new_node.
            last_node = None
            _current_func[0] = node.name
            _lbl = "START" if node.name == "main" else f"method: {node.name}"
            n = new_node(_lbl, line_of(node))
            func_node_ids[node.name] = n["id"]
            connect(n)
            last_if_node = None
            last_switch_node = None

        elif isinstance(node, javalang.tree.ConstructorDeclaration):
            if node.body is None:
                continue
            defined_funcs.add(node.name)
            constructor_names.add(node.name)
            # Each constructor is an isolated subgraph — no edge from previous method.
            last_node = None
            _current_func[0] = node.name
            n = new_node(f"constructor: {node.name}", line_of(node))
            func_node_ids[node.name] = n["id"]
            connect(n)
            last_if_node = None
            last_switch_node = None

        elif isinstance(node, javalang.tree.IfStatement):
            n = new_node("if condition", line_of(node))
            in_else = _in_else(path)
            if in_else and last_if_node:
                edge = {"from": last_if_node["id"], "to": n["id"]}
                conditionals.append(edge)
                last_node = n
            else:
                connect(n, "conditional")
            last_if_node = n

        elif isinstance(node, javalang.tree.SwitchStatement):
            n = new_node("switch", line_of(node))
            connect(n, "conditional")
            last_switch_node = n
            last_if_node = None

        elif isinstance(node, javalang.tree.SwitchStatementCase):
            if node.case:
                c = node.case[0]
                raw = getattr(c, 'value', None) or getattr(c, 'member', None) or str(c)
                label = f"case {raw}"
            else:
                label = "default"
            n = new_node(label, line_of(node))
            if last_switch_node:
                edge = {"from": last_switch_node["id"], "to": n["id"]}
                conditionals.append(edge)
                last_node = n
            else:
                connect(n)
            last_if_node = None

        elif isinstance(node, javalang.tree.ForStatement):
            is_inf = False
            condition = "..."
            try:
                ctrl = node.control
                if hasattr(ctrl, 'condition') and ctrl.condition is not None:
                    condition = _java_expr_str(ctrl.condition)
                    if condition.lower() in ('true', '1'):
                        is_inf = True
                elif hasattr(ctrl, 'condition') and ctrl.condition is None:
                    condition = "(none — infinite)"
                    is_inf = True
                elif hasattr(ctrl, 'iterable'):
                    condition = _java_expr_str(ctrl.iterable)
            except Exception:
                pass
            n = new_node("for loop", line_of(node))
            n["loop_type"] = "for"
            n["loop_condition"] = condition
            n["is_infinite"] = is_inf
            connect(n, "loop")
            _loop_stack.append((n, node))
            last_if_node = None

        elif isinstance(node, javalang.tree.WhileStatement):
            is_inf = False
            condition = "..."
            try:
                condition = _java_expr_str(node.condition)
                is_inf = condition.lower() in ('true', '1')
            except Exception:
                pass
            n = new_node("while loop", line_of(node))
            n["loop_type"] = "while"
            n["loop_condition"] = condition
            n["is_infinite"] = is_inf
            connect(n, "loop")
            _loop_stack.append((n, node))
            last_if_node = None

        elif isinstance(node, javalang.tree.DoStatement):
            is_inf = False
            condition = "..."
            try:
                condition = _java_expr_str(node.condition)
                is_inf = condition.lower() in ('true', '1')
            except Exception:
                pass
            n = new_node("do-while loop", line_of(node))
            n["loop_type"] = "do-while"
            n["loop_condition"] = condition
            n["is_infinite"] = is_inf
            connect(n, "loop")
            _loop_stack.append((n, node))
            last_if_node = None

        elif isinstance(node, javalang.tree.TryStatement):
            n = new_node("try block", line_of(node))
            connect(n)
            # Handle catch clauses
            if node.catches:
                try_n = n
                for catch in node.catches:
                    catch_type = ""
                    if catch.parameter and catch.parameter.types:
                        catch_type = " ".join(catch.parameter.types)
                    catch_label = f"catch ({catch_type})" if catch_type else "catch"
                    c_n = new_node(catch_label, line_of(catch))
                    conditionals.append({"from": try_n["id"], "to": c_n["id"]})
            # Handle finally block
            if node.finally_block:
                fin_n = new_node("finally", line_of(node))
                edges.append({"from": n["id"], "to": fin_n["id"]})
            last_if_node = None

        elif isinstance(node, javalang.tree.CatchClause):
            # Already handled above in TryStatement — skip to avoid duplicates
            continue

        elif isinstance(node, javalang.tree.ReturnStatement):
            n = new_node("return", line_of(node))
            connect(n)
            last_if_node = None
            last_switch_node = None

        elif isinstance(node, javalang.tree.BreakStatement):
            n = new_node("break", line_of(node))
            connect(n)

        elif isinstance(node, javalang.tree.ContinueStatement):
            n = new_node("continue", line_of(node))
            connect(n)

        elif isinstance(node, javalang.tree.ThrowStatement):
            n = new_node("throw", line_of(node))
            connect(n)

        elif isinstance(node, javalang.tree.MethodInvocation):
            in_else = _in_else(path)
            caller = _enclosing_callable(path)
            node_line = line_of(node)
            is_dead = _in_dead_line_range(node_line, _java_dead_ranges)
            # Always record in call_graph so unused-function analysis counts
            # syntactic calls even inside dead branches (they are still "used" code).
            called_funcs.add(node.member)
            if caller:
                call_graph[caller].add(node.member)
            else:
                # Field initialiser or static initialiser — track separately
                # so _reachable_functions can seed from these targets too
                call_graph['__field_init__'].add(node.member)
            n = new_node(f"call: {node.member}", node_line)
            if is_dead:
                n["dead"] = True
            if node.member in func_node_ids:
                call_edges.append({"from": n["id"], "to": func_node_ids[node.member]})
            if in_else and last_if_node:
                edge = {"from": last_if_node["id"], "to": n["id"]}
                edges.append(edge)
                last_node = n
            else:
                connect(n)

        elif isinstance(node, javalang.tree.ClassCreator):
            caller = _enclosing_callable(path)
            ctor_name = getattr(node.type, "name", None)
            if ctor_name:
                called_funcs.add(ctor_name)
                if caller:
                    call_graph[caller].add(ctor_name)
                else:
                    call_graph['__field_init__'].add(ctor_name)

        elif hasattr(javalang.tree, 'MethodReference') and \
                isinstance(node, javalang.tree.MethodReference):
            # Java 8+ method references: ClassName::methodName or obj::method
            method_name = getattr(node, 'member', None)
            if method_name:
                called_funcs.add(method_name)
                caller = _enclosing_callable(path)
                if caller:
                    call_graph[caller].add(method_name)
                else:
                    call_graph['__field_init__'].add(method_name)

        elif isinstance(node, javalang.tree.StatementExpression):
            # Non-call statement expressions (assignments, increments, etc.)
            expr = getattr(node, 'expression', None)
            if not isinstance(expr, javalang.tree.MethodInvocation):
                n = new_node("statement", line_of(node))
                connect(n)

        else:
            continue

    # Drain remaining loop stack — create back-edges for any loops still open
    while _loop_stack:
        loop_cfg, _ = _loop_stack.pop()
        if (last_node and last_node["id"] != loop_cfg["id"]
                and last_node["label"] not in ("return", "break", "continue")):
            loops.append({"from": last_node["id"], "to": loop_cfg["id"]})
        last_node = loop_cfg

    # ── Recursion detection ────────────────────────────────────────────────
    direct_recursion = set()
    mutual_recursion = set()
    for func in defined_funcs:
        callees = call_graph.get(func, set())
        if func in callees:
            direct_recursion.add(func)
        visited = set()
        stack_r = [c for c in callees if c in defined_funcs and c != func]
        while stack_r:
            current = stack_r.pop()
            if current in visited:
                continue
            visited.add(current)
            if func in call_graph.get(current, set()):
                mutual_recursion.add(func)
                break
            for callee in call_graph.get(current, set()):
                if callee in defined_funcs and callee not in visited:
                    stack_r.append(callee)

    all_recursive = direct_recursion | mutual_recursion
    for n in nodes:
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

    reachable = _reachable_functions(
        defined_funcs, call_graph, constructor_names, implicit_entry_names
    )

    # Each method/constructor is its own isolated sub-graph.
    # The old START→all-methods edges are intentionally removed so the layout
    # can arrange each function cluster independently.

    # Post-process: fill in call_edges for forward references
    # (calls to functions defined later in the source are missed during traversal)
    existing_call_edges = {(e["from"], e["to"]) for e in call_edges}
    for n in nodes:
        label = n.get("label", "")
        if label.startswith("call: "):
            name = label[6:]
            bare = name.split(".")[-1]
            target_id = func_node_ids.get(name) or func_node_ids.get(bare)
            if target_id:
                key = (n["id"], target_id)
                if key not in existing_call_edges:
                    call_edges.append({"from": n["id"], "to": target_id})
                    existing_call_edges.add(key)

    # Deduplicate all edge lists
    def _dedup(lst):
        seen = set()
        out = []
        for e in lst:
            k = (e["from"], e["to"])
            if k not in seen:
                seen.add(k)
                out.append(e)
        return out

    edges = _dedup(edges)
    loops = _dedup(loops)
    conditionals = _dedup(conditionals)
    call_edges = _dedup(call_edges)

    # Build function_groups: func_name → [node_ids]
    groups = {}
    for n in nodes:
        g = n.get("func", "__toplevel__")
        groups.setdefault(g, []).append(n["id"])

    return {
        "nodes": nodes,
        "edges": edges,
        "loops": loops,
        "conditionals": conditionals,
        "call_edges": call_edges,
        "function_groups": groups,
        "unused_functions": sorted(
            f for f in (defined_funcs - reachable)
            if f not in ("main",)           # JVM entry point
            and f not in _JAVA_IMPLICIT_METHODS  # runtime-called contracts
        ),
        "recursion": {
            "direct": sorted(direct_recursion),
            "mutual": sorted(mutual_recursion),
        }
    }
