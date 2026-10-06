import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from backend.config import settings

# Hard caps to prevent unbounded resource consumption (CWE-400, CWE-770)
# Raised to 32k chars to support multi-table semantic maps (7+ Northwind tables)
# Raised to 4096 tokens to support complex CTEs and window function SQL output
MAX_INPUT_CHARS = 32000
MAX_OUTPUT_TOKENS = 4096

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMClient:
    """
    A simple abstraction around the new official google-genai SDK.
    """
    def __init__(self):
        # Validate that the API key exists before trying to configure the client
        if not settings.gemini_api_key:
            logger.error("GEMINI_API_KEY is missing from the environment.")
            raise ValueError("GEMINI_API_KEY is not set. Please check your .env file.")
        
        try:
            # Initialize the new SDK Client
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model_name = settings.gemini_model
        except Exception as e:
            logger.error(f"Failed to initialize the Gemini client: {e}")
            raise RuntimeError("Could not initialize LLM Client.") from e

    @retry(
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(8),
        retry=retry_if_exception_type(APIError),
        before_sleep=lambda retry_state: logger.warning(
            f"Google API rate limited (429) or overloaded (503). Retrying in {retry_state.next_action.sleep}s..."
        )
    )
    def generate_response(self, prompt: str, response_schema=None) -> str:
        """
        Sends a prompt to the Gemini model and returns the generated text.
        Automatically retries with exponential backoff if the API is overloaded.
        If response_schema is provided (a Pydantic model), it forces structured JSON output.
        """
        # Bound input size to prevent cost amplification
        if len(prompt) > MAX_INPUT_CHARS:
            logger.warning(f"Prompt truncated from {len(prompt)} to {MAX_INPUT_CHARS} chars.")
            prompt = prompt[:MAX_INPUT_CHARS]

        try:
            # Build config: always cap output tokens; optionally force JSON schema
            if response_schema:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                )
            else:
                config = types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            
            # Extract and return the text
            return response.text
            
        except APIError as e:
            # If it's a 503 or 429, tenacity will catch it and retry automatically.
            if e.code in [503, 429]:
                raise # Pass up to tenacity to retry
            logger.error(f"Gemini API Error: {e}")
            raise RuntimeError(f"The model API returned an error: {e}")
            
        except Exception as e:
            # Catch network errors, timeouts, or API outages
            logger.error(f"Gemini API Error: {str(e)}")
            raise RuntimeError(f"Failed to communicate with the LLM: {str(e)}")
