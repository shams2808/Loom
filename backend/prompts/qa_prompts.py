from typing import List, Dict, Optional
from backend.retrieval.interface import ContextChunk

def build_qa_system_prompt() -> str:
    """
    Returns the system prompt instructing Gemini on response formatting,
    grounding, citation requirements, and JSON structure.
    """
    return (
        "You are Loom, an expert AI assistant that answers questions about codebases.\n\n"
        "Instructions:\n"
        "1. Answer the user's question using ONLY the provided code snippets (retrieved context).\n"
        "2. If the retrieved context does not contain enough information to answer confidently, say so rather than guessing. "
        "This is critical: do not hallucinate, make up details, or assume code that is not shown exists.\n"
        "3. For the files and functions you rely on, cite them in the 'sources' array of your response. "
        "Only cite files and line ranges that are present in the provided context and directly relevant to the answer.\n"
        "4. Your output MUST be valid JSON only, matching the schema below. "
        "Do not include any preamble, conversational filler, or markdown fences (like ```json). Just return the raw JSON object.\n"
        "5. NEVER start your answer with generic filler phrases like 'Based on the provided code snippets', "
        "'Based on the codebase', 'The codebase contains', or similar. "
        "Jump straight into the actual explanation.\n\n"
        "Response Schema:\n"
        "{\n"
        '  "answer": "A detailed, structured, clear explanation answering the question.",\n'
        '  "sources": [\n'
        '    {\n'
        '      "file": "path/to/file.ext",\n'
        '      "function_name": "optional_function_or_class_name",\n'
        '      "line_start": 12,\n'
        '      "line_end": 45\n'
        '    }\n'
        '  ]\n'
        "}\n"
    )

def build_qa_user_prompt(
    question: str,
    retrieved_context: List[ContextChunk],
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Formats the context chunks, conversation history, and user question into the user prompt string.
    """
    history_str = ""
    if conversation_history:
        history_str += "Conversation History:\n"
        for turn in conversation_history:
            role = turn.get("role", "user").capitalize()
            content = turn.get("content", "")
            history_str += f"- {role}: {content}\n"
        history_str += "\n"

    context_str = ""
    if not retrieved_context:
        context_str = "No relevant context was found in the codebase.\n"
    else:
        context_str += "Retrieved Code Context Chunks:\n\n"
        for idx, chunk in enumerate(retrieved_context):
            func_desc = f" (in function/class: {chunk.function_name})" if chunk.function_name else ""
            context_str += (
                f"--- Chunk {idx + 1} ---\n"
                f"File: {chunk.file}{func_desc}\n"
                f"Lines: {chunk.line_start}-{chunk.line_end}\n"
                f"Code:\n"
                f"```\n"
                f"{chunk.code}\n"
                f"```\n\n"
            )

    user_prompt = (
        f"{history_str}"
        f"{context_str}"
        f"User Question: {question}\n\n"
        "Provide your grounded JSON response now:"
    )
    return user_prompt
