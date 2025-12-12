#!/usr/bin/env python3
"""
NovaOS Reminders System Tests — v2.0.0

Tests for:
- Windowed reminders (Sunday 5pm-11:59pm example)
- Snooze behavior
- Recurrence advancement
- Due detection
"""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import tempfile
import shutil
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from kernel.reminders_manager import (
    RemindersManager,
    Reminder,
    RepeatConfig,
    RepeatWindow,
    DEFAULT_TIMEZONE,
)


class TestRemindersManager(unittest.TestCase):
    """Test RemindersManager core functionality."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir)
        self.manager = RemindersManager(self.data_dir)
        self.manager._items = {}
        self.manager._save()
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_add_simple_reminder(self):
        """Test adding a simple one-time reminder."""
        reminder = self.manager.add(title="Test", due="2025-12-15 17:00")
        self.assertEqual(reminder.title, "Test")
        self.assertTrue(reminder.id.startswith("rem_"))
        self.assertEqual(reminder.status, "active")
        self.assertFalse(reminder.is_recurring)
    
    def test_add_recurring_daily(self):
        """Test adding a daily recurring reminder."""
        reminder = self.manager.add(
            title="Daily", due="2025-12-15 09:00",
            repeat={"type": "daily", "interval": 1},
        )
        self.assertTrue(reminder.is_recurring)
        self.assertEqual(reminder.repeat.type, "daily")
    
    def test_add_weekly_with_window(self):
        """Test adding a weekly reminder with catch window."""
        reminder = self.manager.add(
            title="Weekly Review", due="2025-12-14 17:00",
            repeat={"type": "weekly", "interval": 1, "by_day": ["SU"]},
            window={"start": "17:00", "end": "23:59"},
        )
        self.assertTrue(reminder.has_window)
        self.assertEqual(reminder.repeat.window.start, "17:00")
    
    def test_snooze(self):
        """Test snooze functionality."""
        reminder = self.manager.add(title="Snoozable", due="2025-12-15 17:00")
        snoozed = self.manager.snooze(reminder.id, "1h")
        self.assertIsNotNone(snoozed.snoozed_until)
    
    def test_complete_non_recurring(self):
        """Test completing a non-recurring reminder."""
        reminder = self.manager.add(title="One-time", due="2025-12-15 17:00")
        completed = self.manager.complete(reminder.id)
        self.assertEqual(completed.status, "done")
    
    def test_complete_recurring_advances(self):
        """Test completing a recurring reminder advances due date."""
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        now = datetime.now(tz)
        reminder = self.manager.add(
            title="Daily", due=now.isoformat(),
            repeat={"type": "daily", "interval": 1},
        )
        original_due = reminder.due_at
        completed = self.manager.complete(reminder.id)
        self.assertEqual(completed.status, "active")
        self.assertNotEqual(completed.due_at, original_due)
    
    def test_pin_unpin(self):
        """Test pin and unpin functionality."""
        reminder = self.manager.add(title="Pinnable", due="2025-12-15 17:00")
        self.assertFalse(reminder.pinned)
        pinned = self.manager.pin(reminder.id)
        self.assertTrue(pinned.pinned)
        unpinned = self.manager.unpin(reminder.id)
        self.assertFalse(unpinned.pinned)


class TestWindowedReminders(unittest.TestCase):
    """Test windowed reminder behavior."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RemindersManager(Path(self.temp_dir))
        self.manager._items = {}
        self.manager._save()
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_window_not_due_before(self):
        """Sunday 4:30pm — NOT due (window starts at 5pm)."""
        sunday_5pm = datetime(2025, 12, 14, 17, 0, 0, tzinfo=self.tz)
        reminder = self.manager.add(
            title="Weekly Review", due=sunday_5pm.isoformat(),
            repeat={"type": "weekly", "interval": 1, "by_day": ["SU"]},
            window={"start": "17:00", "end": "23:59"},
        )
        check_time = sunday_5pm.replace(hour=16, minute=30)
        self.assertFalse(self.manager.is_due_now(reminder, check_time))
    
    def test_window_due_inside(self):
        """Sunday 6:00pm — due (inside window)."""
        sunday_5pm = datetime(2025, 12, 14, 17, 0, 0, tzinfo=self.tz)
        reminder = self.manager.add(
            title="Weekly Review", due=sunday_5pm.isoformat(),
            repeat={"type": "weekly", "interval": 1, "by_day": ["SU"]},
            window={"start": "17:00", "end": "23:59"},
        )
        check_time = sunday_5pm.replace(hour=18, minute=0)
        self.assertTrue(self.manager.is_due_now(reminder, check_time))
    
    def test_window_due_at_end(self):
        """Sunday 11:58pm — due (still in window)."""
        sunday_5pm = datetime(2025, 12, 14, 17, 0, 0, tzinfo=self.tz)
        reminder = self.manager.add(
            title="Weekly Review", due=sunday_5pm.isoformat(),
            repeat={"type": "weekly", "interval": 1, "by_day": ["SU"]},
            window={"start": "17:00", "end": "23:59"},
        )
        check_time = sunday_5pm.replace(hour=23, minute=58)
        self.assertTrue(self.manager.is_due_now(reminder, check_time))
    
    def test_window_rollover_after_end(self):
        """Monday 12:05am — rolled forward + missed_count incremented."""
        sunday_5pm = datetime(2025, 12, 14, 17, 0, 0, tzinfo=self.tz)
        reminder = self.manager.add(
            title="Weekly Review", due=sunday_5pm.isoformat(),
            repeat={"type": "weekly", "interval": 1, "by_day": ["SU"]},
            window={"start": "17:00", "end": "23:59"},
        )
        original_due = reminder.due_at
        monday_1205am = datetime(2025, 12, 15, 0, 5, 0, tzinfo=self.tz)
        rolled = self.manager.apply_window_rollover(reminder, monday_1205am)
        self.assertTrue(rolled)
        self.assertEqual(reminder.missed_count, 1)
        self.assertNotEqual(reminder.due_at, original_due)


