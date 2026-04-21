"""Tests for CategorizationAgent prompt with context."""

from budget_parser.categorizer.agent import CategorizationAgent


def test_prompt_includes_context_when_present():
    agent = CategorizationAgent(
        model="llama3",
        categories=[{"category": "Restaurants", "sub_category": "Family"}],
    )
    transactions = [
        {"index": 0, "description": "TST* THAI FUSION", "context": "Thai restaurant"},
        {"index": 1, "description": "NETFLIX"},
    ]
    prompt = agent._build_prompt(transactions)
    assert "(Context: Thai restaurant)" in prompt
    assert "NETFLIX" in prompt
    # Verify NETFLIX line doesn't have a context annotation
    netflix_line = [l for l in prompt.split("\n") if "NETFLIX" in l][0]
    assert "(Context:" not in netflix_line


def test_prompt_works_without_context():
    agent = CategorizationAgent(
        model="llama3",
        categories=[{"category": "Utilities", "sub_category": "Streaming"}],
    )
    transactions = [
        {"index": 0, "description": "NETFLIX"},
    ]
    prompt = agent._build_prompt(transactions)
    assert "0: NETFLIX" in prompt
    assert "Context" not in prompt
