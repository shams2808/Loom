import pytest
from backend.retrieval.chunking import chunk_file

def test_python_ast_chunker():
    code = """# comments
def add_numbers(x, y):
    # inside function
    return x + y

class MathService:
    def multiply(self, a, b):
        return a * b
"""
    chunks = chunk_file("math.py", code)
    assert len(chunks) >= 3
    
    add_chunk = next(c for c in chunks if c["function_name"] == "add_numbers")
    assert add_chunk["line_start"] == 2
    assert add_chunk["line_end"] == 4
    
    mult_chunk = next(c for c in chunks if c["function_name"] == "MathService.multiply")
    assert mult_chunk["line_start"] == 7
    assert mult_chunk["line_end"] == 8

def test_javascript_brace_chunker():
    code = """// js comment
function handleAuth(req) {
    const token = req.token;
    return token;
}

class SessionStore {
    clear() {
        this.sessions = {};
    }
}
"""
    chunks = chunk_file("auth.js", code)
    assert len(chunks) >= 2
    
    auth_chunk = next(c for c in chunks if c["function_name"] == "handleAuth")
    assert auth_chunk["line_start"] == 2
    assert auth_chunk["line_end"] == 5
    
    store_chunk = next(c for c in chunks if c["function_name"] == "SessionStore")
    assert store_chunk["line_start"] == 7
    assert store_chunk["line_end"] == 11

def test_sliding_window_fallback():
    # Regular text file which has no programming structure
    lines = [f"Text line {i}" for i in range(1, 101)]
    code = "\n".join(lines)
    chunks = chunk_file("doc.txt", code)
    assert len(chunks) > 1
    assert chunks[0]["line_start"] == 1
    assert chunks[0]["line_end"] == 50
