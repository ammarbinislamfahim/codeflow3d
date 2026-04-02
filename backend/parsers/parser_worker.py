# backend/parsers/parser_worker.py - SUBPROCESS WORKER

"""
Isolated parser worker - runs in subprocess.
Reads JSON from stdin, outputs JSON to stdout.
"""

import sys
import os
import json

# Ensure the parsers directory is on sys.path regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from c_parser import parse as parse_c
from cpp_parser import parse as parse_cpp
from python_parser import parse as parse_python
from java_parser import parse as parse_java
from js_parser import parse as parse_js


def main():
    """Main worker entry point"""
    try:
        input_data = json.loads(sys.stdin.read())
        language = input_data.get("language")
        code = input_data.get("code")

        if not language or not code:
            raise ValueError("Missing language or code")

        parsers = {
            "c": parse_c,
            "cpp": parse_cpp,
            "python": parse_python,
            "java": parse_java,
            "javascript": parse_js,
        }

        parser_func = parsers.get(language)
        if not parser_func:
            raise ValueError(f"Unsupported language: {language}")

        result = parser_func(code)

        result.setdefault("nodes", [])
        result.setdefault("edges", [])
        result.setdefault("loops", [])
        result.setdefault("conditionals", [])
        result.setdefault("error", None)

        print(json.dumps(result))
        sys.exit(0)

    except json.JSONDecodeError as e:
        error_result = {
            "nodes": [],
            "edges": [],
            "loops": [],
            "conditionals": [],
            "error": f"Invalid JSON input: {str(e)}"
        }
        print(json.dumps(error_result))
        sys.exit(1)

    except Exception as e:
        error_result = {
            "nodes": [],
            "edges": [],
            "loops": [],
            "conditionals": [],
            "error": f"Parser error: {str(e)}"
        }
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
