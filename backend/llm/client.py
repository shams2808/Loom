import asyncio
import logging
from google import genai
from google.genai import types

logger = logging.getLogger("loom.llm.client")

class LLMClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = model
        # Initialize the new google-genai Client
        self.client = genai.Client(api_key=self.api_key)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        response_mime_type: str = "application/json"
    ) -> str:
        """
        Sends system and user prompts to Gemini 2.5 Flash and returns raw text response.
        Implements 2 retries with exponential backoff for transient errors.
        """
        # Set temperature to 0.3 as required by PRD Section 8.1
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type=response_mime_type
        )

        retries = 2
        backoff_sec = 2.0

        for attempt in range(retries + 1):
            try:
                # Use client.aio for async execution in google-genai SDK
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=user_prompt,
                    config=config
                )
                if not response.text:
                    raise ValueError("Gemini returned an empty response text.")
                return response.text
            except Exception as e:
                if attempt == retries:
                    logger.error(f"Gemini API call failed after {retries} retries: {e}")
                    raise e
                
                wait_time = backoff_sec ** (attempt + 1)
                logger.warning(f"Gemini API call failed (attempt {attempt + 1}/{retries + 1}): {e}. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)

        raise RuntimeError("LLM complete failed unexpectedly.")
