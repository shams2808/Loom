import pytest
from pydantic import BaseModel, Field
from backend.llm.parsing import extract_json, validate_and_parse, LLMParsingError

class UserSchema(BaseModel):
    username: str
    github_id: int
    roles: list[str] = Field(default_factory=list)

def test_extract_json_clean():
    raw = '{"username": "testuser", "github_id": 123, "roles": ["user"]}'
    res = extract_json(raw)
    assert res == {"username": "testuser", "github_id": 123, "roles": ["user"]}

def test_extract_json_markdown():
    raw = """
Text before JSON block
```json
{
  "username": "shams",
  "github_id": 456
}
```
Text after JSON block
"""
    res = extract_json(raw)
    assert res == {"username": "shams", "github_id": 456}

def test_extract_json_malformed():
    raw = '{"username": "testuser", "github_id": 123,'
    with pytest.raises(LLMParsingError):
        extract_json(raw)

def test_validate_and_parse_success():
    raw = '{"username": "charlie", "github_id": 789}'
    obj = validate_and_parse(raw, UserSchema)
    assert isinstance(obj, UserSchema)
    assert obj.username == "charlie"
    assert obj.github_id == 789
    assert obj.roles == []

def test_validate_and_parse_error():
    # Missing required field 'github_id'
    raw = '{"username": "charlie"}'
    with pytest.raises(LLMParsingError):
        validate_and_parse(raw, UserSchema)
