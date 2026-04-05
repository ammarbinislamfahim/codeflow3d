#!/usr/bin/env python3
"""Comprehensive CFG parser test suite."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

errors = []
passed = 0

def check(name, result, checks):
    global passed
    ok = True
    nodes = {n["id"]: n for n in result.get("nodes", [])}
    edges_loop = [(e["from"], e["to"]) for e in result.get("loops", [])]
    edges_cond = [(e["from"], e["to"]) for e in result.get("conditionals", [])]
    edges_normal = [(e["from"], e["to"]) for e in result.get("edges", [])]
    all_edges = edges_normal + edges_loop + edges_cond

    if "min_nodes" in checks and len(nodes) < checks["min_nodes"]:
        errors.append("[%s] Expected >= %d nodes, got %d" % (name, checks["min_nodes"], len(nodes)))
        ok = False
    if "min_loops" in checks and len(edges_loop) < checks["min_loops"]:
        errors.append("[%s] Expected >= %d loop edges, got %d" % (name, checks["min_loops"], len(edges_loop)))
        ok = False
    if "min_conditionals" in checks and len(edges_cond) < checks["min_conditionals"]:
        errors.append("[%s] Expected >= %d cond edges, got %d" % (name, checks["min_conditionals"], len(edges_cond)))
        ok = False
    if "expected_labels" in checks:
        all_labels = [n["label"].lower() for n in nodes.values()]
        for lbl in checks["expected_labels"]:
            if not any(lbl.lower() in al for al in all_labels):
                errors.append('[%s] Missing label containing "%s"' % (name, lbl))
                ok = False
    if checks.get("loop_meta"):
        for nid, n in nodes.items():
            label = n["label"].lower()
            is_loop = any(kw in label for kw in ["for", "while", "do-while", "loop"])
            is_target = any(e[1] == nid for e in edges_loop)
            if is_loop and is_target:
                for field in ["loop_type", "loop_condition", "is_infinite"]:
                    if field not in n:
                        errors.append('[%s] Node "%s" missing %s' % (name, n["label"], field))
                        ok = False
    for src, dst in all_edges:
        if src not in nodes:
            errors.append("[%s] Bad edge source %s" % (name, src))
            ok = False
        if dst not in nodes:
            errors.append("[%s] Bad edge dest %s" % (name, dst))
            ok = False
    if ok:
        passed += 1
    return ok


from parsers.python_parser import parse as py_p
from parsers.c_parser import parse as c_p
from parsers.cpp_parser import parse as cpp_p
from parsers.java_parser import parse as java_p
from parsers.js_parser import parse as js_p

print("=" * 60)
print("PYTHON TESTS")
print("=" * 60)
check("PY-seq", py_p("x=1\ny=2\nprint(x+y)"), {"min_nodes": 3, "expected_labels": ["start", "assignment"]})
check("PY-if", py_p("x=10\nif x>5:\n    print(1)\nelse:\n    print(0)"), {"min_nodes": 4, "min_conditionals": 1})
check("PY-for", py_p("for i in range(10):\n    print(i)"), {"min_loops": 1, "loop_meta": True, "expected_labels": ["for loop"]})
check("PY-while", py_p("while True:\n    pass"), {"min_loops": 1, "loop_meta": True})
check("PY-nested", py_p("for i in range(5):\n    for j in range(5):\n        print(i,j)"), {"min_loops": 2, "loop_meta": True})
check("PY-func", py_p("def add(a,b):\n    return a+b\nresult=add(1,2)"), {"min_nodes": 3, "expected_labels": ["function: add", "return"]})
check("PY-try", py_p("try:\n    x=1/0\nexcept:\n    print(0)"), {"min_nodes": 3, "expected_labels": ["try"]})

print("=" * 60)
print("C TESTS")
print("=" * 60)
check("C-main", c_p("int main(){int x=5;return 0;}"), {"min_nodes": 2, "expected_labels": ["start", "return"]})
check("C-for", c_p('int main(){for(int i=0;i<10;i++){printf("x",i);}return 0;}'), {"min_loops": 1, "loop_meta": True, "expected_labels": ["for loop"]})
check("C-while", c_p("int main(){while(1){break;}return 0;}"), {"min_loops": 1, "loop_meta": True})
check("C-dowhile", c_p("int main(){int i=0;do{i++;}while(i<10);return 0;}"), {"min_loops": 1, "loop_meta": True})
check("C-if", c_p('int main(){int x=5;if(x>3){printf("b");}else{printf("s");}return 0;}'), {"min_conditionals": 1})
check("C-nested", c_p("int main(){for(int i=0;i<5;i++){for(int j=0;j<5;j++){}}return 0;}"), {"min_loops": 2, "loop_meta": True})
check("C-funcs", c_p("void helper(){}int main(){helper();return 0;}"), {"min_nodes": 3, "expected_labels": ["function: helper"]})

print("=" * 60)
print("C++ TESTS")
print("=" * 60)
check("CPP-main", cpp_p("int main(){int x=5;return 0;}"), {"min_nodes": 2, "expected_labels": ["start"]})
check("CPP-for", cpp_p("int main(){for(int i=0;i<10;i++){}return 0;}"), {"min_loops": 1, "loop_meta": True})
check("CPP-while", cpp_p("int main(){while(true){break;}return 0;}"), {"min_loops": 1, "loop_meta": True})
check("CPP-dowhile", cpp_p("int main(){int i=0;do{i++;}while(i<10);return 0;}"), {"min_loops": 1, "loop_meta": True})
check("CPP-range", cpp_p("int main(){int a[]={1,2,3};for(auto x:a){}return 0;}"), {"min_loops": 1, "loop_meta": True})
check("CPP-if", cpp_p("int main(){int x=5;if(x>3){return 1;}else{return 0;}}"), {"min_conditionals": 1})
check("CPP-nested", cpp_p("int main(){for(int i=0;i<5;i++){for(int j=0;j<5;j++){}}return 0;}"), {"min_loops": 2, "loop_meta": True})

print("=" * 60)
print("JAVA TESTS")
print("=" * 60)
check("JAVA-main", java_p("public class M{public static void main(String[] a){System.out.println(1);}}"), {"min_nodes": 2})
check("JAVA-for", java_p("public class M{public static void main(String[] a){for(int i=0;i<10;i++){System.out.println(i);}}}"), {"min_loops": 1, "loop_meta": True, "expected_labels": ["for loop"]})
check("JAVA-while", java_p("public class M{public static void main(String[] a){while(true){break;}}}"), {"min_loops": 1, "loop_meta": True})
check("JAVA-dowhile", java_p("public class M{public static void main(String[] a){int i=0;do{i++;}while(i<10);}}"), {"min_loops": 1, "loop_meta": True})
check("JAVA-if", java_p("public class M{public static void main(String[] a){int x=5;if(x>3){System.out.println(1);}else{System.out.println(0);}}}"), {"min_conditionals": 1})
check("JAVA-try", java_p("public class M{public static void main(String[] a){try{int x=1/0;}catch(Exception e){System.out.println(0);}}}"), {"min_nodes": 3, "expected_labels": ["try"]})

print("=" * 60)
print("JAVASCRIPT TESTS")
print("=" * 60)
check("JS-func", js_p("function hello(){console.log(1);}"), {"min_nodes": 2, "expected_labels": ["function: hello"]})
check("JS-for", js_p("function t(){for(let i=0;i<10;i++){console.log(i);}}"), {"min_loops": 1, "loop_meta": True})
check("JS-while", js_p("function t(){while(true){break;}}"), {"min_loops": 1, "loop_meta": True})
check("JS-dowhile", js_p("function t(){let i=0;do{i++;}while(i<10);}"), {"min_loops": 1, "loop_meta": True})
check("JS-forof", js_p("function t(){for(const x of [1,2,3]){console.log(x);}}"), {"min_loops": 1, "loop_meta": True})
check("JS-if", js_p("function t(){if(true){console.log(1);}else{console.log(0);}}"), {"min_conditionals": 1})
check("JS-arrow", js_p("const add=(a,b)=>a+b;const mul=(a,b)=>a*b;"), {"min_nodes": 2, "expected_labels": ["function: add", "function: mul"]})
check("JS-nested", js_p("function t(){for(let i=0;i<5;i++){for(let j=0;j<5;j++){console.log(i+j);}}}"), {"min_loops": 2, "loop_meta": True})

print("=" * 60)
print("INFINITE LOOP CROSS-LANGUAGE")
print("=" * 60)
for lang, p, code in [
    ("PY", py_p, "while True:\n    pass"),
    ("C", c_p, "int main(){while(1){}return 0;}"),
    ("CPP", cpp_p, "int main(){while(true){}return 0;}"),
    ("JAVA", java_p, "public class M{public static void main(String[] a){while(true){}}}"),
    ("JS", js_p, "function t(){while(true){}}"),
]:
    r = p(code)
    inf = [n for n in r["nodes"] if n.get("is_infinite")]
    if inf:
        passed += 1
    else:
        errors.append("[%s-INF] while(true) not infinite" % lang)

print()
print("=" * 60)
print("RECURSION DETECTION TESTS")
print("=" * 60)

# Python: direct recursion
r = py_p("def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n-1)\nfactorial(5)")
rec = r.get("recursion", {})
if "factorial" in rec.get("direct", []):
    passed += 1
else:
    errors.append("[PY-REC-DIRECT] factorial not detected as direct recursion")

# Python: mutual recursion
r = py_p("def is_even(n):\n    if n == 0:\n        return True\n    return is_odd(n-1)\ndef is_odd(n):\n    if n == 0:\n        return False\n    return is_even(n-1)\nis_even(4)")
rec = r.get("recursion", {})
if "is_even" in rec.get("mutual", []) and "is_odd" in rec.get("mutual", []):
    passed += 1
else:
    errors.append("[PY-REC-MUTUAL] is_even/is_odd not detected as mutual recursion (got %s)" % rec)

# C: direct recursion
r = c_p("int factorial(int n){if(n<=1)return 1;return n*factorial(n-1);}int main(){return factorial(5);}")
rec = r.get("recursion", {})
if "factorial" in rec.get("direct", []):
    passed += 1
else:
    errors.append("[C-REC-DIRECT] factorial not detected as direct recursion")

# C++: direct recursion
r = cpp_p("int factorial(int n){if(n<=1)return 1;return n*factorial(n-1);}int main(){return factorial(5);}")
rec = r.get("recursion", {})
if "factorial" in rec.get("direct", []):
    passed += 1
else:
    errors.append("[CPP-REC-DIRECT] factorial not detected as direct recursion")

# Java: direct recursion
r = java_p("public class M{public static int factorial(int n){if(n<=1)return 1;return n*factorial(n-1);}public static void main(String[] a){factorial(5);}}")
rec = r.get("recursion", {})
if "factorial" in rec.get("direct", []):
    passed += 1
else:
    errors.append("[JAVA-REC-DIRECT] factorial not detected as direct recursion")

# JS: direct recursion
r = js_p("function factorial(n){if(n<=1)return 1;return n*factorial(n-1);}const x=factorial(5);")
rec = r.get("recursion", {})
if "factorial" in rec.get("direct", []):
    passed += 1
else:
    errors.append("[JS-REC-DIRECT] factorial not detected as direct recursion")

# Verify recursive nodes are marked
r = py_p("def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n-1)\nfactorial(5)")
rec_nodes = [n for n in r["nodes"] if n.get("recursive")]
if rec_nodes:
    passed += 1
else:
    errors.append("[PY-REC-NODES] No nodes marked as recursive")

print()
print("=" * 60)
print("BREAK/CONTINUE TESTS")
print("=" * 60)

# Python break
r = py_p("for i in range(10):\n    if i == 5:\n        break\n    print(i)")
check("PY-break", r, {"expected_labels": ["break"]})

# Python continue
r = py_p("for i in range(10):\n    if i % 2 == 0:\n        continue\n    print(i)")
check("PY-continue", r, {"expected_labels": ["continue"]})

# C break (already tested via while(1){break;}, add explicit)
check("C-break", c_p("int main(){for(int i=0;i<10;i++){if(i==5)break;}return 0;}"), {"expected_labels": ["break"]})

# C++ break
check("CPP-break", cpp_p("int main(){for(int i=0;i<10;i++){if(i==5)break;}return 0;}"), {"expected_labels": ["break"]})

# Java break
check("JAVA-break", java_p("public class M{public static void main(String[] a){for(int i=0;i<10;i++){if(i==5)break;}}}"), {"expected_labels": ["break"]})

# JS break
check("JS-break", js_p("function t(){for(let i=0;i<10;i++){if(i===5)break;}}"), {"expected_labels": ["break"]})

print()
print("=" * 60)
print("FINALLY BLOCK TESTS")
print("=" * 60)

# Python try/finally
r = py_p("try:\n    x = 1/0\nexcept:\n    print('error')\nfinally:\n    print('cleanup')")
check("PY-finally", r, {"expected_labels": ["try", "finally"]})

# Python with statement
r = py_p("with open('file.txt') as f:\n    data = f.read()")
check("PY-with", r, {"expected_labels": ["with"]})

print()
print("=" * 60)
print("DEEP EDGE CORRECTNESS TESTS")
print("=" * 60)

# Test: Make sure the graph actually connects properly
# Factorial function - should have: function header -> if -> return/for -> return

def verify_flow(name, result, expected_flow_keywords):
    """Verify nodes appear in the right order with edges connecting them."""
    global passed
    nodes_list = result["nodes"]
    all_edges_list = result.get("edges", []) + result.get("loops", []) + result.get("conditionals", [])
    edge_set = set((e["from"], e["to"]) for e in all_edges_list)
    node_map = {n["id"]: n for n in nodes_list}

    # Find nodes matching each keyword (in order)
    matched_nodes = []
    for kw in expected_flow_keywords:
        found = None
        for n in nodes_list:
            if kw.lower() in n["label"].lower() and n["id"] not in [m["id"] for m in matched_nodes]:
                found = n
                break
        if found:
            matched_nodes.append(found)
        else:
            errors.append("[%s] Could not find node with keyword '%s'" % (name, kw))
            return False

    # For each consecutive pair, check there's a path (direct or indirect)
    all_ok = True
    for i in range(len(matched_nodes) - 1):
        src = matched_nodes[i]["id"]
        dst = matched_nodes[i + 1]["id"]
        # BFS
        visited = {src}
        queue = [src]
        found_path = False
        while queue:
            cur = queue.pop(0)
            if cur == dst:
                found_path = True
                break
            for s, d in edge_set:
                if s == cur and d not in visited:
                    visited.add(d)
                    queue.append(d)
        if not found_path:
            errors.append("[%s] No path from '%s' (%s) to '%s' (%s)" % (
                name, matched_nodes[i]["label"][:30], src,
                matched_nodes[i+1]["label"][:30], dst))
            all_ok = False

    if all_ok:
        passed += 1
    return all_ok


# Python factorial
r = py_p("def factorial(n):\n    if n <= 1:\n        return 1\n    result = 1\n    for i in range(2, n+1):\n        result *= i\n    return result\nx = factorial(5)")
verify_flow("PY-factorial-flow", r, ["function: factorial", "if", "for loop"])

# C factorial
r = c_p("""
int factorial(int n) {
    if (n <= 1) return 1;
    int result = 1;
    for (int i = 2; i <= n; i++) { result *= i; }
    return result;
}
int main() { int x = factorial(5); return 0; }
""")
verify_flow("C-factorial-flow", r, ["function: factorial", "if", "for loop"])

# C++ factorial
r = cpp_p("""
int factorial(int n) {
    if (n <= 1) return 1;
    int result = 1;
    for (int i = 2; i <= n; i++) { result *= i; }
    return result;
}
int main() { int x = factorial(5); return 0; }
""")
verify_flow("CPP-factorial-flow", r, ["function: factorial", "if", "for"])

# Java factorial
r = java_p("""
public class Main {
    public static int factorial(int n) {
        if (n <= 1) return 1;
        int result = 1;
        for (int i = 2; i <= n; i++) { result *= i; }
        return result;
    }
    public static void main(String[] args) {
        int x = factorial(5);
        System.out.println(x);
    }
}
""")
verify_flow("JAVA-factorial-flow", r, ["factorial", "if", "for loop"])

# JS factorial
r = js_p("""
function factorial(n) {
    if (n <= 1) return 1;
    let result = 1;
    for (let i = 2; i <= n; i++) { result *= i; }
    return result;
}
const x = factorial(5);
""")
verify_flow("JS-factorial-flow", r, ["function: factorial", "if", "for"])


print()
print("=" * 60)
print("GRAPH DUMP: Detailed node+edge inspection per language")
print("=" * 60)

# Dump a standard test case for each language
test_code = {
    "python": "x = 0\nfor i in range(10):\n    if i % 2 == 0:\n        x += i\nprint(x)",
    "c": 'int main(){int x=0;for(int i=0;i<10;i++){if(i%2==0){x+=i;}}printf("%d",x);return 0;}',
    "cpp": 'int main(){int x=0;for(int i=0;i<10;i++){if(i%2==0){x+=i;}}return 0;}',
    "java": 'public class M{public static void main(String[] a){int x=0;for(int i=0;i<10;i++){if(i%2==0){x+=i;}}System.out.println(x);}}',
    "javascript": 'function main(){let x=0;for(let i=0;i<10;i++){if(i%2===0){x+=i;}}console.log(x);}',
}
parsers_map = {"python": py_p, "c": c_p, "cpp": cpp_p, "java": java_p, "javascript": js_p}

for lang, code in test_code.items():
    r = parsers_map[lang](code)
    nodes = {n["id"]: n for n in r["nodes"]}
    print("\n--- %s ---" % lang.upper())
    print("  Nodes (%d):" % len(nodes))
    for n in r["nodes"]:
        meta = ""
        if n.get("loop_type"):
            meta = "  [LOOP: type=%s cond=%s inf=%s]" % (n["loop_type"], n.get("loop_condition", "?"), n.get("is_infinite"))
        print("    %s: %s%s" % (n["id"], n["label"][:50], meta))
    print("  Edges: %d normal, %d loop, %d conditional" % (
        len(r.get("edges", [])), len(r.get("loops", [])), len(r.get("conditionals", []))))
    for e in r.get("edges", []):
        print("    %s(%s) -> %s(%s)" % (e["from"], nodes[e["from"]]["label"][:20], e["to"], nodes[e["to"]]["label"][:20]))
    for e in r.get("loops", []):
        print("    LOOP: %s(%s) -> %s(%s)" % (e["from"], nodes[e["from"]]["label"][:20], e["to"], nodes[e["to"]]["label"][:20]))
    for e in r.get("conditionals", []):
        print("    COND: %s(%s) -> %s(%s)" % (e["from"], nodes[e["from"]]["label"][:20], e["to"], nodes[e["to"]]["label"][:20]))


print()
print()
print("=" * 60)
print("FINAL RESULTS")
print("=" * 60)
print("  Passed: %d" % passed)
print("  Errors: %d" % len(errors))
if errors:
    print("\nERRORS:")
    for e in errors:
        print("  X %s" % e)
else:
    print("\n  ALL TESTS PASSED!")

if __name__ == "__main__":
    sys.exit(1 if errors else 0)
