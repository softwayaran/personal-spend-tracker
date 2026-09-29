"""Two-step laya-based transaction categorizer."""

from collections import defaultdict
from typing import Any, Dict, List

from laya import Router

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class LayaCategorizer:
    """Categorizes transactions using laya's choice primitive in two steps."""

    def __init__(
        self,
        categories: List[Dict[str, str]],
        model: str = "convaiinnovations/laya",
        confidence_threshold: float = 0.6,
    ):
        self._model = model
        self._threshold = confidence_threshold
        self._router = Router(preload=True)

        self._category_criteria, self._sub_criteria = self._build_criteria(categories)

    @staticmethod
    def _build_criteria(
        categories: List[Dict[str, str]],
    ) -> tuple:
        """Build laya criteria dicts from DB categories.

        Returns:
            (category_criteria, sub_criteria) where:
            - category_criteria: {"Grocery": "grocery stores, ...", ...}
            - sub_criteria: {"Grocery": {"Grocery": "general grocery", "Indian": "..."}, ...}
        """
        cat_descriptions: Dict[str, List[str]] = defaultdict(list)
        sub_criteria: Dict[str, Dict[str, str]] = defaultdict(dict)

        for row in categories:
            cat = row["category"]
            sub = row["sub_category"]
            desc = row.get("description", "").strip() or sub.lower()
            cat_descriptions[cat].append(desc)
            sub_criteria[cat][sub] = desc

        category_criteria = {
            cat: ", ".join(descs) for cat, descs in cat_descriptions.items()
        }
        return category_criteria, dict(sub_criteria)

    def _classify_one(self, description: str) -> Dict[str, Any]:
        """Run two-step classification on a single transaction description.

        Returns:
            {"category": str, "sub_category": str, "confidence": float}
            or {"category": "", "sub_category": "", "confidence": 0.0} on error.
        """
        empty = {"category": "", "sub_category": "", "confidence": 0.0}

        try:
            # Step 1: pick category
            step1 = self._router.predict(
                description,
                {
                    "category": {
                        "type": "choice",
                        "instructions": "What spending category does this transaction belong to?",
                        "criteria": self._category_criteria,
                    }
                },
            )
            cat_answer = step1["answers"]["category"]
            chosen_cat = cat_answer["choice"]
            cat_conf = cat_answer["confidence"]

            sub_options = self._sub_criteria.get(chosen_cat)
            if not sub_options:
                return empty

            # Step 2: pick sub_category
            step2 = self._router.predict(
                description,
                {
                    "sub_category": {
                        "type": "choice",
                        "instructions": f"What type of {chosen_cat.lower()} expense is this?",
                        "criteria": sub_options,
                    }
                },
            )
            sub_answer = step2["answers"]["sub_category"]
            chosen_sub = sub_answer["choice"]
            sub_conf = sub_answer["confidence"]

            return {
                "category": chosen_cat,
                "sub_category": chosen_sub,
                "confidence": min(cat_conf, sub_conf),
            }

        except Exception as e:
            logger.warning(f"Laya classification failed for '{description[:50]}': {e}")
            return empty

    def categorize(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Categorize transactions using laya two-step classification.

        Skips already-categorized rows. For accepted results (confidence >= threshold),
        sets category, sub_category, confidence, and categorized_by. For low-confidence
        results, leaves category empty and stashes the best guess in _laya_best_guess.

        Args:
            transactions: List of transaction dicts with at least 'description'

        Returns:
            Same list with laya results applied where confident
        """
        results = [dict(tx) for tx in transactions]

        pending = [
            (i, tx)
            for i, tx in enumerate(results)
            if not tx.get("category", "").strip()
        ]

        if not pending:
            logger.info("Laya: all transactions already categorized.")
            return results

        logger.info(f"Laya: classifying {len(pending)} transaction(s)...")
        accepted = 0

        for i, tx in pending:
            classification = self._classify_one(tx["description"])
            conf = classification["confidence"]

            if conf >= self._threshold:
                results[i]["category"] = classification["category"]
                results[i]["sub_category"] = classification["sub_category"]
                results[i]["confidence"] = conf
                results[i]["categorized_by"] = "laya"
                accepted += 1
            elif classification["category"]:
                results[i]["_laya_best_guess"] = {
                    "category": classification["category"],
                    "sub_category": classification["sub_category"],
                    "confidence": conf,
                }

        logger.info(
            f"Laya: {accepted}/{len(pending)} accepted "
            f"(threshold={self._threshold}), "
            f"{len(pending) - accepted} routed to fallback"
        )
        return results
