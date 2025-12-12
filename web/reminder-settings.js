/* ============================================================================
   NovaOS Reminder Settings UI — v2.0.0
   ============================================================================
   
   Settings panel for configuring reminder notifications.
   Can be opened via #reminders-settings command or settings button.
   
   Add this to your index.html after reminder-notifications.js
   ============================================================================ */

const ReminderSettingsUI = {
  isOpen: false,
  settings: {},
  
  // Initialize
  init() {
    this.createStyles();
    console.log('[ReminderSettings] UI initialized');
  },
  
  // Create CSS
  createStyles() {
    if (document.getElementById('reminder-settings-styles')) return;
    
    const styles = document.createElement('style');
    styles.id = 'reminder-settings-styles';
    styles.textContent = `
      /* Settings overlay */
      .reminder-settings-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        z-index: 10001;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: fadeIn 0.2s ease-out;
      }
      
      @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
      }
      
      /* Settings panel */
      .reminder-settings-panel {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #00d4ff;
        border-radius: 12px;
        padding: 24px;
        width: 90%;
        max-width: 500px;
        max-height: 80vh;
        overflow-y: auto;
        box-shadow: 0 8px 32px rgba(0, 212, 255, 0.3);
      }
      
      .reminder-settings-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 20px;
        padding-bottom: 16px;
        border-bottom: 1px solid #333;
      }
      
      .reminder-settings-title {
        font-size: 20px;
        font-weight: 600;
        color: #00d4ff;
        margin: 0;
      }
      
      .reminder-settings-close {
        background: none;
        border: none;
        color: #666;
        font-size: 24px;
        cursor: pointer;
        padding: 4px;
        line-height: 1;
      }
      
      .reminder-settings-close:hover {
        color: #fff;
      }
      
      /* Section */
      .settings-section {
        margin-bottom: 24px;
      }
      
      .settings-section-title {
        font-size: 14px;
        font-weight: 600;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 12px;
      }
      
      /* Form row */
      .settings-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 0;
        border-bottom: 1px solid #222;
      }
      
      .settings-row:last-child {
        border-bottom: none;
      }
      
      .settings-label {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      
      .settings-label-text {
        font-size: 15px;
        color: #fff;
      }
      
      .settings-label-hint {
        font-size: 12px;
        color: #666;
      }
      
      /* Toggle switch */
      .settings-toggle {
        position: relative;
        width: 48px;
        height: 26px;
        background: #333;
        border-radius: 13px;
        cursor: pointer;
        transition: background 0.2s;
      }
      
      .settings-toggle.active {
        background: #00d4ff;
      }
      
      .settings-toggle::after {
        content: '';
        position: absolute;
        top: 3px;
        left: 3px;
        width: 20px;
        height: 20px;
        background: #fff;
        border-radius: 50%;
        transition: transform 0.2s;
      }
      
      .settings-toggle.active::after {
        transform: translateX(22px);
      }
      
      /* Text input */
      .settings-input {
        background: #0a0a14;
        border: 1px solid #333;
        border-radius: 6px;
        padding: 8px 12px;
        color: #fff;
        font-size: 14px;
        width: 200px;
      }
      
      .settings-input:focus {
        outline: none;
        border-color: #00d4ff;
      }
      
      .settings-input::placeholder {
        color: #555;
      }
      
      /* Select */
      .settings-select {
        background: #0a0a14;
        border: 1px solid #333;
        border-radius: 6px;
        padding: 8px 12px;
        color: #fff;
        font-size: 14px;
        cursor: pointer;
      }
      
      .settings-select:focus {
        outline: none;
        border-color: #00d4ff;
      }
      
      /* Buttons */
      .settings-actions {
        display: flex;
        gap: 12px;
        margin-top: 24px;
        padding-top: 16px;
        border-top: 1px solid #333;
      }
      
      .settings-btn {
        flex: 1;
        padding: 12px 16px;
        border: none;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
      }
      
      .settings-btn-primary {
        background: #00d4ff;
        color: #000;
      }
      
      .settings-btn-primary:hover {
        background: #00b8e6;
      }
      
      .settings-btn-secondary {
        background: #333;
        color: #fff;
      }
      
      .settings-btn-secondary:hover {
        background: #444;
      }
      
      .settings-btn-test {
        background: #2a2a4a;
        color: #00d4ff;
        border: 1px solid #00d4ff;
      }
      
      .settings-btn-test:hover {
        background: #3a3a5a;
      }
      
      /* Status message */
      .settings-status {
        padding: 12px;
        border-radius: 6px;
        margin-top: 16px;
        font-size: 14px;
      }
      
      .settings-status.success {
        background: rgba(0, 212, 255, 0.1);
        border: 1px solid #00d4ff;
        color: #00d4ff;
      }
      
      .settings-status.error {
        background: rgba(255, 71, 87, 0.1);
        border: 1px solid #ff4757;
        color: #ff4757;
      }
    `;
    document.head.appendChild(styles);
  },
  
  // Open settings panel
  async open() {
    if (this.isOpen) return;
    this.isOpen = true;
    
    // Load current settings
    try {
      const response = await fetch('/api/reminders/settings');
      const data = await response.json();
      if (data.ok) {
        this.settings = data.settings;
      }
    } catch (err) {
      console.error('[ReminderSettings] Load error:', err);
      this.settings = {};
    }
    
    this.render();
  },
  
  // Close settings panel
  close() {
    const overlay = document.querySelector('.reminder-settings-overlay');
    if (overlay) {
      overlay.remove();
    }
    this.isOpen = false;
  },
  
  // Render the settings panel
  render() {
    // Remove existing
    this.close();
    this.isOpen = true;
    
    const overlay = document.createElement('div');
    overlay.className = 'reminder-settings-overlay';
    overlay.onclick = (e) => {
      if (e.target === overlay) this.close();
    };
    
    const s = this.settings;
    
    overlay.innerHTML = `
      <div class="reminder-settings-panel">
        <div class="reminder-settings-header">
          <h2 class="reminder-settings-title">⚙️ Reminder Settings</h2>
          <button class="reminder-settings-close">&times;</button>
        </div>
        
        <div class="settings-section">
          <div class="settings-section-title">Push Notifications (ntfy.sh)</div>
          
          <div class="settings-row">
            <div class="settings-label">
              <span class="settings-label-text">Enable Push Notifications</span>
              <span class="settings-label-hint">Send to your phone via ntfy.sh</span>
            </div>
            <div class="settings-toggle ${s.ntfy_enabled ? 'active' : ''}" data-setting="ntfy_enabled"></div>
          </div>
          
          <div class="settings-row">
            <div class="settings-label">
              <span class="settings-label-text">Topic Name</span>
              <span class="settings-label-hint">Subscribe to this in ntfy app</span>
            </div>
            <input type="text" class="settings-input" data-setting="ntfy_topic" 
                   placeholder="novaos-your-name" value="${s.ntfy_topic || ''}">
          </div>
          
          <div class="settings-row">
            <div class="settings-label">
              <span class="settings-label-text">Priority</span>
              <span class="settings-label-hint">Notification urgency level</span>
            </div>
            <select class="settings-select" data-setting="ntfy_priority">
              <option value="low" ${s.ntfy_priority === 'low' ? 'selected' : ''}>Low</option>
              <option value="default" ${s.ntfy_priority === 'default' ? 'selected' : ''}>Default</option>
              <option value="high" ${s.ntfy_priority === 'high' ? 'selected' : ''}>High</option>
              <option value="urgent" ${s.ntfy_priority === 'urgent' ? 'selected' : ''}>Urgent</option>
            </select>
          </div>
          
          <button class="settings-btn settings-btn-test" id="test-ntfy-btn">
            📤 Send Test Notification
          </button>
        </div>
        
        <div class="settings-section">
          <div class="settings-section-title">In-App Notifications</div>
          
          <div class="settings-row">
            <div class="settings-label">
              <span class="settings-label-text">Show In-App Popups</span>
              <span class="settings-label-hint">Toast notifications when using NovaOS</span>
            </div>
            <div class="settings-toggle ${s.inapp_enabled !== false ? 'active' : ''}" data-setting="inapp_enabled"></div>
          </div>
        </div>
        
        <div class="settings-section">
          <div class="settings-section-title">Service Settings</div>
          
          <div class="settings-row">
            <div class="settings-label">
              <span class="settings-label-text">Check Interval</span>
              <span class="settings-label-hint">How often to check for due reminders</span>
            </div>
            <select class="settings-select" data-setting="check_interval">
              <option value="30" ${s.check_interval == 30 ? 'selected' : ''}>30 seconds</option>
              <option value="60" ${s.check_interval == 60 ? 'selected' : ''}>1 minute</option>
              <option value="120" ${s.check_interval == 120 ? 'selected' : ''}>2 minutes</option>
              <option value="300" ${s.check_interval == 300 ? 'selected' : ''}>5 minutes</option>
            </select>
          </div>
        </div>
        
        <div class="settings-status" style="display: none;"></div>
        
        <div class="settings-actions">
          <button class="settings-btn settings-btn-secondary" id="settings-cancel-btn">Cancel</button>
          <button class="settings-btn settings-btn-primary" id="settings-save-btn">Save Settings</button>
        </div>
      </div>
    `;
    
    document.body.appendChild(overlay);
    
    // Event handlers
    overlay.querySelector('.reminder-settings-close').onclick = () => this.close();
    overlay.querySelector('#settings-cancel-btn').onclick = () => this.close();
    overlay.querySelector('#settings-save-btn').onclick = () => this.save();
    overlay.querySelector('#test-ntfy-btn').onclick = () => this.testNtfy();
    
    // Toggle handlers
    overlay.querySelectorAll('.settings-toggle').forEach(toggle => {
      toggle.onclick = () => {
        toggle.classList.toggle('active');
      };
    });
  },
  
  // Collect values from form
  collectValues() {
    const values = {};
    
    // Toggles
    document.querySelectorAll('.settings-toggle').forEach(toggle => {
      const key = toggle.dataset.setting;
      values[key] = toggle.classList.contains('active');
    });
    
    // Inputs
    document.querySelectorAll('.settings-input').forEach(input => {
      const key = input.dataset.setting;
      values[key] = input.value.trim();
    });
    
    // Selects
    document.querySelectorAll('.settings-select').forEach(select => {
      const key = select.dataset.setting;
      let value = select.value;
      // Convert numeric values
      if (key === 'check_interval') {
        value = parseInt(value, 10);
      }
      values[key] = value;
    });
    
    return values;
  },
  
  // Show status message
  showStatus(message, isError = false) {
    const status = document.querySelector('.settings-status');
    if (status) {
      status.textContent = message;
      status.className = `settings-status ${isError ? 'error' : 'success'}`;
      status.style.display = 'block';
      
      setTimeout(() => {
        status.style.display = 'none';
      }, 3000);
    }
  },
  
  // Save settings
  async save() {
    const values = this.collectValues();
    
    try {
      const response = await fetch('/api/reminders/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      
      const data = await response.json();
      
      if (data.ok) {
        this.showStatus('✓ Settings saved!');
        this.settings = data.settings;
        
        // Close after brief delay
        setTimeout(() => this.close(), 1500);
      } else {
        this.showStatus(data.error || 'Failed to save', true);
      }
    } catch (err) {
      this.showStatus('Network error: ' + err.message, true);
    }
  },
  
  // Test ntfy notification
  async testNtfy() {
    // First save current values
    const values = this.collectValues();
    
    if (!values.ntfy_enabled) {
      this.showStatus('Enable push notifications first', true);
      return;
    }
    
    if (!values.ntfy_topic) {
      this.showStatus('Enter a topic name first', true);
      return;
    }
    
    // Save settings first
    try {
      await fetch('/api/reminders/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
    } catch (err) {
      // Continue anyway
    }
    
    // Send test
    try {
      const response = await fetch('/api/reminders/settings/test-ntfy', {
        method: 'POST',
      });
      
      const data = await response.json();
      
      if (data.ok) {
        this.showStatus('✓ Test notification sent! Check your phone.');
      } else {
        this.showStatus(data.error || 'Test failed', true);
      }
    } catch (err) {
      this.showStatus('Network error: ' + err.message, true);
    }
  },
};

// Initialize
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => ReminderSettingsUI.init());
} else {
  ReminderSettingsUI.init();
}

// Export
window.ReminderSettingsUI = ReminderSettingsUI;

// Also expose a simple function to open settings
window.openReminderSettings = () => ReminderSettingsUI.open();
