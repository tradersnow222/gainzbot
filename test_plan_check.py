#!/usr/bin/env python3
"""Tests for plan_check.py validation guardrails."""

import pytest
from plan_check import PlanValidator, ValidationResult


class TestBMREstimation:
    """Test BMR estimation."""
    
    def test_bmr_male(self):
        """Test BMR calculation for males."""
        validator = PlanValidator()
        bmr = validator.estimate_bmr(80, 'M', 30, 180)
        assert 1700 < bmr < 1900
    
    def test_bmr_female(self):
        """Test BMR calculation for females."""
        validator = PlanValidator()
        bmr = validator.estimate_bmr(60, 'F', 30, 165)
        assert 1300 < bmr < 1500


class TestCalorieValidation:
    """Test calorie validation guardrails."""
    
    def test_calories_below_floor_men(self):
        """Reject calories below male floor."""
        validator = PlanValidator()
        result = validator.validate_calories(
            proposed_calories=1400,
            sex='M',
            weight_kg=80,
            age=30,
            height_cm=180
        )
        assert not result.valid
        assert "below the floor" in result.errors[0]
    
    def test_calories_below_floor_women(self):
        """Reject calories below female floor."""
        validator = PlanValidator()
        result = validator.validate_calories(
            proposed_calories=1100,
            sex='F',
            weight_kg=60,
            age=30,
            height_cm=165
        )
        assert not result.valid
        assert "below the floor" in result.errors[0]
    
    def test_calories_below_bmr_without_clearance(self):
        """Reject calories below BMR without medical clearance."""
        validator = PlanValidator()
        result = validator.validate_calories(
            proposed_calories=1600,
            sex='M',
            weight_kg=80,
            age=30,
            height_cm=180,
            has_medical_clearance=False
        )
        assert not result.valid
        assert "BMR" in result.errors[0]
    
    def test_calories_below_bmr_with_clearance(self):
        """Allow calories below BMR with medical clearance."""
        validator = PlanValidator()
        result = validator.validate_calories(
            proposed_calories=1600,
            sex='M',
            weight_kg=80,
            age=30,
            height_cm=180,
            has_medical_clearance=True
        )
        assert result.valid
    
    def test_calories_above_floor_and_bmr(self):
        """Accept calories above both floor and BMR."""
        validator = PlanValidator()
        result = validator.validate_calories(
            proposed_calories=2000,
            sex='M',
            weight_kg=80,
            age=30,
            height_cm=180
        )
        assert result.valid


class TestWeightLossRate:
    """Test weight loss rate validation."""
    
    def test_excessive_weight_loss(self):
        """Reject weight loss exceeding 1% body weight per week."""
        validator = PlanValidator()
        result = validator.validate_weight_loss_rate(
            target_loss_kg_per_week=1.0,
            current_weight_kg=80
        )
        assert not result.valid
        assert "1%" in result.errors[0]
    
    def test_safe_weight_loss(self):
        """Accept weight loss at or below 1% body weight per week."""
        validator = PlanValidator()
        result = validator.validate_weight_loss_rate(
            target_loss_kg_per_week=0.7,
            current_weight_kg=80
        )
        assert result.valid


class TestProteinValidation:
    """Test protein intake validation."""
    
    def test_protein_too_low(self):
        """Reject protein below 1.6 g/kg."""
        validator = PlanValidator()
        result = validator.validate_protein(
            protein_g=120,
            weight_kg=80
        )
        assert not result.valid
        assert "below minimum" in result.errors[0]
    
    def test_protein_too_high(self):
        """Reject protein above 2.2 g/kg."""
        validator = PlanValidator()
        result = validator.validate_protein(
            protein_g=200,
            weight_kg=80
        )
        assert not result.valid
        assert "exceeds maximum" in result.errors[0]
    
    def test_protein_in_range(self):
        """Accept protein in 1.6-2.2 g/kg range."""
        validator = PlanValidator()
        result = validator.validate_protein(
            protein_g=144,
            weight_kg=80
        )
        assert result.valid


