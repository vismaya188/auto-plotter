import json
import logging
from pydantic import BaseModel, Field
from backend.llm.gemini import LLMClient

logger = logging.getLogger(__name__)

class UngroundedInsightError(Exception):
    """Raised when an insight contains hallucinations or ungrounded data."""
    pass

class InsightResponse(BaseModel):
    fact: str = Field(description="What the data directly shows.")
    insight: str = Field(description="What can reasonably be interpreted from that data.")
    action: str = Field(description="A possible next step based on the observed pattern.")

def verify_grounding(generated_text: str, source_data: str) -> bool:
    """
    Uses an LLM as a judge to verify semantic entailment and prevent hallucinated numbers.
    """
    if not generated_text:
        return True
        
    client = LLMClient()
    prompt = f"""
    You are a fact-checker. 
    Source Data: {source_data}
    Claim: {generated_text}
    
    Does the claim contain ANY hallucinated numbers that contradict or cannot be logically derived from the Source Data?
    It is ACCEPTABLE for numbers to be formatted for readability (e.g. '1.5k' instead of 1500, or '12%' instead of 0.12) or to count the number of data points.
    Answer ONLY with 'YES' (if there are severe ungrounded hallucinations) or 'NO' (if the claim is factually grounded).
    """
    try:
        res = client.generate_response(prompt).strip().upper()
        if 'YES' in res:
            logger.warning(f"Ungrounded claim detected by LLM judge: {generated_text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to verify grounding: {e}")
        return False # Fail closed for safety

def generate_structured_insight(intent: str, data_summary: str) -> dict:
    client = LLMClient()
    
    prompt = f"""
    You are a precise data analyst. Based on the user's intent and the data provided, 
    generate a 3-part structured analysis.
    
    CRITICAL RULES:
    1. DO NOT invent, calculate, or hallucinate any numbers.
    2. ONLY use numbers that appear exactly in the Data Summary or can be safely logically deduced.
    
    User Intent: {intent}
    Data Summary: {data_summary}
    """
    
    try:
        response_text = client.generate_response(prompt, response_schema=InsightResponse)
        result = json.loads(response_text)
        
        combined_text = f"{result.get('fact', '')} {result.get('insight', '')}"
        if not verify_grounding(combined_text, data_summary):
            raise UngroundedInsightError("The insight contains ungrounded numeric values or illicit calculations.")
            
        return result
        
    except UngroundedInsightError as e:
        logger.error(str(e))
        return {
            "fact": "The data returned valid results, but the automated insight was flagged for containing ungrounded numbers.",
            "insight": "The LLM attempted to calculate or hallucinate data that wasn't strictly returned by DuckDB.",
            "action": "Review the raw data visually in the chart or table."
        }
    except Exception as e:
        logger.error(f"Insight Generation Error: {e}")
        return {
            "fact": "An error occurred.",
            "insight": "API failed.",
            "action": "Try again later."
        }
