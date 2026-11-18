
"""Deterministic eligibility rule evaluator for SahayAI."""

from typing import Any, Dict, List, Optional


class EligibilityEngine:
    """Evaluates structured scheme rules against a user profile."""

    SUPPORTED_OPERATORS = {
        "==", "!=", "<", "<=", ">", ">=", "IN", "ANY_OF"
    }

    def evaluate(
        self,
        scheme: Dict[str, Any],
        profile: Dict[str, Any],
        application_type: Optional[str] = None,
    ) -> Dict[str, Any]:

        eligibility = scheme.get("eligibility", {})
        rules = eligibility.get("structured_rules", [])

        scheme_verification = scheme.get(
            "verification_status", "unknown"
        )

        if not rules:
            review_required = scheme_verification != "verified"

            return {
                "scheme_id": scheme.get("scheme_id"),
                "scheme_name": scheme.get("scheme_name"),
                "status": (
                    "REVIEW_REQUIRED" if review_required else "UNKNOWN"
                ),
                "rule_match_status": "UNKNOWN",
                "review_required": review_required,
                "unverified_rule_count": 0,
                "results": [],
                "missing_information": [],
                "scheme_verification_status": scheme_verification,
                "official_eligibility_confirmed": False,
            }

        application_type = (
            application_type or profile.get("application_type")
        )

        if application_type:
            application_type = application_type.upper()

        results = []
        missing_information = []

        for rule in rules:
            rule_type = (rule.get("rule_type") or "GENERAL").upper()

            if rule_type in {"FRESH", "RENEWAL"}:
                if application_type is None:
                    results.append(
                        self._unknown(
                            rule,
                            "Application type (FRESH or RENEWAL) is missing."
                        )
                    )
                    missing_information.append("application_type")
                    continue

                if rule_type != application_type:
                    continue

            criterion = rule.get("criterion")
            operator = rule.get("operator")
            required = rule.get("required_value")

            if operator not in self.SUPPORTED_OPERATORS:
                results.append(
                    self._unknown(
                        rule, f"Unsupported operator: {operator}"
                    )
                )
                continue

            actual = profile.get(criterion)

            if actual is None:
                results.append(
                    self._unknown(
                        rule,
                        f"Profile information '{criterion}' is missing."
                    )
                )
                missing_information.append(criterion)
                continue

            try:
                passed = self._compare(actual, operator, required)

                results.append({
                    "criterion": criterion,
                    "status": "PASS" if passed else "FAIL",
                    "actual_value": actual,
                    "required_value": required,
                    "operator": operator,
                    "explanation": rule.get("explanation", ""),
                    "source_reference": rule.get("source_reference"),
                    "reason": (
                        "Condition satisfied."
                        if passed
                        else "Condition not satisfied."
                    ),
                    "logical_group": rule.get(
                        "logical_group", "ALL_OF"
                    ),
                })

            except (TypeError, ValueError):
                results.append(
                    self._unknown(
                        rule,
                        "Profile value could not be compared safely."
                    )
                )
                missing_information.append(criterion)

        rule_match_status = self._calculate_status(results)

        unverified_rules = [
            rule for rule in rules
            if rule.get("verification_status") != "verified"
        ]

        review_required = (
            scheme_verification != "verified"
            or bool(unverified_rules)
        )

        status = (
            "REVIEW_REQUIRED"
            if review_required
            else rule_match_status
        )

        return {
            "scheme_id": scheme.get("scheme_id"),
            "scheme_name": scheme.get("scheme_name"),
            "status": status,
            "rule_match_status": rule_match_status,
            "review_required": review_required,
            "unverified_rule_count": len(unverified_rules),
            "results": results,
            "missing_information": sorted(
                set(missing_information)
            ),
            "scheme_verification_status": scheme_verification,
            "official_eligibility_confirmed": False,
        }

    @staticmethod
    def _compare(actual: Any, operator: str, required: Any) -> bool:

        if operator == "==":
            return actual == required
        if operator == "!=":
            return actual != required
        if operator == "<":
            return actual < required
        if operator == "<=":
            return actual <= required
        if operator == ">":
            return actual > required
        if operator == ">=":
            return actual >= required
        if operator == "IN":
            return actual in required
        if operator == "ANY_OF":
            if isinstance(actual, (list, tuple, set)):
                return bool(set(actual).intersection(required))
            if isinstance(required, (list, tuple, set)):
                return actual in required
            return False

        raise ValueError(f"Unsupported operator: {operator}")

    @staticmethod
    def _unknown(rule: Dict[str, Any], reason: str) -> Dict[str, Any]:

        return {
            "criterion": rule.get("criterion"),
            "status": "UNKNOWN",
            "required_value": rule.get("required_value"),
            "operator": rule.get("operator"),
            "explanation": rule.get("explanation", ""),
            "source_reference": rule.get("source_reference"),
            "reason": reason,
            "logical_group": rule.get("logical_group", "ALL_OF"),
        }

    @staticmethod
    def _calculate_status(results: List[Dict[str, Any]]) -> str:

        if not results:
            return "UNKNOWN"

        groups: Dict[str, List[str]] = {}

        for result in results:
            group = result.get("logical_group", "ALL_OF")
            groups.setdefault(group, []).append(result["status"])

        group_statuses = []

        for group, statuses in groups.items():

            if group == "ALL_OF":
                if "FAIL" in statuses:
                    group_statuses.append("FAIL")
                elif "UNKNOWN" in statuses:
                    group_statuses.append("UNKNOWN")
                else:
                    group_statuses.append("PASS")

            elif group == "ANY_OF":
                if "PASS" in statuses:
                    group_statuses.append("PASS")
                elif "UNKNOWN" in statuses:
                    group_statuses.append("UNKNOWN")
                else:
                    group_statuses.append("FAIL")

            elif group == "ONE_OF":
                if "UNKNOWN" in statuses:
                    group_statuses.append("UNKNOWN")
                elif statuses.count("PASS") == 1:
                    group_statuses.append("PASS")
                else:
                    group_statuses.append("FAIL")

            else:
                group_statuses.append("UNKNOWN")

        if "FAIL" in group_statuses:
            return "FAIL"
        if "UNKNOWN" in group_statuses:
            return "UNKNOWN"

        return "PASS"
