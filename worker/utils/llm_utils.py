from typing import Any, List, Dict, Type, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

async def call_llm_structured(
    llm_client: Any,
    model: str,
    messages: List[Dict[str, str]],
    pydantic_model: Type[T],
    logger,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    retry: bool = True,
) -> Optional[T]:
    """
    Calls an LLM and returns a validated structured dictionary
    using a Pydantic model for schema validation.
    Automatically retries once if the first call fails.

    Parameters
    ----------
    llm_client : Any
        The LLM client instance (e.g., OpenAI, Qwen, Grok, etc.).
    model : str
        Model name (e.g., "gpt-4o-mini", "qwen-plus", "grok-4-non-reasoning").
    messages : List[Dict[str, str]]
        Chat messages in OpenAI format.
    pydantic_model : BaseModel subclass
        The Pydantic model used for structured validation of the LLM response.
    logger :
        Logger instance for diagnostics.
    max_tokens : int, optional
        Maximum tokens for the response. Default is 1024.
    temperature : float, optional
        Sampling temperature. Default is 0.0.
    retry : bool, optional
        Whether to retry once if the first attempt fails. Default is True.

    Returns
    -------
    dict | None
        A validated Python dictionary if successful, otherwise None.
    """

    async def _attempt_request() -> T:
        """Encapsulates a single attempt to call the LLM."""
        llm_response = await llm_client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=pydantic_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        parsed_model = llm_response.choices[0].message.parsed
        
        return parsed_model.model_dump()

    # --- First attempt ---
    try:
        return await _attempt_request()

    except Exception as e:
        logger.warning(f"LLM structured call failed on first attempt: {e}")

        # Retry once if enabled
        if retry:
            logger.info("Retrying structured LLM call once...")
            try:
                return await _attempt_request()
            except Exception as retry_error:
                logger.error(f"Second LLM attempt also failed: {retry_error}")
                return None

        # If retry disabled
        return None
