from typing import List
from backend.retrieval.interface import ContextChunk

def build_file_review_system_prompt() -> str:
    return (
        "You are Loom, a senior code reviewer. Analyze the provided diff of a file and generate constructive, highly accurate comments.\n"
        "You may also have access to related reference chunks from the repository. Use them to ground your review.\n\n"
        "Instructions:\n"
        "1. Flag only genuine issues (bugs, duplicated logic, performance bottlenecks, security risks, broken patterns, or missing tests). Avoid generic style nitpicks.\n"
        "2. For each comment, identify the correct line number in the new version of the file (corresponding to lines starting with '+' or context lines ' ' in the diff patch).\n"
        "3. Assign a severity level: 'info', 'warning', or 'critical' only. Do not use any other values.\n"
        "4. Leverage the provided codebase context:\n"
        "   - If relation is 'similar': note 'similar logic exists in [File].'\n"
        "   - If relation is 'caller': note 'this change may affect callers in [File].'\n"
        "5. Output valid JSON matching the schema below. Do not include any preamble, conversational filler, or markdown code fences (like ```json). Just the raw JSON object.\n\n"
        "Response Schema:\n"
        "{\n"
        '  "comments": [\n'
        '    {\n'
        '      "line": 42,\n'
        '      "severity": "warning",\n'
        '      "text": "Detailed explanation of the issue."\n'
        '    }\n'
        '  ]\n'
        "}\n"
    )

def build_file_review_user_prompt(
    filename: str,
    patch: str,
    status: str,
    retrieved_context: List[ContextChunk]
) -> str:
    context_str = ""
    if not retrieved_context:
        context_str = "No relevant reference context was found in the codebase.\n"
    else:
        context_str += "Retrieved codebase reference context:\n\n"
        for idx, chunk in enumerate(retrieved_context):
            relation_desc = f" (Relationship: {chunk.relation})" if chunk.relation else ""
            context_str += (
                f"--- Reference {idx + 1}{relation_desc} ---\n"
                f"File: {chunk.file}\n"
                f"Code:\n"
                f"```\n"
                f"{chunk.code}\n"
                f"```\n\n"
            )

    user_prompt = (
        f"File being reviewed: {filename}\n"
        f"Change Status: {status}\n"
        f"Diff Patch:\n"
        f"```diff\n"
        f"{patch}\n"
        f"```\n\n"
        f"{context_str}"
        "Provide your per-file review comments JSON now:"
    )
    return user_prompt

def build_summary_system_prompt() -> str:
    return (
        "You are Loom, a senior code reviewer. Your task is to generate a final top-level PR review summary based on the PR description and a list of gathered code comments.\n\n"
        "Instructions:\n"
        "1. Write a detailed, cohesive summary. Do not output raw JSON. Output plain markdown content.\n"
        "2. Organize the summary strictly using the following nested markdown format:\n"
        "   * **Core Changes**:\n"
        "     1. [Point 1]\n"
        "     2. [Point 2]\n"
        "   * **Architectural Impact**:\n"
        "     1. [Point 1]\n"
        "   * **Testing & Verification**:\n"
        "     1. [Point 1]\n"
        "3. Make sure to indent the numbered items under each bullet header by exactly 2 spaces so they nest correctly.\n"
        "4. Be objective, brief, and highly informative.\n"
    )

def build_summary_user_prompt(
    pr_title: str,
    pr_description: str,
    comments_list: List[dict]
) -> str:
    comments_str = ""
    if not comments_list:
        comments_str = "No issues or comments were generated for this PR."
    else:
        for c in comments_list:
            comments_str += f"- File: {c.get('file')}, Line: {c.get('line')}, Severity: {c.get('severity')}\n  Comment: {c.get('text')}\n"

    user_prompt = (
        f"PR Title: {pr_title}\n"
        f"PR Description: {pr_description}\n\n"
        f"Inline Review Comments:\n"
        f"{comments_str}\n\n"
        "Generate the markdown review summary now:"
    )
    return user_prompt
