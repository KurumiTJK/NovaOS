/* ============================================================================
   NovaOS Reminder Notifications — Frontend Component
   ============================================================================
   
   Add this to your index.html or as a separate JS file.
   
   Features:
   - Polls /api/reminders/due every 30 seconds
   - Shows toast notifications for due reminders
   - Quick actions: Done, Snooze, Dismiss
   - Non-intrusive but attention-getting
   ============================================================================ */

// =============================================================================
// REMINDER NOTIFICATION SYSTEM
// =============================================================================

const ReminderNotifications = {
  pollInterval: 30000,  // 30 seconds
  pollTimer: null,
  activeNotifications: new Map(),  // id -> notification element
  
  // Initialize the system
  init() {
    this.createStyles();
    this.createContainer();
    this.startPolling();
    console.log('[Reminders] Notification system initialized');
  },
  
  // Create CSS styles
  createStyles() {
    if (document.getElementById('reminder-notification-styles')) return;
    
    const styles = document.createElement('style');
    styles.id = 'reminder-notification-styles';
    styles.textContent = `
      /* Reminder notification container */
      #reminder-notifications {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 10000;
        display: flex;
        flex-direction: column;
        gap: 10px;
        max-width: 380px;
        pointer-events: none;
      }
      
      /* Individual notification */
      .reminder-notification {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #00d4ff;
        border-left: 4px solid #00d4ff;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 4px 20px rgba(0, 212, 255, 0.3);
        animation: slideIn 0.3s ease-out;
        pointer-events: auto;
      }
      
      .reminder-notification.priority-high {
        border-left-color: #ff4757;
        box-shadow: 0 4px 20px rgba(255, 71, 87, 0.3);
      }
      
      .reminder-notification.priority-high .reminder-icon {
        color: #ff4757;
      }
      
      @keyframes slideIn {
        from {
          transform: translateX(100%);
          opacity: 0;
        }
        to {
          transform: translateX(0);
          opacity: 1;
        }
      }
      
      @keyframes slideOut {
        from {
          transform: translateX(0);
          opacity: 1;
        }
        to {
          transform: translateX(100%);
          opacity: 0;
        }
      }
      
      .reminder-notification.dismissing {
        animation: slideOut 0.3s ease-in forwards;
      }
      
      /* Header row */
      .reminder-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
      }
      
      .reminder-icon {
        font-size: 24px;
        color: #00d4ff;
      }
      
      .reminder-title {
        flex: 1;
        font-size: 16px;
        font-weight: 600;
        color: #fff;
        margin: 0;
      }
      
      .reminder-dismiss {
        background: none;
        border: none;
        color: #666;
        cursor: pointer;
        font-size: 18px;
        padding: 4px;
        line-height: 1;
        transition: color 0.2s;
      }
      
      .reminder-dismiss:hover {
        color: #fff;
      }
      
      /* Meta info */
      .reminder-meta {
        font-size: 13px;
        color: #888;
        margin-bottom: 12px;
      }
      
      .reminder-meta span {
        margin-right: 12px;
      }
      
      .reminder-recurring {
        color: #00d4ff;
      }
      
      /* Notes */
      .reminder-notes {
        font-size: 14px;
        color: #aaa;
        margin-bottom: 12px;
        font-style: italic;
      }
      
      /* Action buttons */
      .reminder-actions {
        display: flex;
        gap: 8px;
      }
      
      .reminder-btn {
        flex: 1;
        padding: 8px 12px;
        border: none;
        border-radius: 4px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
      }
      
      .reminder-btn-done {
        background: #00d4ff;
        color: #000;
      }
      
      .reminder-btn-done:hover {
        background: #00b8e6;
      }
      
      .reminder-btn-snooze {
        background: #333;
        color: #fff;
      }
      
      .reminder-btn-snooze:hover {
        background: #444;
      }
      
      /* Snooze dropdown */
      .snooze-dropdown {
        position: relative;
        flex: 1;
      }
      
      .snooze-options {
        display: none;
        position: absolute;
        bottom: 100%;
        left: 0;
        right: 0;
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 4px;
        margin-bottom: 4px;
        overflow: hidden;
      }
      
      .snooze-dropdown:hover .snooze-options,
      .snooze-dropdown:focus-within .snooze-options {
        display: block;
      }
      
      .snooze-option {
        display: block;
        width: 100%;
        padding: 8px 12px;
        border: none;
        background: none;
        color: #fff;
        text-align: left;
        cursor: pointer;
        font-size: 13px;
      }
      
      .snooze-option:hover {
        background: #333;
      }
      
      /* Badge for notification count */
      .reminder-badge {
        position: fixed;
        top: 10px;
        right: 10px;
        background: #ff4757;
        color: #fff;
        font-size: 12px;
        font-weight: bold;
        padding: 4px 8px;
        border-radius: 12px;
        z-index: 9999;
        display: none;
      }
      
      .reminder-badge.visible {
        display: block;
      }
    `;
    document.head.appendChild(styles);
  },
  
  // Create container for notifications
  createContainer() {
    if (document.getElementById('reminder-notifications')) return;
    
    const container = document.createElement('div');
    container.id = 'reminder-notifications';
    document.body.appendChild(container);
  },
  
  // Start polling for due reminders
  startPolling() {
    // Check immediately
    this.checkDueReminders();
    
    // Then poll every 30 seconds
    this.pollTimer = setInterval(() => {
      this.checkDueReminders();
    }, this.pollInterval);
  },
  
  // Stop polling
  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  },
  
  // Check for due reminders
  async checkDueReminders() {
    try {
      const response = await fetch('/api/reminders/due');
      if (!response.ok) return;
      
      const data = await response.json();
      
      if (data.has_due && data.reminders) {
        data.reminders.forEach(reminder => {
          if (!this.activeNotifications.has(reminder.id)) {
            this.showNotification(reminder);
          }
        });
      }
    } catch (err) {
      console.error('[Reminders] Poll error:', err);
    }
  },
  
  // Show a notification
  showNotification(reminder) {
    const container = document.getElementById('reminder-notifications');
    if (!container) return;
    
    const el = document.createElement('div');
    el.className = `reminder-notification${reminder.priority === 'high' ? ' priority-high' : ''}`;
    el.dataset.id = reminder.id;
    
    el.innerHTML = `
      <div class="reminder-header">
        <span class="reminder-icon">⏰</span>
        <h4 class="reminder-title">${this.escapeHtml(reminder.title)}</h4>
        <button class="reminder-dismiss" title="Dismiss">&times;</button>
      </div>
      <div class="reminder-meta">
        <span>📅 ${reminder.due_at}</span>
        ${reminder.is_recurring ? '<span class="reminder-recurring">🔄 Recurring</span>' : ''}
        ${reminder.is_pinned ? '<span>📌 Pinned</span>' : ''}
      </div>
      ${reminder.notes ? `<div class="reminder-notes">${this.escapeHtml(reminder.notes)}</div>` : ''}
      <div class="reminder-actions">
        <button class="reminder-btn reminder-btn-done">✓ Done</button>
        <div class="snooze-dropdown">
          <button class="reminder-btn reminder-btn-snooze">💤 Snooze</button>
          <div class="snooze-options">
            <button class="snooze-option" data-duration="10m">10 minutes</button>
            <button class="snooze-option" data-duration="30m">30 minutes</button>
            <button class="snooze-option" data-duration="1h">1 hour</button>
            <button class="snooze-option" data-duration="3h">3 hours</button>
            <button class="snooze-option" data-duration="1d">Tomorrow</button>
          </div>
        </div>
      </div>
    `;
    
    // Event handlers
    el.querySelector('.reminder-dismiss').onclick = () => this.dismiss(reminder.id);
    el.querySelector('.reminder-btn-done').onclick = () => this.markDone(reminder.id);
    el.querySelectorAll('.snooze-option').forEach(btn => {
      btn.onclick = () => this.snooze(reminder.id, btn.dataset.duration);
    });
    
    container.appendChild(el);
    this.activeNotifications.set(reminder.id, el);
    
    // Play notification sound (optional)
    this.playSound();
  },
  
  // Remove notification with animation
  removeNotification(id) {
    const el = this.activeNotifications.get(id);
    if (el) {
      el.classList.add('dismissing');
      setTimeout(() => {
        el.remove();
        this.activeNotifications.delete(id);
      }, 300);
    }
  },
  
  // Dismiss (hide but don't mark done)
  async dismiss(id) {
    try {
      await fetch(`/api/reminders/dismiss/${id}`, { method: 'POST' });
      this.removeNotification(id);
    } catch (err) {
      console.error('[Reminders] Dismiss error:', err);
    }
  },
  
  // Mark done
  async markDone(id) {
    try {
      const response = await fetch(`/api/reminders/done/${id}`, { method: 'POST' });
      const data = await response.json();
      
      if (data.ok) {
        this.removeNotification(id);
        // Show brief confirmation
        this.showToast(data.is_recurring ? '✓ Done! Next occurrence scheduled.' : '✓ Reminder completed!');
      }
    } catch (err) {
      console.error('[Reminders] Done error:', err);
    }
  },
  
  // Snooze
  async snooze(id, duration) {
    try {
      const response = await fetch(`/api/reminders/snooze/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration }),
      });
      const data = await response.json();
      
      if (data.ok) {
        this.removeNotification(id);
        this.showToast(`💤 Snoozed for ${duration}`);
      }
    } catch (err) {
      console.error('[Reminders] Snooze error:', err);
    }
  },
  
  // Show a brief toast message
  showToast(message) {
    const toast = document.createElement('div');
    toast.style.cssText = `
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: #1a1a2e;
      color: #fff;
      padding: 12px 24px;
      border-radius: 8px;
      border: 1px solid #00d4ff;
      z-index: 10001;
      animation: fadeIn 0.3s ease-out;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
      toast.style.animation = 'fadeOut 0.3s ease-in forwards';
      setTimeout(() => toast.remove(), 300);
    }, 2000);
  },
  
  // Play notification sound
  playSound() {
    // Optional: Add a notification sound
    // const audio = new Audio('/static/notification.mp3');
    // audio.volume = 0.3;
    // audio.play().catch(() => {});
  },
  
  // Utility: Escape HTML
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => ReminderNotifications.init());
} else {
  ReminderNotifications.init();
}

// Export for manual control
window.ReminderNotifications = ReminderNotifications;
