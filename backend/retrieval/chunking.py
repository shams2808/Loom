import ast
import re
import os
from typing import List, Dict, Any

def chunk_sliding_window(file_path: str, code: str, chunk_size: int = 50, overlap: int = 10) -> List[Dict[str, Any]]:
    """Splits a file into sliding windows of lines."""
    lines = code.splitlines()
    total_lines = len(lines)
    chunks = []

    if total_lines == 0:
        return [{
            "file": file_path,
            "function_name": None,
            "code": "",
            "line_start": 1,
            "line_end": 1
        }]

    if total_lines <= chunk_size:
        return [{
            "file": file_path,
            "function_name": None,
            "code": code,
            "line_start": 1,
            "line_end": total_lines
        }]

    i = 0
    while i < total_lines:
        end = min(i + chunk_size, total_lines)
        chunk_lines = lines[i:end]
        chunk_code = "\n".join(chunk_lines)
        chunks.append({
            "file": file_path,
            "function_name": None,
            "code": chunk_code,
            "line_start": i + 1,
            "line_end": end
        })
        if end == total_lines:
            break
        i += chunk_size - overlap

    return chunks

class PythonASTVisitor(ast.NodeVisitor):
    def __init__(self, code_lines: List[str], file_path: str):
        self.code_lines = code_lines
        self.file_path = file_path
        self.chunks = []
        self.scope_stack = []

    def _add_chunk(self, name: str, lineno: int, end_lineno: int):
        start_line = max(1, lineno)
        end_line = min(len(self.code_lines), end_lineno)
        chunk_code = "\n".join(self.code_lines[start_line - 1 : end_line])
        
        self.chunks.append({
            "file": self.file_path,
            "function_name": ".".join(self.scope_stack),
            "code": chunk_code,
            "line_start": start_line,
            "line_end": end_line
        })

    def visit_ClassDef(self, node: ast.ClassDef):
        self.scope_stack.append(node.name)
        end_line = getattr(node, "end_lineno", len(self.code_lines))
        self._add_chunk(node.name, node.lineno, end_line)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.scope_stack.append(node.name)
        end_line = getattr(node, "end_lineno", len(self.code_lines))
        self._add_chunk(node.name, node.lineno, end_line)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.scope_stack.append(node.name)
        end_line = getattr(node, "end_lineno", len(self.code_lines))
        self._add_chunk(node.name, node.lineno, end_line)
        self.generic_visit(node)
        self.scope_stack.pop()

