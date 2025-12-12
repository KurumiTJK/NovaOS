#!/usr/bin/env python3
# tests/test_council.py
"""
Nova Council — Test Suite

Run with: python -m pytest tests/test_council.py -v
Or standalone: python tests/test_council.py
"""

import sys
import os
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from unittest.mock import patch, MagicMock


class TestCouncilState(unittest.TestCase):
    """Test council state management."""
    
    def test_initial_state(self):
        """Test initial state is OFF."""
        from council.state import CouncilState, CouncilMode
        
        state = CouncilState()
        self.assertFalse(state.used)
        self.assertEqual(state.mode, CouncilMode.OFF)
        self.assertEqual(state.gemini_calls, 0)
    
    def test_mark_used(self):
        """Test marking state as used."""
        from council.state import CouncilState, CouncilMode
        
        state = CouncilState()
        state.mark_used(CouncilMode.QUEST)
        
        self.assertTrue(state.used)
        self.assertEqual(state.mode, CouncilMode.QUEST)
        self.assertEqual(state.gemini_calls, 1)
    
    def test_reset(self):
        """Test state reset."""
        from council.state import CouncilState, CouncilMode
        
        state = CouncilState()
        state.mark_used(CouncilMode.LIVE_MAX)
        state.reset()
        
        self.assertFalse(state.used)
        self.assertEqual(state.mode, CouncilMode.OFF)
    
    def test_session_registry(self):
        """Test session state registry."""
        from council.state import get_council_state, reset_council_state, CouncilMode
        
        state1 = get_council_state("session1")
        state1.mark_used(CouncilMode.QUEST)
        
        state2 = get_council_state("session2")
        
        self.assertTrue(state1.used)
        self.assertFalse(state2.used)
        
        # Same session returns same state
        state1_again = get_council_state("session1")
        self.assertTrue(state1_again.used)


class TestCouncilRouter(unittest.TestCase):
    """Test mode detection and routing."""
    
    def test_extract_solo_flag(self):
        """Test @solo flag extraction."""
        from council.router import extract_flags, ExplicitFlag
        
        clean, flag = extract_flags("@solo What is the weather?")
        
        self.assertEqual(flag, ExplicitFlag.SOLO)
        self.assertEqual(clean, "What is the weather?")
    
    def test_extract_live_flag(self):
        """Test @live flag extraction."""
        from council.router import extract_flags, ExplicitFlag
        
        clean, flag = extract_flags("What is the @live latest pricing?")
        
        self.assertEqual(flag, ExplicitFlag.LIVE)
        self.assertIn("latest pricing", clean)
        self.assertNotIn("@live", clean)
    
    def test_command_intent_detection(self):
        """Test command-intent triggers LIVE-MAX."""
        from council.router import detect_council_mode
        from council.state import CouncilMode
        
        mode, clean, reason = detect_council_mode("Create a command for memory stats")
        self.assertEqual(mode, CouncilMode.LIVE_MAX)
        
        mode, clean, reason = detect_council_mode("Design a new #dashboard command")
        self.assertEqual(mode, CouncilMode.LIVE_MAX)
        
        mode, clean, reason = detect_council_mode("Modify the SYS_HANDLERS registry")
        self.assertEqual(mode, CouncilMode.LIVE_MAX)
    
    def test_quest_intent_detection(self):
        """Test quest-intent triggers QUEST."""
        from council.router import detect_council_mode
        from council.state import CouncilMode
        
        mode, clean, reason = detect_council_mode("Create a quest for learning Python")
        self.assertEqual(mode, CouncilMode.QUEST)
        
        mode, clean, reason = detect_council_mode("I need a lesson plan for SQL")
        self.assertEqual(mode, CouncilMode.QUEST)
    
    def test_live_intent_detection(self):
        """Test live-intent triggers LIVE."""
        from council.router import detect_council_mode
        from council.state import CouncilMode
        
        mode, clean, reason = detect_council_mode("What's the latest AWS pricing?")
        self.assertEqual(mode, CouncilMode.LIVE)
        
        mode, clean, reason = detect_council_mode("Verify the current status of X")
        self.assertEqual(mode, CouncilMode.LIVE)
    
    def test_default_solo(self):
        """Test default is SOLO."""
        from council.router import detect_council_mode
        from council.state import CouncilMode
        
        mode, clean, reason = detect_council_mode("Hello, how are you?")
        self.assertEqual(mode, CouncilMode.OFF)
    
    def test_flag_overrides_heuristic(self):
        """Test explicit flag overrides heuristic detection."""
        from council.router import detect_council_mode
        from council.state import CouncilMode
        
        # Quest-intent text with @solo flag
        mode, clean, reason = detect_council_mode("@solo Create a quest for Python")
        self.assertEqual(mode, CouncilMode.OFF)


