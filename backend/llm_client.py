# backend/llm_client.py
import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

class LLMClient:
    """
    Thin, stateless wrapper around the OpenAI API.
    Kernel is responsible for prompts and context.
    """
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment or .env")

        self.client = OpenAI(api_key=api_key)

    def chat(self, system_prompt: str, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Execute a chat completion and return assistant text.
        """
        model = kwargs.pop("model", "gpt-5.1")  # or your preferred model
        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            **kwargs,
        )
        return resp.choices[0].message.content

    # 🔹 New method used by NovaKernel._handle_natural_language
    def complete(
        self,
        system: str,
        user: str,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        High-level helper used by NovaKernel.
        Wraps `chat()` and returns a dict with a `text` field.
        """
        messages = [
            {"role": "user", "content": user}
        ]

        text = self.chat(system_prompt=system, messages=messages, **kwargs)

        return {
            "text": text,
            "session_id": session_id,
        }
