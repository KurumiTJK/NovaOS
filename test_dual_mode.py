# test_dual_mode.py
"""
Test script for NovaOS v0.9.0 Dual-Mode Architecture

Run this script to verify the mode router is working correctly.
It simulates the flow without requiring a full kernel/persona setup.

Usage:
    python test_dual_mode.py
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_nova_state():
    """Test NovaState class."""
    print("=" * 50)
    print("Testing NovaState")
    print("=" * 50)
    
    from core.nova_state import NovaState
    
    # Create state
    state = NovaState(session_id="test-session")
    print(f"✓ Created state: session_id={state.session_id}")
    print(f"  novaos_enabled={state.novaos_enabled}")
    print(f"  mode_name={state.mode_name}")
    
    # Test enable
    state.enable_novaos()
    assert state.novaos_enabled == True
    assert state.mode_name == "NovaOS"
    print(f"✓ After enable: mode_name={state.mode_name}")
    
    # Test disable
    state.disable_novaos()
    assert state.novaos_enabled == False
    assert state.mode_name == "Persona"
    print(f"✓ After disable: mode_name={state.mode_name}")
    
    print("✅ NovaState tests passed!\n")


def test_pattern_matching():
    """Test boot/shutdown pattern matching."""
    print("=" * 50)
    print("Testing Pattern Matching")
    print("=" * 50)
    
    from core.mode_router import _is_boot_command, _is_shutdown_command
    
    # Boot patterns
    boot_tests = [
        ("#boot", True),
        ("#BOOT", True),
        ("#Boot", True),
        ("#boot now", True),
        ("boot", False),
        ("# boot", False),
        ("#bootstrap", False),
        ("#booting", False),
    ]
    
    for test_input, expected in boot_tests:
        result = _is_boot_command(test_input)
        status = "✓" if result == expected else "✗"
        print(f"  {status} _is_boot_command('{test_input}') = {result} (expected {expected})")
        assert result == expected, f"Failed for '{test_input}'"
    
    # Shutdown patterns
    shutdown_tests = [
        ("#shutdown", True),
        ("#SHUTDOWN", True),
        ("#Shutdown", True),
        ("#shutdown now", True),
        ("shutdown", False),
        ("# shutdown", False),
        ("#shutdowns", False),
    ]
    
    for test_input, expected in shutdown_tests:
        result = _is_shutdown_command(test_input)
        status = "✓" if result == expected else "✗"
        print(f"  {status} _is_shutdown_command('{test_input}') = {result} (expected {expected})")
        assert result == expected, f"Failed for '{test_input}'"
    
    print("✅ Pattern matching tests passed!\n")


def test_state_management():
    """Test session state management."""
    print("=" * 50)
    print("Testing State Management")
    print("=" * 50)
    
    from core.mode_router import get_or_create_state, get_state, clear_state
    
    # Clear any existing state
    clear_state("test-session-mgmt")
    
    # Get state (should be None)
    state = get_state("test-session-mgmt")
    assert state is None
    print("✓ get_state returns None for non-existent session")
    
    # Get or create (should create)
    state = get_or_create_state("test-session-mgmt")
    assert state is not None
    assert state.session_id == "test-session-mgmt"
    print(f"✓ get_or_create_state creates new state")
    
    # Get again (should return same)
    state2 = get_or_create_state("test-session-mgmt")
    assert state is state2
    print("✓ get_or_create_state returns same instance")
    
    # Clear
    clear_state("test-session-mgmt")
    state = get_state("test-session-mgmt")
    assert state is None
    print("✓ clear_state removes state")
    
    print("✅ State management tests passed!\n")


class MockKernel:
    """Mock kernel for testing."""
    
    def __init__(self):
        self.handle_input_calls = []
    
    def handle_input(self, text, session_id):
        self.handle_input_calls.append((text, session_id))
        
        # Simulate different responses
        if text == "#boot":
            return {
                "ok": True,
                "type": "syscommand",
                "command": "boot",
                "summary": "NovaOS kernel booted.",
                "text": "NovaOS kernel booted.",
            }
        elif text == "#shutdown":
            return {
                "ok": True,
                "type": "syscommand",
                "command": "shutdown",
                "summary": "NovaOS shutting down.",
                "text": "NovaOS shutting down.",
            }
        elif text == "#status":
            return {
                "ok": True,
                "type": "syscommand",
                "command": "status",
                "summary": "All systems operational.",
                "text": "All systems operational.",
            }
        else:
            # Persona fallback
            return {
                "ok": True,
                "type": "persona",
                "summary": f"I heard: {text}",
                "text": f"I heard: {text}",
            }


class MockPersona:
    """Mock persona for testing."""
    
    def __init__(self):
        self.generate_response_calls = []
    
    def generate_response(self, text, session_id, wm_context_string=None, direct_answer=None, assistant_mode=None):
        self.generate_response_calls.append({
            "text": text,
            "session_id": session_id,
            "wm_context_string": wm_context_string,
            "direct_answer": direct_answer,
        })
        
        # If direct answer provided, return it
        if direct_answer:
            return direct_answer
        
        return f"Persona response to: {text}"


def test_mode_routing():
    """Test mode routing logic."""
    print("=" * 50)
    print("Testing Mode Routing (with mocks)")
    print("=" * 50)
    
    from core.mode_router import handle_user_message, get_or_create_state, clear_state
    
    # Setup
    clear_state("test-routing")
    state = get_or_create_state("test-routing")
    kernel = MockKernel()
    persona = MockPersona()
    
    # Test 1: Persona mode - regular chat
    print("\n--- Test 1: Persona mode - regular chat ---")
    result = handle_user_message("hello", state, kernel, persona)
    print(f"  Mode: {result.get('mode')}")
    print(f"  Handled by: {result.get('handled_by')}")
    print(f"  Text: {result.get('text', '')[:50]}...")
    assert result["mode"] == "Persona"
    assert result["handled_by"] == "persona"
    assert len(kernel.handle_input_calls) == 0  # Kernel not called
    print("  ✓ Passed")
    
    # Test 2: Persona mode - #boot
    print("\n--- Test 2: Persona mode - #boot ---")
    result = handle_user_message("#boot", state, kernel, persona)
    print(f"  Mode: {result.get('mode')}")
    print(f"  Event: {result.get('event')}")
    assert result["mode"] == "NovaOS"
    assert result["event"] == "boot"
    assert state.novaos_enabled == True
    print("  ✓ Passed")
    
    # Test 3: NovaOS mode - syscommand
    print("\n--- Test 3: NovaOS mode - #status ---")
    result = handle_user_message("#status", state, kernel, persona)
    print(f"  Mode: {result.get('mode')}")
    print(f"  Handled by: {result.get('handled_by')}")
    print(f"  Command: {result.get('command')}")
    assert result["mode"] == "NovaOS"
    assert result["handled_by"] == "kernel"
    assert "#status" in [call[0] for call in kernel.handle_input_calls]
    print("  ✓ Passed")
    
    # Test 4: NovaOS mode - regular chat (fallback)
    print("\n--- Test 4: NovaOS mode - regular chat (fallback) ---")
    result = handle_user_message("what's the weather?", state, kernel, persona)
    print(f"  Mode: {result.get('mode')}")
    print(f"  Handled by: {result.get('handled_by')}")
    assert result["mode"] == "NovaOS"
    # Kernel handles but falls back to persona
    assert result["handled_by"] == "persona"
    print("  ✓ Passed")
    
    # Test 5: NovaOS mode - #shutdown
    print("\n--- Test 5: NovaOS mode - #shutdown ---")
    result = handle_user_message("#shutdown", state, kernel, persona)
    print(f"  Mode: {result.get('mode')}")
    print(f"  Event: {result.get('event')}")
    assert result["mode"] == "Persona"
    assert result["event"] == "shutdown"
    assert state.novaos_enabled == False
    print("  ✓ Passed")
    
    # Test 6: Back in Persona mode - command ignored
    print("\n--- Test 6: Persona mode - #status (not executed) ---")
    kernel.handle_input_calls.clear()
    result = handle_user_message("#status", state, kernel, persona)
    print(f"  Mode: {result.get('mode')}")
    print(f"  Handled by: {result.get('handled_by')}")
    assert result["mode"] == "Persona"
    assert result["handled_by"] == "persona"
    assert len(kernel.handle_input_calls) == 0  # Kernel not called
    print("  ✓ Passed")
    
    print("\n✅ Mode routing tests passed!\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  NovaOS v0.9.0 Dual-Mode Architecture Tests")
    print("=" * 60 + "\n")
    
    try:
        test_nova_state()
        test_pattern_matching()
        test_state_management()
        test_mode_routing()
        
        print("=" * 60)
        print("  ✅ ALL TESTS PASSED!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except ImportError as e:
        print(f"\n❌ IMPORT ERROR: {e}")
        print("Make sure the core/ folder is in your project root.")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
