/* Monaco Editor Setup - PRODUCTION READY */

let editor = null;
let editorReady = false;
let fallbackTextarea = null;

/**
 * Create a plain textarea fallback when Monaco fails to load
 */
function createFallbackEditor() {
    const container = document.getElementById("editor");
    if (!container || fallbackTextarea) return;
    console.warn("⚠️ Using fallback textarea editor");
    container.innerHTML = "";
    fallbackTextarea = document.createElement("textarea");
    fallbackTextarea.id = "fallback-editor";
    fallbackTextarea.spellcheck = false;
    fallbackTextarea.value = getDefaultCode("c");
    fallbackTextarea.style.cssText =
        "width:100%;height:100%;background:#1e1e1e;color:#d4d4d4;" +
        "font-family:'IBM Plex Mono',monospace;font-size:14px;padding:12px;" +
        "border:none;outline:none;resize:none;tab-size:4;white-space:pre;" +
        "overflow:auto;border-radius:8px;";
    container.appendChild(fallbackTextarea);
    editorReady = true;
}

/**
 * Initialize Monaco Editor with retry + fallback
 */
function initEditor(attempt) {
    attempt = attempt || 1;
    const maxAttempts = 3;

    if (typeof window.require === "undefined" || typeof window.require.config !== "function") {
        if (attempt < maxAttempts) {
            console.log("⏳ Monaco loader not ready, retrying (" + attempt + "/" + maxAttempts + ")...");
            setTimeout(function () { initEditor(attempt + 1); }, 1000);
        } else {
            console.error("❌ Monaco loader unavailable after " + maxAttempts + " attempts");
            createFallbackEditor();
        }
        return;
    }

    console.log("📝 Initializing Monaco Editor...");

    try {
        window.require.config({
            paths: {
                vs: "https://unpkg.com/monaco-editor@0.52.0/min/vs"
            }
        });

        window.require(["vs/editor/editor.main"], function () {
            try {
                var container = document.getElementById("editor");
                container.innerHTML = "";
                editor = window.monaco.editor.create(container, {
                    value: getDefaultCode("c"),
                    language: "c",
                    theme: "vs-dark",
                    automaticLayout: true,
                    fontSize: 14,
                    minimap: { enabled: window.innerWidth > 700 },
                    scrollBeyondLastLine: false,
                    lineNumbers: "on",
                    wordWrap: "on",
                    tabSize: 4,
                    insertSpaces: true,
                });

                editorReady = true;
                console.log("✓ Monaco Editor initialized");
            } catch (error) {
                console.error("❌ Monaco Editor create failed:", error);
                createFallbackEditor();
            }
        }, function (err) {
            console.error("❌ Monaco module load failed:", err);
            createFallbackEditor();
        });
    } catch (error) {
        console.error("❌ Monaco require.config failed:", error);
        createFallbackEditor();
    }
}

/**
 * Default boilerplate per language
 */
