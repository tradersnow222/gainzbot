#!/usr/bin/env python3
"""Tests for red_flag_check.py scanning guardrails."""

import pytest
from red_flag_check import RedFlagChecker


class TestChestPainDetection:
    """Test chest pain and cardiac symptom detection."""
    
    def test_clean_text_no_flags(self):
        """Clean text returns no flags."""
        checker = RedFlagChecker()
        result = checker.scan_text("Had a great workout today!")
        assert not result.pause_plan
        assert len(result.flags_detected) == 0
    
    def test_chest_pain_detected(self):
        """Chest pain is detected and plan paused."""
        checker = RedFlagChecker()
        result = checker.scan_text("Experiencing chest pain during my run.")
        assert result.pause_plan
        assert "chest_pain" in result.flags_detected
        assert "emergency" in result.message.lower()
    
    def test_chest_pressure_detected(self):
        """Chest pressure is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Feeling chest pressure and tightness.")
        assert result.pause_plan
        assert "chest_pain" in result.flags_detected
    
    def test_heart_racing_detected(self):
        """Heart racing detected as cardiac symptom."""
        checker = RedFlagChecker()
        result = checker.scan_text("My heart is racing and won't slow down.")
        assert result.pause_plan
        assert "cardiac_symptoms" in result.flags_detected


class TestFaintingDetection:
    """Test fainting and consciousness loss detection."""
    
    def test_fainted_detected(self):
        """Fainting is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("I fainted during my workout yesterday.")
        assert result.pause_plan
        assert "fainting" in result.flags_detected
    
    def test_passed_out_detected(self):
        """Passed out is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Passed out after my set.")
        assert result.pause_plan
        assert "fainting" in result.flags_detected
    
    def test_blacked_out_detected(self):
        """Blacked out is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Blacked out briefly after standing up.")
        assert result.pause_plan
        assert "fainting" in result.flags_detected


class TestJointPainDetection:
    """Test sharp joint pain detection."""
    
    def test_sharp_knee_pain_detected(self):
        """Sharp knee pain is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Sharp knee pain during squats.")
        assert result.pause_plan
        assert "sharp_joint_pain" in result.flags_detected
    
    def test_sharp_shoulder_pain_detected(self):
        """Sharp shoulder pain is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Sharp shoulder pain on overhead press.")
        assert result.pause_plan
        assert "sharp_joint_pain" in result.flags_detected
    
    def test_general_soreness_not_flagged(self):
        """General soreness doesn't trigger red flag."""
        checker = RedFlagChecker()
        result = checker.scan_text("Feeling sore from yesterday's workout.")
        assert not result.pause_plan


class TestInjuryDetection:
    """Test injury detection."""
    
    def test_pulled_muscle_detected(self):
        """Pulled muscle is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("I think I pulled my hamstring.")
        assert result.pause_plan
        assert "injury" in result.flags_detected
    
    def test_torn_ligament_detected(self):
        """Torn ligament is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Worried I tore a ligament in my knee.")
        assert result.pause_plan
        assert "injury" in result.flags_detected
    
    def test_sprained_ankle_detected(self):
        """Sprained ankle is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Sprained my ankle during basketball.")
        assert result.pause_plan
        assert "injury" in result.flags_detected


class TestExtremeFatigueDetection:
    """Test extreme fatigue detection."""
    
    def test_extreme_fatigue_detected(self):
        """Extreme fatigue is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Experiencing extreme fatigue, can barely move.")
        assert result.pause_plan
        assert "extreme_fatigue" in result.flags_detected
    
    def test_severe_fatigue_detected(self):
        """Severe fatigue is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Severe fatigue, can't get out of bed.")
        assert result.pause_plan
        assert "extreme_fatigue" in result.flags_detected
    
    def test_normal_tiredness_not_flagged(self):
        """Normal tiredness doesn't trigger flag."""
        checker = RedFlagChecker()
        result = checker.scan_text("Feeling a bit tired today.")
        assert not result.pause_plan


class TestDisorderedEatingDetection:
    """Test disordered eating pattern detection."""
    
    def test_purging_detected(self):
        """Purging is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("I purged after eating too much yesterday.")
        assert result.pause_plan
        assert "disordered_eating" in result.flags_detected
        assert "professional" in result.message.lower()
    
    def test_vomiting_after_eating_detected(self):
        """Vomiting after eating is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Keep vomiting after meals to stay under calories.")
        assert result.pause_plan
        assert "disordered_eating" in result.flags_detected
    
    def test_food_fear_detected(self):
        """Fear of food is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Terrified of food, haven't eaten in days.")
        assert result.pause_plan
        assert "disordered_eating" in result.flags_detected
    
    def test_punishment_exercise_detected(self):
        """Exercise as punishment is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Need to exercise to punish myself for eating.")
        assert result.pause_plan
        assert "disordered_eating" in result.flags_detected


