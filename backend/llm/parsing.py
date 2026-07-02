import json
import re
from typing import Type, Dict, Any
from pydantic import BaseModel, ValidationError

class LLMParsingError(Exception):
    """Raised when LLM output cannot be parsed or validated."""
    pass

def extract_json(raw_text: str) -> Dict[str, Any]:
    """
    Strips markdown code fences and extracts raw JSON.
    Attempts json.loads() and raises LLMParsingError on failure.
    """
    text = raw_text.strip()
    
    # Try to find JSON block inside markdown code fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        json_str = match.group(1).strip()
    else:
        json_str = text

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Fallback: search for first '{' and last '}'
        start_idx = json_str.find('{')
        end_idx = json_str.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(json_str[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                pass
        raise LLMParsingError(f"Failed to decode JSON from LLM response: {e}. Raw text: {raw_text}")

def validate_and_parse(raw_text: str, schema: Type[BaseModel]) -> BaseModel:
    """
    Extracts JSON from the raw text and validates it against the Pydantic schema.
    Raises LLMParsingError on failure.
    """
    parsed_dict = extract_json(raw_text)
    try:
        return schema.model_validate(parsed_dict)
    except ValidationError as e:
        raise LLMParsingError(f"Pydantic validation failed for schema {schema.__name__}: {e}. Dict: {parsed_dict}")