def chunk_python(file_path: str, code: str) -> List[Dict[str, Any]]:
    """Chunks a Python file using AST parsing."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return chunk_sliding_window(file_path, code)

    visitor = PythonASTVisitor(code.splitlines(), file_path)
    visitor.visit(tree)

    if not visitor.chunks:
        return chunk_sliding_window(file_path, code)

    return visitor.chunks

def chunk_by_braces(file_path: str, code: str) -> List[Dict[str, Any]]:
    """Chunks curly-brace languages (JS, TS, Swift) using brace matching."""
    chunks = []
    lines = code.splitlines()
    length = len(code)

    if length == 0:
        return []

    char_to_line = []
    current_line = 1
    for char in code:
        char_to_line.append(current_line)
        if char == '\n':
            current_line += 1

    i = 0
    in_single_comment = False
    in_multi_comment = False
    in_string = None  # '"', "'", '`'

    brace_stack = []
    balance = 0
    last_boundary = 0

    while i < length:
        char = code[i]

        if in_string:
            if char == '\\' and i + 1 < length:
                i += 2
                continue
            elif char == in_string:
                in_string = None
            i += 1
            continue

        if in_single_comment:
            if char == '\n':
                in_single_comment = False
                last_boundary = i + 1
            i += 1
            continue

        if in_multi_comment:
            if char == '*' and i + 1 < length and code[i+1] == '/':
                in_multi_comment = False
                i += 2
                last_boundary = i
                continue
            i += 1
            continue

        if char == '/' and i + 1 < length:
            if code[i+1] == '/':
                in_single_comment = True
                i += 2
                continue
            elif code[i+1] == '*':
                in_multi_comment = True
                i += 2
                continue

        if char in ('"', "'", '`'):
            in_string = char
            i += 1
            continue

        if char == '{':
            signature = code[last_boundary:i].strip()
            signature_clean = " ".join(signature.split())

            start_line = char_to_line[i]
            sig_start_line = start_line

            if signature:
                sig_char = last_boundary
                while sig_char < i and code[sig_char].isspace():
                    sig_char += 1
                if sig_char < len(char_to_line):
                    sig_start_line = char_to_line[sig_char]

            brace_stack.append({
                "start_char": i,
                "sig_start_char": last_boundary,
                "sig_start_line": sig_start_line,
                "signature": signature_clean,
                "balance_before": balance
            })
            balance += 1
            last_boundary = i + 1

        elif char == '}':
            balance -= 1
            if brace_stack:
                block_info = brace_stack.pop()
                if balance == block_info["balance_before"]:
                    end_line = char_to_line[i]
                    start_char = block_info["start_char"]
                    sig_start_line = block_info["sig_start_line"]
                    sig = block_info["signature"]
                    sig_start_char = block_info["sig_start_char"]

                    actual_start = sig_start_char
                    while actual_start < i and code[actual_start].isspace():
                        actual_start += 1

                    patterns = [
                        (r'\b(function|class|struct|enum|interface|extension)\s+(\w+)', 2),
                        (r'\b(const|let|var)\s+(\w+)\s*=\s*(async\s*)?(\([^)]*\)|_|\w+)\s*=>', 2),
                        (r'\bfunc\s+(\w+)', 1),
                        (r'\b(\w+)\s*\([^)]*\)\s*(async|throws|private|public|protected|static|override)*\s*$', 1),
                    ]

                    func_name = None
                    is_interesting = False
                    for pat, group_idx in patterns:
                        m = re.search(pat, sig)
                        if m:
                            is_interesting = True
                            func_name = m.group(group_idx)
                            break

                    block_code = code[actual_start:i+1]
                    if is_interesting or len(block_code.splitlines()) >= 5:
                        chunks.append({
                            "file": file_path,
                            "function_name": func_name or "block",
                            "code": block_code,
                            "line_start": sig_start_line,
                            "line_end": end_line
                        })

            last_boundary = i + 1

        elif char in (';', '\n'):
            if balance == 0:
                last_boundary = i + 1

        i += 1

    return chunks

def chunk_file(file_path: str, content: str) -> List[Dict[str, Any]]:
    """Chunks a file based on its extension and splits any chunks that exceed a safe character limit."""
    _, ext = os.path.splitext(file_path.lower())
    
    if ext == '.py':
        chunks = chunk_python(file_path, content)
    elif ext in ('.js', '.jsx', '.ts', '.tsx', '.swift'):
        chunks = chunk_by_braces(file_path, content)
        if not chunks:
            chunks = chunk_sliding_window(file_path, content)
    else:
        chunks = chunk_sliding_window(file_path, content)

    final_chunks = []
    for chunk in chunks:
        code_len = len(chunk["code"])
        if code_len > 6000:
            sub_chunks = chunk_sliding_window(
                file_path=chunk["file"],
                code=chunk["code"],
                chunk_size=40,
                overlap=10
            )
            for sc in sub_chunks:
                sc["line_start"] = chunk["line_start"] + sc["line_start"] - 1
                sc["line_end"] = chunk["line_start"] + sc["line_end"] - 1
                sc["function_name"] = chunk["function_name"]
                final_chunks.append(sc)
        else:
            final_chunks.append(chunk)

    if not final_chunks:
        return chunk_sliding_window(file_path, content)
    return final_chunks