class TestBreathingDifficulty:
    """Test breathing difficulty detection."""
    
    def test_cant_breathe_detected(self):
        """Can't breathe is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Can't breathe properly during exercise.")
        assert result.pause_plan
        assert "breathing_difficulty" in result.flags_detected
    
    def test_shortness_of_breath_detected(self):
        """Shortness of breath is detected."""
        checker = RedFlagChecker()
        result = checker.scan_text("Severe shortness of breath at rest.")
        assert result.pause_plan
        assert "breathing_difficulty" in result.flags_detected


class TestMultipleFlags:
    """Test detection of multiple flags."""
    
    def test_multiple_flags_detected(self):
        """Multiple red flags are all detected."""
        checker = RedFlagChecker()
        result = checker.scan_text(
            "Experiencing chest pain and dizziness. Also sharp knee pain."
        )
        assert result.pause_plan
        assert "chest_pain" in result.flags_detected
        assert len(result.flags_detected) >= 2
    
    def test_cardiac_severity_prioritized(self):
        """Cardiac symptoms result in emergency message."""
        checker = RedFlagChecker()
        result = checker.scan_text("Chest pain and pulled hamstring.")
        assert result.pause_plan
        assert "emergency" in result.message.lower() or "immediate" in result.message.lower()


class TestCheckInScanning:
    """Test structured check-in scanning."""
    
    def test_clean_check_in(self):
        """Clean check-in has no flags."""
        checker = RedFlagChecker()
        check_in = {
            "notes": "Great workout!",
            "how_feeling": "Strong and energized",
            "pain": "None"
        }
        result = checker.scan_check_in(check_in)
        assert not result.pause_plan
    
    def test_red_flag_in_notes(self):
        """Red flag in notes is detected."""
        checker = RedFlagChecker()
        check_in = {
            "notes": "Experienced chest pain during warm-up",
            "how_feeling": "Concerned",
        }
        result = checker.scan_check_in(check_in)
        assert result.pause_plan
        assert "chest_pain" in result.flags_detected
    
    def test_red_flag_in_pain_field(self):
        """Red flag in pain field is detected."""
        checker = RedFlagChecker()
        check_in = {
            "notes": "Did squats today",
            "pain": "Sharp knee pain on the descent"
        }
        result = checker.scan_check_in(check_in)
        assert result.pause_plan
        assert "sharp_joint_pain" in result.flags_detected
    
    def test_multiple_fields_combined(self):
        """Red flags across multiple fields are detected."""
        checker = RedFlagChecker()
        check_in = {
            "notes": "Pulled hamstring",
            "how_feeling": "Dizzy and fatigued",
            "pain": "Sharp pain in leg"
        }
        result = checker.scan_check_in(check_in)
        assert result.pause_plan
        assert len(result.flags_detected) >= 1


class TestRecommendations:
    """Test recommendation generation."""
    
    def test_cardiac_recommendations_include_emergency(self):
        """Cardiac symptoms include emergency recommendations."""
        checker = RedFlagChecker()
        result = checker.scan_text("Chest pain and pressure.")
        assert result.pause_plan
        assert any("911" in rec or "emergency" in rec.lower() for rec in result.recommendations)
    
    def test_fainting_recommendations_conditional_emergency(self):
        """Fainting has conditional emergency guidance."""
        checker = RedFlagChecker()
        result = checker.scan_text("I fainted during workout.")
        assert result.pause_plan
        assert any("emergency services if" in rec.lower() for rec in result.recommendations)
        assert any("chest pain" in rec.lower() or "breathing" in rec.lower() for rec in result.recommendations)
    
    def test_injury_recommendations_include_rest(self):
        """Injury recommendations include rest guidance."""
        checker = RedFlagChecker()
        result = checker.scan_text("Pulled my hamstring.")
        assert result.pause_plan
        assert any("rest" in rec.lower() for rec in result.recommendations)
    
    def test_disordered_eating_recommendations_include_helpline(self):
        """Disordered eating recommendations include helpline."""
        checker = RedFlagChecker()
        result = checker.scan_text("Purging after meals.")
        assert result.pause_plan
        assert any("NEDA" in rec or "eating disorder" in rec.lower() for rec in result.recommendations)
    
    def test_all_results_include_pause_recommendation(self):
        """All red flag results include pause recommendation."""
        checker = RedFlagChecker()
        result = checker.scan_text("Sharp knee pain.")
        assert result.pause_plan
        assert any("resume" in rec.lower() or "clearance" in rec.lower() for rec in result.recommendations)


class TestFalsePositives:
    """Test that benign phrases don't trigger false positives."""
    
    def test_starving_after_workout_not_flagged(self):
        """'Starving after leg day' doesn't trigger eating disorder flag."""
        checker = RedFlagChecker()
        result = checker.scan_text("I'm starving after leg day!")
        assert not result.pause_plan
        assert len(result.flags_detected) == 0
    
    def test_binge_watched_netflix_not_flagged(self):
        """'Binge-watched Netflix' doesn't trigger eating disorder flag."""
        checker = RedFlagChecker()
        result = checker.scan_text("Binge-watched Netflix last night.")
        assert not result.pause_plan
        assert len(result.flags_detected) == 0
    
    def test_cant_stand_burpees_not_flagged(self):
        """'Can't stand burpees' doesn't trigger dizziness flag."""
        checker = RedFlagChecker()
        result = checker.scan_text("I can't stand burpees, they're so hard!")
        assert not result.pause_plan
        assert len(result.flags_detected) == 0
    
    def test_hurt_my_feelings_not_flagged(self):
        """'Hurt my feelings' doesn't trigger injury flag."""
        checker = RedFlagChecker()
        result = checker.scan_text("That comment hurt my feelings.")
        assert not result.pause_plan
        assert len(result.flags_detected) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
