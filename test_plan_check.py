#!/usr/bin/env python3
"""Tests for plan_check.py validation guardrails."""

import pytest
from plan_check import PlanValidator, ValidationResult
from readiness_screen import ReadinessScreen
from red_flag_check import RedFlagChecker


def passing_check_in():
    checker = RedFlagChecker()
    answers = {
        aliases[0]: "no"
        for _flag, aliases in checker.CHECKLIST_GROUPS
    }
    return checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })


def minor_screen(age=15):
    screener = ReadinessScreen()
    return screener.screen_intake({
        "age": age,
        "parental_consent": True,
        "par_q": {flag: False for flag in screener.PAR_Q_RED_FLAGS},
        "pregnant": False,
        "medical_conditions": "none",
        "medical_clearance": False,
    })


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
        """A zero baseline cannot jump to a new load."""
        validator = PlanValidator()
        result = validator.validate_training_load_increase(
            current_load=0,
            proposed_load=100
        )
        assert not result.valid
        assert "baseline" in result.errors[0].lower()


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
        result = validator.validate_plan(plan, check_in_result=passing_check_in())
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
        result = validator.validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid


class TestMessyInput:
    """Test handling of messy and invalid input."""
    
    def test_empty_plan_rejected(self):
        """Empty plan is rejected."""
        validator = PlanValidator()
        result = validator.validate_plan({})
        assert not result.valid
        assert "empty" in result.errors[0].lower()
    
    def test_missing_user_fields_rejected(self):
        """Plan with missing required user fields is rejected."""
        validator = PlanValidator()
        plan = {
            "user": {"sex": "M"},
            "nutrition": {"calories": 2000}
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("weight_kg" in err.lower() for err in result.errors)
    
    def test_string_boolean_false_not_clearance(self):
        """String 'false' must not count as clearance."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 100,
                "age": 30,
                "height_cm": 180,
                "medical_clearance": "false"
            },
            "nutrition": {
                "calories": 1600
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("BMR" in err for err in result.errors)
    
    def test_numeric_string_calories_parsed(self):
        """Numeric string for calories is parsed."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "F",
                "weight_kg": 60,
                "age": 25,
                "height_cm": 165
            },
            "nutrition": {
                "calories": "1600",
                "protein_g": "108"
            }
        }
        result = validator.validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid
    
    def test_nan_rejected(self):
        """NaN values are rejected."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": float('nan'),
                "age": 30,
                "height_cm": 180
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("not finite" in err.lower() or "nan" in err.lower() for err in result.errors)
    
    def test_zero_weight_rejected(self):
        """Zero weight is rejected."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 0,
                "age": 30,
                "height_cm": 180
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("weight_kg" in err.lower() for err in result.errors)
    
    def test_negative_calories_rejected(self):
        """Negative calories are rejected."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 80,
                "age": 30,
                "height_cm": 180
            },
            "nutrition": {
                "calories": -1000
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("negative" in err.lower() or "positive" in err.lower() for err in result.errors)
    
    def test_title_case_sex_accepted(self):
        """Title case sex is accepted."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "Male",
                "weight_kg": 80,
                "age": 30,
                "height_cm": 180
            },
            "nutrition": {
                "calories": 2000,
                "protein_g": 144
            }
        }
        result = validator.validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid
    
    def test_sport_hours_without_structured_validated(self):
        """Sport hours without structured hours is validated against cap."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 80,
                "age": 30,
                "height_cm": 180
            },
            "training": {
                "sport_hours": 25
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("20 hours" in err for err in result.errors)


class TestBMREnforcement:
    """Test BMR enforcement requires explicit clearance."""
    
    def test_100kg_man_at_1600_fails_without_clearance(self):
        """100 kg man at 1600 kcal must fail (BMR ~2011)."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 100,
                "age": 30,
                "height_cm": 180,
                "medical_clearance": False
            },
            "nutrition": {
                "calories": 1600
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("BMR" in err for err in result.errors)
    
    def test_100kg_man_at_1600_passes_with_clearance(self):
        """100 kg man at 1600 kcal passes with explicit true clearance."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 100,
                "age": 30,
                "height_cm": 180,
                "medical_clearance": True
            },
            "nutrition": {
                "calories": 1600
            }
        }
        result = validator.validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid


class TestK06aProbes:
    """Test K06a probe scenarios."""
    
    def test_unknown_key_kcal_rejected(self):
        """Unknown key 'kcal' instead of 'calories' is rejected."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "F",
                "weight_kg": 60,
                "age": 25,
                "height_cm": 165
            },
            "nutrition": {
                "kcal": 800
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("unknown" in err.lower() and "kcal" in err.lower() for err in result.errors)
    
    def test_empty_nutrition_rejected(self):
        """Empty nutrition section is rejected (missing required calories)."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "F",
                "weight_kg": 60,
                "age": 25,
                "height_cm": 165
            },
            "nutrition": {}
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("calories" in err.lower() and "require" in err.lower() for err in result.errors)
    
    def test_par_q_is_an_allowed_plan_key(self):
        flags = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}
        plan = {
            "user": {"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180},
            "training": {
                "previous_load": 100,
                "current_load": 100,
                "weeks_since_deload": 0,
                "structured_hours": 1,
                "sport_hours": 0,
            },
            "par_q": flags,
        }
        result = PlanValidator().validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid, result.errors
        bad = dict(plan, par_q={**flags, "not_a_question": False})
        refused = PlanValidator().validate_plan(bad, check_in_result=passing_check_in())
        assert not refused.valid
        assert any("not_a_question" in err for err in refused.errors)

    def test_unknown_key_sport_hrs_rejected(self):
        """Unknown key 'sport_hrs' instead of 'sport_hours' is rejected."""
        validator = PlanValidator()
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 80,
                "age": 30,
                "height_cm": 180
            },
            "nutrition": {
                "calories": 2000
            },
            "training": {
                "sport_hrs": 40
            }
        }
        result = validator.validate_plan(plan)
        assert not result.valid
        assert any("unknown" in err.lower() and "sport_hrs" in err.lower() for err in result.errors)
    
    def test_validate_protein_with_zero_weight_safe(self):
        """validate_protein with zero weight doesn't crash."""
        validator = PlanValidator()
        result = validator._validate_protein(100, 0)
        assert not result.valid
        assert any("weight_kg" in err.lower() for err in result.errors)
    
    def test_validate_calories_with_invalid_inputs_safe(self):
        """validate_calories with invalid inputs doesn't crash."""
        validator = PlanValidator()
        result = validator._validate_calories(
            proposed_calories="abc",
            sex="M",
            weight_kg=80,
            age=30,
            height_cm=180
        )
        assert not result.valid
        assert any("calories" in err.lower() for err in result.errors)


class TestReviewerProbes:
    """Reviewer probes for plan_check. Each case asserts block or pass."""

    USER = {"sex": "F", "weight_kg": 60, "age": 30, "height_cm": 165}

    @pytest.mark.parametrize(
        "name,plan,expected_valid",
        [
            ("empty plan", {}, False),
            (
                "kcal alias",
                {"user": USER, "nutrition": {"kcal": 800}},
                False,
            ),
            ("nutrition empty", {"user": USER, "nutrition": {}}, False),
            ("only user", {"user": USER}, False),
            (
                "male 1300",
                {
                    "user": {"sex": "male", "weight_kg": 80, "age": 30, "height_cm": 180},
                    "nutrition": {"calories": 1300},
                },
                False,
            ),
            (
                "Male 1300 with clearance still under floor",
                {
                    "user": {
                        "sex": "Male",
                        "weight_kg": 50,
                        "age": 70,
                        "height_cm": 150,
                        "medical_clearance": True,
                    },
                    "nutrition": {"calories": 1300},
                },
                False,
            ),
            ("no user", {"nutrition": {"calories": 1450}}, False),
            (
                "female missing weight",
                {"user": {"sex": "F"}, "nutrition": {"calories": 1250}},
                False,
            ),
            (
                "clearance string false",
                {
                    "user": {
                        "sex": "M",
                        "weight_kg": 100,
                        "age": 30,
                        "height_cm": 185,
                        "medical_clearance": "false",
                    },
                    "nutrition": {"calories": 1600},
                },
                False,
            ),
            (
                "clearance curly quoted true",
                {
                    "user": {
                        "sex": "M",
                        "weight_kg": 100,
                        "age": 30,
                        "height_cm": 185,
                        "medical_clearance": "\u201ctrue\u201d",
                    },
                    "nutrition": {"calories": 1600},
                },
                True,
            ),
            (
                "NaN calories",
                {"user": USER, "nutrition": {"calories": float("nan")}},
                False,
            ),
            (
                "calories numeric string below floor",
                {"user": USER, "nutrition": {"calories": "1000"}},
                False,
            ),
            (
                "calories thousands separator",
                {"user": USER, "nutrition": {"calories": "1,800"}},
                True,
            ),
            (
                "sex None",
                {
                    "user": {"sex": None, "weight_kg": 60, "age": 30, "height_cm": 165},
                    "nutrition": {"calories": 1300},
                },
                False,
            ),
            (
                "weight zero",
                {
                    "user": {"sex": "F", "weight_kg": 0, "age": 30, "height_cm": 165},
                    "nutrition": {"protein_g": 100},
                },
                False,
            ),
            (
                "weight loss gain",
                {"user": USER, "goals": {"weight_loss_kg_per_week": -5}},
                False,
            ),
            (
                "weight loss maintain",
                {"user": USER, "goals": {"weight_loss_kg_per_week": 0}},
                True,
            ),
            (
                "load drop",
                {"training": {"previous_load": 100, "current_load": 0}},
                True,
            ),
            (
                "load from zero",
                {"training": {"previous_load": 0, "current_load": 1000}},
                False,
            ),
            ("deload negative", {"training": {"weeks_since_deload": -3}}, False),
            ("sport hours over cap", {"training": {"sport_hours": 30}}, False),
            (
                "weight loss without user",
                {"goals": {"weight_loss_kg_per_week": 0.7}},
                False,
            ),
            (
                "sport_hrs alias",
                {"training": {"sport_hrs": 40, "structured_hours": 2}},
                False,
            ),
            (
                "nutrition string",
                {"user": USER, "nutrition": "1000 kcal"},
                False,
            ),
            (
                "user list",
                {"user": ["F"], "nutrition": {"calories": 1000}},
                False,
            ),
            (
                "age 12 above female floor",
                {
                    "user": {"sex": "F", "weight_kg": 40, "age": 12, "height_cm": 150},
                    "nutrition": {"calories": 1250},
                },
                False,
            ),
            (
                "height in meters",
                {
                    "user": {"sex": "F", "weight_kg": 60, "age": 30, "height_cm": 1.65},
                    "nutrition": {"calories": 1250},
                },
                False,
            ),
            (
                "weight with pounds unit",
                {
                    "user": {
                        "sex": "F",
                        "weight_kg": "132 lbs",
                        "age": 30,
                        "height_cm": 165,
                    },
                    "nutrition": {"calories": 1250},
                },
                False,
            ),
            (
                "valid baseline",
                {
                    "user": {"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180},
                    "nutrition": {
                        "calories": 2000,
                        "protein_g": 144,
                        "previous_calories": 2100,
                    },
                    "goals": {"weight_loss_kg_per_week": 0.5},
                    "training": {
                        "previous_load": 100,
                        "current_load": 108,
                        "weeks_since_deload": 4,
                        "structured_hours": 6,
                        "sport_hours": 3,
                    },
                },
                True,
            ),
        ],
    )
    def test_plan_probe(self, name, plan, expected_valid):
        result = PlanValidator().validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid is expected_valid

    def test_direct_validate_calories_normalizes_sex(self):
        result = PlanValidator().validate_calories(1300, "Male", 50, 70, 150, True)
        assert result.valid is False

    def test_direct_validate_protein_zero_weight_does_not_crash(self):
        result = PlanValidator().validate_protein(100, 0)
        assert result.valid is False


class _Clearance:
    def __init__(self, value):
        self.value = value


class _Screen:
    def __init__(self, clearance, blocked):
        self.clearance = _Clearance(clearance)
        self.blocked = blocked


PASSING_SCREEN = {"clearance": "caution", "blocked": False}


class TestAgeReadinessAndRates:
    """Age gates, gain cap, and load baseline."""

    def test_under_13_rejected_even_with_passing_screen(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 40, "age": 12, "height_cm": 150},
            "nutrition": {"calories": 2000},
        }
        result = PlanValidator().validate_plan(plan, PASSING_SCREEN)
        assert not result.valid
        assert "under 13" in result.errors[0].lower()
        assert "floor" not in " ".join(result.errors).lower()

    def test_under_18_without_screen_does_not_apply_adult_floor(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 40, "age": 16, "height_cm": 150},
            "nutrition": {"calories": 1150},
        }
        result = PlanValidator().validate_plan(plan)
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "under 18" in blob
        assert "readiness" in blob
        assert "floor" not in blob

    def test_under_18_with_passing_screen_rejects_calorie_target(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 40, "age": 16, "height_cm": 150},
            "nutrition": {"calories": 1150},
        }
        result = PlanValidator().validate_plan(plan, minor_screen(16))
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "under 18" in blob
        assert "floor" not in blob
        assert "bmr" not in blob

    def test_fifteen_with_clearance_and_screen_rejects_600_kcal(self):
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 55,
                "age": 15,
                "height_cm": 170,
                "medical_clearance": True,
            },
            "nutrition": {"calories": 600},
            "training": {"previous_load": 80, "current_load": 84},
        }
        result = PlanValidator().validate_plan(plan, minor_screen(15))
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "under 18" in blob
        assert "floor" not in blob

    def test_minor_high_calories_still_rejected(self):
        plan = {
            "user": {
                "sex": "F",
                "weight_kg": 50,
                "age": 17,
                "height_cm": 160,
                "medical_clearance": True,
            },
            "nutrition": {"calories": 2200},
        }
        result = PlanValidator().validate_plan(plan, minor_screen(17))
        assert not result.valid
        assert "floor" not in " ".join(result.errors).lower()

    def test_minor_deficit_rejected_with_passing_screen(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 50, "age": 16, "height_cm": 160},
            "goals": {"weight_loss_kg_per_week": 0.2},
        }
        result = PlanValidator().validate_plan(plan, minor_screen(16))
        assert not result.valid
        assert "deficit" in " ".join(result.errors).lower()

    def test_minor_training_without_calories_passes(self):
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 55,
                "age": 15,
                "height_cm": 170,
                "medical_clearance": True,
            },
            "training": {
                "previous_load": 100,
                "current_load": 105,
                "structured_hours": 4,
                "sport_hours": 2,
            },
        }
        result = PlanValidator().validate_plan(
            plan, minor_screen(15), passing_check_in()
        )
        assert result.valid
        assert result.errors == []

    def test_blocked_or_uncleared_screen_does_not_pass(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 40, "age": 16, "height_cm": 150},
            "nutrition": {"calories": 1800},
        }
        validator = PlanValidator()
        blocked = validator.validate_plan(plan, {"clearance": "clear", "blocked": True})
        doctor = validator.validate_plan(
            plan, {"clearance": "needs_doctor_clearance", "blocked": False}
        )
        assert not blocked.valid
        assert not doctor.valid

    def test_age_over_100_rejected(self):
        plan = {
            "user": {"sex": "M", "weight_kg": 70, "age": 100.2, "height_cm": 170},
            "nutrition": {"calories": 2000},
        }
        result = PlanValidator().validate_plan(plan)
        assert not result.valid
        assert "plausible" in result.errors[0].lower()

    def test_age_100_adult_floor_still_applies(self):
        plan = {
            "user": {"sex": "M", "weight_kg": 70, "age": 100, "height_cm": 170},
            "nutrition": {"calories": 1800},
        }
        result = PlanValidator().validate_plan(plan, check_in_result=passing_check_in())
        assert result.valid

    def test_age_18_still_uses_adult_floor(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 60, "age": 18, "height_cm": 165},
            "nutrition": {"calories": 1100},
        }
        result = PlanValidator().validate_plan(plan)
        assert not result.valid
        assert "floor" in " ".join(result.errors).lower()

    def test_child_below_bmr_still_rejected_with_screen(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 40, "age": 16, "height_cm": 150},
            "nutrition": {"calories": 900},
        }
        result = PlanValidator().validate_plan(plan, minor_screen(16))
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "under 18" in blob
        assert "floor" not in blob
        assert "bmr" not in blob

    def test_direct_calories_reject_child_without_screen(self):
        result = PlanValidator().validate_calories(2000, "F", 40, 12, 150)
        assert not result.valid
        assert "floor" not in " ".join(result.errors).lower()

    def test_direct_calories_reject_minor_even_with_clearance_and_screen(self):
        result = PlanValidator().validate_calories(
            600, "M", 55, 15, 170, True, {"clearance": "clear", "blocked": False}
        )
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "under 18" in blob
        assert "floor" not in blob

    def test_gain_within_one_percent_passes(self):
        result = PlanValidator().validate_weight_loss_rate(-0.5, 60)
        assert result.valid

    def test_gain_over_one_percent_rejected(self):
        result = PlanValidator().validate_weight_loss_rate(-0.7, 60)
        assert not result.valid
        assert "gain" in result.errors[0].lower()

    def test_maintain_still_passes(self):
        result = PlanValidator().validate_weight_loss_rate(0, 60)
        assert result.valid

    def test_missing_load_baseline_rejected(self):
        result = PlanValidator().validate_plan({"training": {"current_load": 100}})
        assert not result.valid
        assert "baseline" in " ".join(result.errors).lower()

    def test_zero_to_zero_load_passes(self):
        result = PlanValidator().validate_plan(
            {"training": {"previous_load": 0, "current_load": 0}},
            check_in_result=passing_check_in(),
        )
        assert result.valid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
