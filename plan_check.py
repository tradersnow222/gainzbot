#!/usr/bin/env python3
"""
Plan validation script for Gainzbot.

Validates proposed nutrition and training plans against hard safety bounds.
Rejects invalid plans with specific reasons; never silently clamps values.
Uses shared input validation with fail-closed behavior.
"""

from dataclasses import dataclass
from typing import Dict, List
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError


@dataclass
class ValidationResult:
    """Result of plan validation."""
    valid: bool
    errors: List[str]

    def to_dict(self) -> Dict:
        return {"valid": self.valid, "errors": self.errors}


class PlanValidator:
    """Validates fitness and nutrition plans against safety guardrails."""

    CALORIE_FLOOR_MEN = 1500
    CALORIE_FLOOR_WOMEN = 1200
    MAX_WEIGHT_LOSS_PERCENT = 1.0
    MIN_PROTEIN_G_PER_KG = 1.6
    MAX_PROTEIN_G_PER_KG = 2.2
    MAX_CALORIE_CHANGE_PER_WEEK = 200
    MAX_TRAINING_LOAD_INCREASE_PERCENT = 10.0
    MIN_WEEKS_BETWEEN_DELOADS = 4
    MAX_WEEKS_BETWEEN_DELOADS = 6
    MAX_WEEKLY_TRAINING_HOURS = 20

    @staticmethod
    def estimate_bmr(weight_kg: float, sex: str, age: int, height_cm: float) -> float:
        """
        Estimate Basal Metabolic Rate using Mifflin-St Jeor equation.
        
        Args:
            weight_kg: Body weight in kg
            sex: 'M' or 'F'
            age: Age in years
            height_cm: Height in cm
            
        Returns:
            Estimated BMR in kcal/day
        """
        if sex.upper() == 'M':
            return (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
        else:
            return (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161

    def _validate_calories(
        self,
        proposed_calories: float,
        sex: str,
        weight_kg: float,
        age: int,
        height_cm: float,
        has_medical_clearance: bool = False
    ) -> ValidationResult:
        """Validate proposed calorie target (internal)."""
        errors = []
        
        try:
            sex = InputValidator.parse_sex(sex, "sex").value
            proposed_calories = InputValidator.parse_number(proposed_calories, "proposed_calories")
            weight_kg = InputValidator.parse_number(weight_kg, "weight_kg")
            age = int(InputValidator.parse_number(age, "age"))
            height_cm = InputValidator.parse_number(height_cm, "height_cm")
            if not isinstance(has_medical_clearance, bool):
                has_medical_clearance = InputValidator.parse_boolean(
                    has_medical_clearance, "medical_clearance"
                )
        except ValidationError as e:
            return ValidationResult(valid=False, errors=[str(e)])
        
        floor = self.CALORIE_FLOOR_MEN if sex == 'M' else self.CALORIE_FLOOR_WOMEN
        
        if proposed_calories < floor:
            errors.append(
                f"Calorie target {proposed_calories:.0f} kcal is below the floor of "
                f"{floor} kcal for {sex.upper()}."
            )
        
        bmr = self.estimate_bmr(weight_kg, sex, age, height_cm)
        if proposed_calories < bmr and not has_medical_clearance:
            errors.append(
                f"Calorie target {proposed_calories:.0f} kcal is below estimated BMR "
                f"({bmr:.0f} kcal). Medical clearance required."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_calories(
        self,
        proposed_calories: float,
        sex: str,
        weight_kg: float,
        age: int,
        height_cm: float,
        has_medical_clearance: bool = False
    ) -> ValidationResult:
        """Validate proposed calorie target (public for backward compatibility)."""
        return self._validate_calories(
            proposed_calories, sex, weight_kg, age, height_cm, has_medical_clearance
        )

    def _validate_weight_loss_rate(
        self,
        target_loss_kg_per_week: float,
        current_weight_kg: float
    ) -> ValidationResult:
        """Validate weight loss rate (internal)."""
        errors = []
        
        try:
            target_loss_kg_per_week = InputValidator.parse_number(
                target_loss_kg_per_week,
                "target_loss_kg_per_week",
                allow_zero=True,
                allow_negative=True,
            )
            current_weight_kg = InputValidator.parse_number(current_weight_kg, "current_weight_kg")
        except ValidationError as e:
            return ValidationResult(valid=False, errors=[str(e)])

        if target_loss_kg_per_week <= 0:
            return ValidationResult(valid=True, errors=[])
        
        max_loss = current_weight_kg * (self.MAX_WEIGHT_LOSS_PERCENT / 100)
        
        if target_loss_kg_per_week > max_loss:
            errors.append(
                f"Target weight loss {target_loss_kg_per_week:.2f} kg/week exceeds "
                f"maximum safe rate of {max_loss:.2f} kg/week "
                f"(1% of body weight {current_weight_kg:.1f} kg)."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_weight_loss_rate(
        self,
        target_loss_kg_per_week: float,
        current_weight_kg: float
    ) -> ValidationResult:
        """Validate weight loss rate (public for backward compatibility)."""
        return self._validate_weight_loss_rate(target_loss_kg_per_week, current_weight_kg)

    def _validate_protein(
        self,
        protein_g: float,
        weight_kg: float
    ) -> ValidationResult:
        """Validate protein intake (internal)."""
        errors = []
        
        try:
            protein_g = InputValidator.parse_number(protein_g, "protein_g")
            weight_kg = InputValidator.parse_number(weight_kg, "weight_kg")
        except ValidationError as e:
            return ValidationResult(valid=False, errors=[str(e)])
        
        g_per_kg = protein_g / weight_kg
        
        if g_per_kg < self.MIN_PROTEIN_G_PER_KG:
            errors.append(
                f"Protein intake {protein_g:.0f}g ({g_per_kg:.2f} g/kg) is below "
                f"minimum {self.MIN_PROTEIN_G_PER_KG} g/kg."
            )
        
        if g_per_kg > self.MAX_PROTEIN_G_PER_KG:
            errors.append(
                f"Protein intake {protein_g:.0f}g ({g_per_kg:.2f} g/kg) exceeds "
                f"maximum {self.MAX_PROTEIN_G_PER_KG} g/kg."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_protein(
        self,
        protein_g: float,
        weight_kg: float
    ) -> ValidationResult:
        """Validate protein intake (public for backward compatibility)."""
        return self._validate_protein(protein_g, weight_kg)

    def _validate_calorie_change(
        self,
        current_calories: float,
        proposed_calories: float
    ) -> ValidationResult:
        """Validate weekly calorie change (internal)."""
        errors = []
        
        try:
            current_calories = InputValidator.parse_number(current_calories, "current_calories")
            proposed_calories = InputValidator.parse_number(proposed_calories, "proposed_calories")
        except ValidationError as e:
            return ValidationResult(valid=False, errors=[str(e)])
        
        change = abs(proposed_calories - current_calories)
        
        if change > self.MAX_CALORIE_CHANGE_PER_WEEK:
            errors.append(
                f"Calorie change {change:.0f} kcal exceeds maximum weekly change "
                f"of {self.MAX_CALORIE_CHANGE_PER_WEEK} kcal."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_calorie_change(
        self,
        current_calories: float,
        proposed_calories: float
    ) -> ValidationResult:
        """Validate weekly calorie change (public for backward compatibility)."""
        return self._validate_calorie_change(current_calories, proposed_calories)

    def validate_training_load_increase(
        self,
        current_load: float,
        proposed_load: float
    ) -> ValidationResult:
        """Validate training load increase."""
        errors = []
        
        if current_load == 0:
            return ValidationResult(valid=True, errors=[])
        
        increase_percent = ((proposed_load - current_load) / current_load) * 100
        
        if increase_percent > self.MAX_TRAINING_LOAD_INCREASE_PERCENT:
            errors.append(
                f"Training load increase {increase_percent:.1f}% exceeds maximum "
                f"safe increase of {self.MAX_TRAINING_LOAD_INCREASE_PERCENT}% per week."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_deload_schedule(
        self,
        weeks_since_last_deload: int
    ) -> ValidationResult:
        """Validate deload scheduling (public for backward compatibility)."""
        errors = []
        
        if weeks_since_last_deload > self.MAX_WEEKS_BETWEEN_DELOADS:
            errors.append(
                f"Deload required: {weeks_since_last_deload} weeks since last deload "
                f"(maximum {self.MAX_WEEKS_BETWEEN_DELOADS} weeks)."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_weekly_training_hours(
        self,
        structured_training_hours: float,
        sport_practice_hours: float
    ) -> ValidationResult:
        """Validate total weekly training hours (public for backward compatibility)."""
        errors = []
        
        total_hours = structured_training_hours + sport_practice_hours
        
        if total_hours > self.MAX_WEEKLY_TRAINING_HOURS:
            errors.append(
                f"Total weekly training hours {total_hours:.1f} "
                f"(structured: {structured_training_hours:.1f}, "
                f"sport: {sport_practice_hours:.1f}) exceeds maximum "
                f"{self.MAX_WEEKLY_TRAINING_HOURS} hours."
            )
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _check_unknown_keys(self, plan: Dict) -> List[str]:
        """Check for unknown keys in the plan."""
        errors = []
        
        known_top_level = {"user", "nutrition", "goals", "training"}
        known_user = {"sex", "weight_kg", "age", "height_cm", "medical_clearance"}
        known_nutrition = {"calories", "protein_g", "previous_calories"}
        known_goals = {"weight_loss_kg_per_week"}
        known_training = {"previous_load", "current_load", "weeks_since_deload", "structured_hours", "sport_hours"}
        
        for key in plan.keys():
            if key not in known_top_level:
                errors.append(f"Unknown top-level key: '{key}'")
        
        if "user" in plan:
            for key in plan["user"].keys():
                if key not in known_user:
                    errors.append(f"Unknown user key: '{key}'")
        
        if "nutrition" in plan:
            for key in plan["nutrition"].keys():
                if key not in known_nutrition:
                    errors.append(f"Unknown nutrition key: '{key}' (did you mean 'calories'?)")
        
        if "goals" in plan:
            for key in plan["goals"].keys():
                if key not in known_goals:
                    errors.append(f"Unknown goals key: '{key}'")
        
        if "training" in plan:
            for key in plan["training"].keys():
                if key not in known_training:
                    errors.append(f"Unknown training key: '{key}' (did you mean 'sport_hours'?)")
        
        return errors

    def validate_plan(self, plan: Dict) -> ValidationResult:
        """
        Validate a complete plan against all guardrails.
        
        Args:
            plan: Dictionary containing plan parameters
            
        Returns:
            ValidationResult with overall validity and all errors
        """
        all_errors = []

        if not isinstance(plan, dict):
            return ValidationResult(valid=False, errors=["Plan must be an object."])
        
        try:
            InputValidator.validate_plan_not_empty(plan)
        except ValidationError as e:
            return ValidationResult(valid=False, errors=[str(e)])

        for section in ("user", "nutrition", "goals", "training"):
            if section in plan and not isinstance(plan[section], dict):
                return ValidationResult(
                    valid=False,
                    errors=[f"Section '{section}' must be an object."],
                )
        
        unknown_key_errors = self._check_unknown_keys(plan)
        if unknown_key_errors:
            all_errors.extend(unknown_key_errors)
            return ValidationResult(valid=False, errors=all_errors)
        
        user_validated = None
        if "user" in plan:
            try:
                user_validated = InputValidator.validate_user_fields(plan["user"])
            except ValidationError as e:
                all_errors.append(f"User validation failed: {e}")
                return ValidationResult(valid=False, errors=all_errors)

            height_cm = user_validated["height_cm"]
            if height_cm < 50 or height_cm > 280:
                all_errors.append(
                    f"height_cm value {height_cm} is not a plausible height in centimeters."
                )
                return ValidationResult(valid=False, errors=all_errors)
        
        if "nutrition" in plan:
            nutrition = plan["nutrition"]
            
            if "calories" not in nutrition:
                all_errors.append("Nutrition section requires 'calories' field.")
                return ValidationResult(valid=False, errors=all_errors)
            
            if not user_validated:
                all_errors.append("Calorie validation requires user fields (sex, weight_kg, age, height_cm).")
            else:
                try:
                    calories = InputValidator.parse_number(nutrition["calories"], "calories")
                    result = self._validate_calories(
                        proposed_calories=calories,
                        sex=user_validated["sex_str"],
                        weight_kg=user_validated["weight_kg"],
                        age=user_validated["age"],
                        height_cm=user_validated["height_cm"],
                        has_medical_clearance=user_validated["medical_clearance"]
                    )
                    all_errors.extend(result.errors)
                except ValidationError as e:
                    all_errors.append(str(e))
            
            if "protein_g" in nutrition:
                if not user_validated:
                    all_errors.append("Protein validation requires user.weight_kg.")
                else:
                    try:
                        protein_g = InputValidator.parse_number(nutrition["protein_g"], "protein_g")
                        result = self._validate_protein(
                            protein_g=protein_g,
                            weight_kg=user_validated["weight_kg"]
                        )
                        all_errors.extend(result.errors)
                    except ValidationError as e:
                        all_errors.append(str(e))
            
            if "previous_calories" in nutrition and "calories" in nutrition:
                try:
                    previous_calories = InputValidator.parse_number(nutrition["previous_calories"], "previous_calories")
                    current_calories = InputValidator.parse_number(nutrition["calories"], "calories")
                    result = self._validate_calorie_change(
                        current_calories=previous_calories,
                        proposed_calories=current_calories
                    )
                    all_errors.extend(result.errors)
                except ValidationError as e:
                    all_errors.append(str(e))
        
        if "goals" in plan:
            goals = plan["goals"]
            
            if "weight_loss_kg_per_week" in goals:
                if not user_validated:
                    all_errors.append("Weight loss validation requires user.weight_kg.")
                else:
                    try:
                        weight_loss = InputValidator.parse_number(
                            goals["weight_loss_kg_per_week"],
                            "weight_loss_kg_per_week",
                            allow_zero=True,
                            allow_negative=True,
                        )
                        result = self._validate_weight_loss_rate(
                            target_loss_kg_per_week=weight_loss,
                            current_weight_kg=user_validated["weight_kg"]
                        )
                        all_errors.extend(result.errors)
                    except ValidationError as e:
                        all_errors.append(str(e))
        
        if "training" in plan:
            training = plan["training"]
            
            if "previous_load" in training and "current_load" in training:
                try:
                    previous_load = InputValidator.parse_number(training["previous_load"], "previous_load", allow_zero=True)
                    current_load = InputValidator.parse_number(training["current_load"], "current_load", allow_zero=True)
                    result = self.validate_training_load_increase(
                        current_load=previous_load,
                        proposed_load=current_load
                    )
                    all_errors.extend(result.errors)
                except ValidationError as e:
                    all_errors.append(str(e))
            
            if "weeks_since_deload" in training:
                try:
                    weeks = int(InputValidator.parse_number(training["weeks_since_deload"], "weeks_since_deload", allow_zero=True))
                    result = self.validate_deload_schedule(weeks_since_last_deload=weeks)
                    all_errors.extend(result.errors)
                except ValidationError as e:
                    all_errors.append(str(e))
            
            structured_hours = 0.0
            sport_hours = 0.0
            has_structured = "structured_hours" in training
            has_sport = "sport_hours" in training
            
            if has_structured or has_sport:
                try:
                    if has_structured:
                        structured_hours = InputValidator.parse_number(training["structured_hours"], "structured_hours", allow_zero=True)
                    if has_sport:
                        sport_hours = InputValidator.parse_number(training["sport_hours"], "sport_hours", allow_zero=True)
                    
                    result = self.validate_weekly_training_hours(
                        structured_training_hours=structured_hours,
                        sport_practice_hours=sport_hours
                    )
                    all_errors.extend(result.errors)
                except ValidationError as e:
                    all_errors.append(str(e))
        
        return ValidationResult(valid=len(all_errors) == 0, errors=all_errors)


def main():
    """Example usage."""
    validator = PlanValidator()
    
    example_plan = {
        "user": {
            "sex": "M",
            "weight_kg": 80,
            "age": 30,
            "height_cm": 180,
            "medical_clearance": False
        },
        "nutrition": {
            "calories": 2000,
            "protein_g": 144,
            "previous_calories": 2100
        },
        "goals": {
            "weight_loss_kg_per_week": 0.5
        },
        "training": {
            "previous_load": 100,
            "current_load": 108,
            "weeks_since_deload": 4,
            "structured_hours": 6,
            "sport_hours": 3
        }
    }
    
    result = validator.validate_plan(example_plan)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
