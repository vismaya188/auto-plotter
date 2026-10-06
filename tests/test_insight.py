import pytest
from backend.agent.insight import verify_grounding

def test_grounded_insight():
    """Test that an insight quoting exact numbers from the data passes."""
    data = '[{"region": "North", "revenue": 520}]'
    fact = "Region North generated 520 in revenue."
    assert verify_grounding(fact, data) is True

def test_grounded_insight_logical_calculation():
    """Test that valid logical derivations (like sums) are permitted."""
    data = '[{"region": "North", "revenue": 520}, {"region": "South", "revenue": 100}]'
    fact = "The total revenue across regions is 620."
    assert verify_grounding(fact, data) is True

def test_grounded_insight_percentage():
    """Test that valid percentage derivations are permitted."""
    data = '[{"region": "North", "revenue": 500}, {"region": "South", "revenue": 500}]'
    fact = "North accounts for 50 percent of the revenue."
    assert verify_grounding(fact, data) is True

def test_grounded_insight_with_commas():
    """Test that formatted numbers with commas pass grounding."""
    data = '[{"region": "North", "revenue": 520000}]'
    fact = "Region North generated 520,000 in revenue."
    assert verify_grounding(fact, data) is True

def test_ungrounded_hallucinated_revenue():
    """Test that completely fabricated numbers that contradict data are rejected."""
    data = '[{"region": "North", "revenue": 520}]'
    fact = "Region North generated 98,500,000 in revenue and 45,000 refunds."
    assert verify_grounding(fact, data) is False