class TestCouncilValidation(unittest.TestCase):
    """Test JSON schema validation."""
    
    def test_valid_quest_ideation(self):
        """Test valid quest ideation schema."""
        from council.validate import validate_quest_ideation
        
        valid_data = {
            "quest_theme": "Python Basics",
            "goal": "Learn Python fundamentals",
            "difficulty": "medium",
            "estimated_duration": "2 hours",
            "steps": [
                {
                    "step_title": "Setup",
                    "action": "Install Python",
                    "completion_criteria": "Python runs"
                }
            ],
            "risks": ["Time constraints"],
            "notes": "Start simple"
        }
        
        is_valid, error = validate_quest_ideation(valid_data)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
    
    def test_invalid_quest_missing_fields(self):
        """Test quest ideation with missing fields."""
        from council.validate import validate_quest_ideation
        
        invalid_data = {
            "quest_theme": "Python Basics",
            # Missing most fields
        }
        
        is_valid, error = validate_quest_ideation(invalid_data)
        self.assertFalse(is_valid)
        self.assertIn("Missing required fields", error)
    
    def test_invalid_quest_too_many_steps(self):
        """Test quest ideation with too many steps."""
        from council.validate import validate_quest_ideation
        
        data = {
            "quest_theme": "Python",
            "goal": "Learn",
            "difficulty": "low",
            "estimated_duration": "1h",
            "steps": [{"step_title": f"Step {i}", "action": "Do", "completion_criteria": "Done"} 
                      for i in range(6)],  # 6 steps, max is 5
            "risks": [],
            "notes": ""
        }
        
        is_valid, error = validate_quest_ideation(data)
        self.assertFalse(is_valid)
        self.assertIn("Too many steps", error)
    
    def test_valid_live_research(self):
        """Test valid live research schema."""
        from council.validate import validate_live_research
        
        valid_data = {
            "meta": {
                "provider": "gemini",
                "model": "gemini-1.5-pro",
                "mode": "live",
                "timestamp": "2024-01-01T00:00:00Z"
            },
            "facts": ["Fact 1", "Fact 2"],
            "options": [
                {
                    "title": "Option A",
                    "summary": "Do this",
                    "tradeoffs": ["Pro 1"],
                    "risks": ["Risk 1"]
                }
            ],
            "edge_cases": ["Edge 1"],
            "open_questions": ["Question 1"],
            "sources": []
        }
        
        is_valid, error = validate_live_research(valid_data)
        self.assertTrue(is_valid)


class TestPipelineIntegration(unittest.TestCase):
    """Test pipeline orchestration (mocked Gemini)."""
    
    @patch('council.orchestrator.is_gemini_available')
    def test_solo_pipeline_no_gemini(self, mock_available):
        """Test SOLO pipeline doesn't call Gemini."""
        mock_available.return_value = True
        
        from council.orchestrator import run_solo_pipeline
        
        result = run_solo_pipeline("Hello", "session1")
        
        self.assertTrue(result.success)
        self.assertFalse(result.gemini_used)
    
    @patch('council.orchestrator.is_gemini_available')
    @patch('council.orchestrator.gemini_quest_ideate')
    def test_quest_pipeline_with_gemini(self, mock_ideate, mock_available):
        """Test QUEST pipeline calls Gemini."""
        mock_available.return_value = True
        mock_ideate.return_value = {
            "quest_theme": "Test",
            "goal": "Test goal",
            "difficulty": "low",
            "estimated_duration": "1h",
            "steps": [{"step_title": "S1", "action": "A", "completion_criteria": "C"}],
            "risks": [],
            "notes": ""
        }
        
        from council.orchestrator import run_quest_pipeline
        from council.state import CouncilMode
        
        result = run_quest_pipeline("Create a test quest", "session1")
        
        self.assertTrue(result.success)
        self.assertTrue(result.gemini_used)
        self.assertEqual(result.mode, CouncilMode.QUEST)
        self.assertIn("gemini_quest_notes", result.extra_context)
    
    @patch('council.orchestrator.is_gemini_available')
    def test_quest_pipeline_fallback_on_unavailable(self, mock_available):
        """Test QUEST pipeline falls back when Gemini unavailable."""
        mock_available.return_value = False
        
        from council.orchestrator import run_quest_pipeline
        from council.state import CouncilMode
        
        result = run_quest_pipeline("Create a quest", "session1")
        
        self.assertTrue(result.success)  # Still succeeds
        self.assertFalse(result.gemini_used)
        self.assertEqual(result.mode, CouncilMode.OFF)  # Fell back to SOLO


class TestDashboardIntegration(unittest.TestCase):
    """Test dashboard status display."""
    
    def test_get_council_display_status(self):
        """Test dashboard status retrieval."""
        from council.dashboard_integration import get_council_display_status
        from council.state import get_council_state, CouncilMode
        
        # Get fresh state
        state = get_council_state("test_session")
        state.reset()
        
        status = get_council_display_status("test_session")
        self.assertEqual(status, "OFF")
        
        state.mark_used(CouncilMode.QUEST)
        status = get_council_display_status("test_session")
        self.assertEqual(status, "QUEST")
        
        state.mark_used(CouncilMode.LIVE_MAX)
        status = get_council_display_status("test_session")
        self.assertEqual(status, "LIVE-MAX")


if __name__ == "__main__":
    unittest.main(verbosity=2)
