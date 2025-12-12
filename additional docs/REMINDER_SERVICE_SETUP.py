# Reminder Service Integration Guide
# ==================================
#
# This file shows how to integrate the ReminderService into your NovaOS app.

# =============================================================================
# STEP 1: Add to app.py (Flask app)
# =============================================================================

"""
In your app.py, add these imports at the top:

    from kernel.reminder_service import init_reminder_service, stop_reminder_service

Then after you create the kernel, initialize the service:

    # Initialize reminder service with your preferred notification method
    reminder_config = {
        # Check every 60 seconds
        "check_interval": 60,
        
        # Console notifications (for debugging, set False in production)
        "console_notifications": True,
        
        # === OPTION A: ntfy.sh (RECOMMENDED - easiest) ===
        # Free push notifications to your phone/desktop
        # 1. Install ntfy app on your phone (iOS/Android)
        # 2. Subscribe to your topic (e.g., "novaos-vant-reminders")
        # 3. Set the topic here:
        "ntfy_topic": "novaos-vant-reminders",  # Change this!
        "ntfy_server": "https://ntfy.sh",  # Or self-host
        "ntfy_priority": "default",  # low, default, high, urgent
        
        # === OPTION B: Webhook (for custom integrations) ===
        # "webhook_url": "https://your-server.com/webhook/reminder",
        # "webhook_method": "POST",
        
        # === OPTION C: Email (requires SMTP) ===
        # "smtp_host": "smtp.gmail.com",
        # "smtp_port": 587,
        # "smtp_username": "your-email@gmail.com",
        # "smtp_password": "your-app-password",  # Use app password, not real password!
        # "email_from": "your-email@gmail.com",
        # "email_to": "your-email@gmail.com",
        # "smtp_use_tls": True,
    }
    
    init_reminder_service(
        reminders_manager=kernel.reminders,
        config=reminder_config,
        data_dir=kernel.config.data_dir,
        auto_start=True,
    )

Then add a shutdown handler:

    import atexit
    atexit.register(stop_reminder_service)

Or if using Flask's teardown:

    @app.teardown_appcontext
    def shutdown_services(exception=None):
        stop_reminder_service()
"""

# =============================================================================
# STEP 2: Example app.py integration
# =============================================================================

EXAMPLE_APP_PY = '''
# In app.py, after kernel initialization:

from kernel.reminder_service import init_reminder_service, stop_reminder_service
import atexit

# ... (kernel creation code) ...

# Start reminder service
reminder_service = init_reminder_service(
    reminders_manager=kernel.reminders,
    config={
        "check_interval": 60,
        "console_notifications": True,
        "ntfy_topic": "novaos-vant-reminders",  # Subscribe to this in ntfy app!
    },
    data_dir=kernel.config.data_dir,
)

# Ensure clean shutdown
atexit.register(stop_reminder_service)

# Optional: Add status endpoint
@app.route("/reminder-status")
def reminder_status():
    from kernel.reminder_service import get_reminder_service
    service = get_reminder_service()
    if service:
        return jsonify(service.get_status())
    return jsonify({"error": "Service not running"})
'''

# =============================================================================
# STEP 3: Setting up ntfy.sh (easiest option)
# =============================================================================

NTFY_SETUP = '''
ntfy.sh Setup (5 minutes)
=========================

1. Install the ntfy app on your phone:
   - iOS: https://apps.apple.com/app/ntfy/id1625396347
   - Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy

2. Open the app and subscribe to a topic:
   - Tap the + button
   - Enter your topic name (e.g., "novaos-vant-reminders")
   - This is like a private channel - use a unique name!

3. Set the same topic in your reminder_config:
   "ntfy_topic": "novaos-vant-reminders"

4. Test it by creating a reminder:
   #reminders-add title="Test notification" due="1m"

5. Wait 1 minute - you should get a push notification!

Tips:
- Topics are public but obscure - use a unique name
- For extra security, self-host ntfy: https://github.com/binwiederhier/ntfy
- Priority levels: low, default, high, urgent (affects notification sound)
'''

# =============================================================================
# STEP 4: Self-hosted ntfy (optional, more secure)
# =============================================================================

NTFY_SELFHOST = '''
Self-hosted ntfy (Docker)
=========================

docker run -d \\
  --name ntfy \\
  -p 8080:80 \\
  -v /var/cache/ntfy:/var/cache/ntfy \\
  -v /etc/ntfy:/etc/ntfy \\
  binwiederhier/ntfy serve

Then update your config:
    "ntfy_server": "http://your-server:8080",
    "ntfy_topic": "novaos-reminders",
'''

if __name__ == "__main__":
    print("This is a documentation file. See the comments for integration instructions.")
    print("\n" + NTFY_SETUP)