class TestCalorieChange:
    """Test weekly calorie change validation."""
    
    def test_excessive_calorie_decrease(self):
        """Reject calorie decrease exceeding 200 kcal/week."""
        validator = PlanValidator()
        result = validator.validate_calorie_change(
            current_calories=2000,
            proposed_calories=1700
        )
        assert not result.valid
        assert "exceeds maximum" in result.errors[0]
    
    def test_excessive_calorie_increase(self):
        """Reject calorie increase exceeding 200 kcal/week."""
        validator = PlanValidator()
        result = validator.validate_calorie_change(
            current_calories=2000,
            proposed_calories=2300
        )
        assert not result.valid
    
    def test_safe_calorie_change(self):
        """Accept calorie change within 200 kcal/week."""
        validator = PlanValidator()
        result = validator.validate_calorie_change(
            current_calories=2000,
            proposed_calories=2150
        )
        assert result.valid


class TestTrainingLoad:
    """Test training load increase validation."""
    
    def test_excessive_load_increase(self):
        """Reject load increase exceeding 10% per week."""
        validator = PlanValidator()
        result = validator.validate_training_load_increase(
            current_load=100,
            proposed_load=115
        )
        assert not result.valid
        assert "10" in result.errors[0] and "%" in result.errors[0]
    
    def test_safe_load_increase(self):
        """Accept load increase within 10% per week."""
        validator = PlanValidator()
        result = validator.validate_training_load_increase(
            current_load=100,
            proposed_load=108
        )
        assert result.valid
    
    def test_first_training_block(self):
        """Accept any load when starting from zero."""
        validator = PlanValidator()
        result = validator.validate_training_load_increase(
            current_load=0,
            proposed_load=100
        )
        assert result.valid


class TestDeloadSchedule:
    """Test deload scheduling validation."""
    
    def test_deload_overdue(self):
        """Require deload after 6 weeks."""
        validator = PlanValidator()
        result = validator.validate_deload_schedule(
            weeks_since_last_deload=7
        )
        assert not result.valid
        assert "Deload required" in result.errors[0]
    
    def test_deload_on_schedule(self):
        """Accept training within 6-week deload window."""
        validator = PlanValidator()
        result = validator.validate_deload_schedule(
            weeks_since_last_deload=4
        )
        assert result.valid


class TestWeeklyTrainingHours:
    """Test weekly training hours validation."""
    
    def test_excessive_training_hours(self):
        """Reject total training exceeding 20 hours per week."""
        validator = PlanValidator()
        result = validator.validate_weekly_training_hours(
            structured_training_hours=15,
            sport_practice_hours=8
        )
        assert not result.valid
        assert "20 hours" in result.errors[0]
    
    def test_safe_training_hours(self):
        """Accept total training within 20 hours per week."""
        validator = PlanValidator()
        result = validator.validate_weekly_training_hours(
            structured_training_hours=10,
            sport_practice_hours=8
        )
        assert result.valid


class TestCompletePlanValidation:
    """Test complete plan validation."""
    
    def test_valid_plan(self):
        """Accept a completely valid plan."""
        validator = PlanValidator()
        plan = {
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
        result = validator.validate_plan(plan)
        assert result.valid
        assert len(result.errors) == 0
    
    def test_multiple_violations(self):
        """Collect all violations in a single validation."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 80,
                "age": 30,
                "height_cm": 180,
                "medical_clearance": False
            },
            "nutrition": {
                "calories": 1400,
                "protein_g": 100,
                "previous_calories": 1700
            },
            "goals": {
                "weight_loss_kg_per_week": 1.5
            },
            "training": {
                "previous_load": 100,
                "current_load": 120,
                "weeks_since_deload": 8,
                "structured_hours": 15,
                "sport_hours": 8
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert len(result.errors) >= 5
    
    def test_minimal_plan(self):
        """Accept plan with only required fields."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "F",
                "weight_kg": 60,
                "age": 25,
                "height_cm": 165
            },
            "nutrition": {
                "calories": 1600,
                "protein_g": 108
            }
        }
        result = validator.validate_plan(plan)
        assert result.valid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