function getDefaultCode(lang) {
    const templates = {
        c: `#include <stdio.h>

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}

int main() {
    int nums[] = {3, 7, -1, 12, 0};
    int sum = 0;

    for (int i = 0; i < 5; i++) {
        if (nums[i] < 0) {
            printf("Skipping negative\\n");
            continue;
        } else if (nums[i] == 0) {
            printf("Done\\n");
            break;
        } else {
            sum += factorial(nums[i]);
        }
    }

    if (sum > 100) {
        printf("Large sum: %d\\n", sum);
    } else {
        printf("Small sum: %d\\n", sum);
    }
    return 0;
}`,
        cpp: `#include <iostream>
#include <vector>
using namespace std;

int fibonacci(int n) {
    if (n <= 1) return n;
    return fibonacci(n - 1) + fibonacci(n - 2);
}

int main() {
    vector<int> results;
    for (int i = 1; i <= 8; i++) {
        int fib = fibonacci(i);
        if (fib % 2 == 0) {
            cout << fib << " is even" << endl;
            results.push_back(fib);
        } else {
            cout << fib << " is odd" << endl;
        }
    }

    if (results.empty()) {
        cout << "No even numbers" << endl;
    } else {
        cout << "Found " << results.size() << " even" << endl;
    }
    return 0;
}`,
        python: `def fizzbuzz(n):
    results = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            results.append("FizzBuzz")
        elif i % 3 == 0:
            results.append("Fizz")
        elif i % 5 == 0:
            results.append("Buzz")
        else:
            results.append(str(i))
    return results

def main():
    output = fizzbuzz(20)
    for item in output:
        if item.isdigit():
            print("Number: " + item)
        else:
            print("Word: " + item)

main()`,
        java: `public class Main {
    static int gcd(int a, int b) {
        while (b != 0) {
            int temp = b;
            b = a % b;
            a = temp;
        }
        return a;
    }

    public static void main(String[] args) {
        int[] pairs = {48, 18, 56, 98, 15, 25};
        for (int i = 0; i < pairs.length - 1; i += 2) {
            int result = gcd(pairs[i], pairs[i + 1]);
            if (result == 1) {
                System.out.println("Coprime pair");
            } else if (result > 10) {
                System.out.println("Large GCD: " + result);
            } else {
                System.out.println("GCD: " + result);
            }
        }
    }
}`,
        javascript: `function fibonacci(n) {
    if (n <= 1) return n;
    return fibonacci(n - 1) + fibonacci(n - 2);
}

function classify(arr) {
    for (let i = 0; i < arr.length; i++) {
        let fib = fibonacci(arr[i]);
        if (fib > 100) {
            console.log(fib + " is large");
        } else if (fib % 2 === 0) {
            console.log(fib + " is even");
        } else {
            console.log(fib + " is odd");
        }
    }
}

classify([5, 8, 3, 12]);`,
        typescript: `interface Task {
    name: string;
    priority: number;
    done: boolean;
}

function processTasks(tasks: Task[]): void {
    let completed: number = 0;
    let pending: number = 0;

    for (let i = 0; i < tasks.length; i++) {
        if (tasks[i].done) {
            completed++;
        } else if (tasks[i].priority > 5) {
            console.log(tasks[i].name + " is urgent");
            pending++;
        } else {
            console.log(tasks[i].name + " can wait");
            pending++;
        }
    }

    if (completed > pending) {
        console.log("Mostly done: " + completed);
    } else {
        console.log("Still working: " + pending);
    }
}

const myTasks: Task[] = [
    { name: "Deploy", priority: 9, done: false },
    { name: "Test", priority: 7, done: true },
    { name: "Docs", priority: 3, done: false }
];

processTasks(myTasks);`,
    };

    return templates[lang] || templates.c;
}

/**
 * Get current editor code (SAFE)
 */
export function getEditorCode() {
    if (fallbackTextarea) return fallbackTextarea.value;
    if (!editor) {
        console.warn("⚠️ Editor not ready yet");
        return "";
    }
    return editor.getValue();
}

/**
 * Change editor language dynamically
 */
export function setLanguage(lang) {
    if (!editor) {
        console.warn("⚠️ Editor not initialized");
        return;
    }

    const langMap = {
        c: "c",
        cpp: "cpp",
        python: "python",
        java: "java",
        javascript: "javascript",
        typescript: "typescript",
    };

    const monacoLang = langMap[lang] || "javascript";

    if (fallbackTextarea) {
        fallbackTextarea.value = getDefaultCode(lang);
        console.log(`✓ Language changed to: ${lang}`);
        return;
    }

    try {
        window.monaco.editor.setModelLanguage(editor.getModel(), monacoLang);
        editor.setValue(getDefaultCode(lang));
        console.log(`✓ Language changed to: ${lang}`);
    } catch (error) {
        console.error("❌ Language change failed:", error);
    }
}

/**
 * Check if editor is ready
 */
export function isEditorReady() {
    return editorReady && (!!editor || !!fallbackTextarea);
}

/**
 * Set editor content programmatically
 */
export function setEditorCode(code) {
    if (fallbackTextarea) { fallbackTextarea.value = code; return; }
    if (!editor) return;
    editor.setValue(code);
}

/**
 * Reveal and highlight a source line in the editor (1-based line number).
 */
export function revealLine(lineNumber) {
    if ((!editor && !fallbackTextarea) || !lineNumber) return;
    if (fallbackTextarea) return;
    editor.revealLineInCenter(lineNumber);
    editor.setPosition({ lineNumber, column: 1 });
    editor.focus();
}

let _errorDecorations = [];

/**
 * Highlight an error line with a red background decoration.
 */
export function setErrorDecoration(lineNumber, message) {
    if (!editor || !lineNumber) return;
    _errorDecorations = editor.deltaDecorations(_errorDecorations, [{
        range: new window.monaco.Range(lineNumber, 1, lineNumber, 1),
        options: {
            isWholeLine: true,
            className: 'error-line-highlight',
            hoverMessage: { value: message || 'Syntax error' },
        }
    }]);
    editor.revealLineInCenter(lineNumber);
}

/**
 * Clear any existing error line decorations.
 */
export function clearErrorDecoration() {
    if (!editor) return;
    _errorDecorations = editor.deltaDecorations(_errorDecorations, []);
}

/**
 * Initialize on load
 */
document.addEventListener("DOMContentLoaded", initEditor);