class TestSnoozeOverridesDue(unittest.TestCase):
    """Test that snooze temporarily overrides due_at."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RemindersManager(Path(self.temp_dir))
        self.manager._items = {}
        self.manager._save()
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_snooze_overrides_due(self):
        """Snooze should override due_at for is_due_now checks."""
        now = datetime.now(self.tz)
        reminder = self.manager.add(title="Due now", due=now.isoformat())
        self.assertTrue(self.manager.is_due_now(reminder, now))
        
        self.manager.snooze(reminder.id, "1h")
        reminder = self.manager.get(reminder.id)
        self.assertFalse(self.manager.is_due_now(reminder, now))
        
        future = now + timedelta(hours=2)
        self.assertTrue(self.manager.is_due_now(reminder, future))
    
    def test_snooze_does_not_change_due_at(self):
        """Snooze should not modify due_at field."""
        now = datetime.now(self.tz)
        due_time = now + timedelta(hours=1)
        reminder = self.manager.add(title="Future", due=due_time.isoformat())
        original_due = reminder.due_at
        
        self.manager.snooze(reminder.id, "30m")
        reminder = self.manager.get(reminder.id)
        self.assertEqual(reminder.due_at, original_due)


class TestRecurrenceAdvancement(unittest.TestCase):
    """Test that completing recurring reminders advances correctly."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RemindersManager(Path(self.temp_dir))
        self.manager._items = {}
        self.manager._save()
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_daily_advances_by_one_day(self):
        """Daily reminder should advance by 1 day."""
        today = datetime(2025, 12, 15, 9, 0, 0, tzinfo=self.tz)
        reminder = self.manager.add(
            title="Daily", due=today.isoformat(),
            repeat={"type": "daily", "interval": 1},
        )
        self.manager.complete(reminder.id)
        reminder = self.manager.get(reminder.id)
        new_due = datetime.fromisoformat(reminder.due_at).astimezone(self.tz)
        self.assertEqual(new_due.date(), (today + timedelta(days=1)).date())
    
    def test_weekly_advances_by_one_week(self):
        """Weekly reminder should advance by 1 week."""
        sunday = datetime(2025, 12, 14, 17, 0, 0, tzinfo=self.tz)
        reminder = self.manager.add(
            title="Weekly", due=sunday.isoformat(),
            repeat={"type": "weekly", "interval": 1, "by_day": ["SU"]},
        )
        self.manager.complete(reminder.id)
        reminder = self.manager.get(reminder.id)
        new_due = datetime.fromisoformat(reminder.due_at).astimezone(self.tz)
        self.assertEqual(new_due.date(), (sunday + timedelta(weeks=1)).date())
    
    def test_completing_clears_snooze(self):
        """Completing a recurring reminder should clear snoozed_until."""
        now = datetime.now(self.tz)
        reminder = self.manager.add(
            title="Snoozed recurring", due=now.isoformat(),
            repeat={"type": "daily", "interval": 1},
        )
        self.manager.snooze(reminder.id, "1h")
        self.manager.complete(reminder.id)
        reminder = self.manager.get(reminder.id)
        self.assertIsNone(reminder.snoozed_until)


class TestDueDetection(unittest.TestCase):
    """Test due now / due today / overdue detection."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = RemindersManager(Path(self.temp_dir))
        self.manager._items = {}
        self.manager._save()
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_is_due_now_past(self):
        """Reminder in the past should be due now."""
        now = datetime.now(self.tz)
        past = now - timedelta(hours=1)
        reminder = self.manager.add(title="Past", due=past.isoformat())
        self.assertTrue(self.manager.is_due_now(reminder, now))
    
    def test_is_due_now_future(self):
        """Reminder in the future should NOT be due now."""
        now = datetime.now(self.tz)
        future = now + timedelta(hours=1)
        reminder = self.manager.add(title="Future", due=future.isoformat())
        self.assertFalse(self.manager.is_due_now(reminder, now))
    
    def test_done_not_due(self):
        """Completed reminders should not be due."""
        now = datetime.now(self.tz)
        past = now - timedelta(hours=1)
        reminder = self.manager.add(title="Completed", due=past.isoformat())
        self.manager.complete(reminder.id)
        reminder = self.manager.get(reminder.id)
        self.assertFalse(self.manager.is_due_now(reminder, now))


class TestDefaultReminder(unittest.TestCase):
    """Test that default Weekly Review reminder is created."""
    
    def test_default_weekly_review_created(self):
        """On first run, Weekly Review should be auto-created."""
        temp_dir = tempfile.mkdtemp()
        try:
            manager = RemindersManager(Path(temp_dir))
            manager._load()
            
            weekly_review = None
            for r in manager._items.values():
                if "weekly review" in r.title.lower():
                    weekly_review = r
                    break
            
            self.assertIsNotNone(weekly_review)
            self.assertTrue(weekly_review.pinned)
            self.assertTrue(weekly_review.is_recurring)
            self.assertTrue(weekly_review.has_window)
            self.assertEqual(weekly_review.repeat.type, "weekly")
            self.assertIn("SU", weekly_review.repeat.by_day)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
