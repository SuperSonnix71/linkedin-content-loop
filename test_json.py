#!/usr/bin/env python3
"""Test that the model outputs valid JSON."""
import os, json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url=os.getenv("AI_BASE_URL"),
    api_key=os.getenv("AI_API_KEY"),
)

prompt = """You MUST output ONLY a valid JSON object. No markdown, no text before or after.

Example output:
{"test": "hello world"}

Now output the same but with "hello" changed to "works":"""

response = client.chat.completions.create(
    model=os.getenv("AI_MODEL", "qwen3.6:35b"),
    messages=[{"role": "user", "content": prompt}],
    temperature=0.85,
    max_tokens=500,
)

raw = response.choices[0].message.content
print(f"RAW ({len(raw)} chars): {repr(raw)}")

# Try to parse
import re
raw_clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
try:
    data = json.loads(raw_clean)
    print(f"PARSED: {data}")
except json.JSONDecodeError as e:
    print(f"FAILED: {e}")
    # Try regex extraction
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            print(f"REGEX PARSED: {data}")
        except json.JSONDecodeError as e2:
            print(f"REGEX FAILED: {e2}")
