// web/js/sse-client.js
/**
 * NovaOS SSE Client — v0.10.1
 * 
 * Handles Server-Sent Events for long-running operations like #quest-compose.
 * 
 * Usage:
 *   // For streaming commands (like #quest-compose with big prompts)
 *   sendStreamingCommand("#quest-compose", sessionId, {
 *     onProgress: (msg, pct) => updateProgressBar(pct, msg),
 *     onChunk: (text) => appendToOutput(text),
 *     onComplete: (result) => handleResult(result),
 *     onError: (err) => showError(err),
 *   });
 * 
 *   // Or use the simple version that falls back to regular POST for non-streaming
 *   sendCommand(text, sessionId, onResult);
 */

/**
 * Send a command using SSE streaming.
 * 
 * @param {string} text - The command text (e.g., "#quest-compose")
 * @param {string} sessionId - Session ID
 * @param {Object} callbacks - Event callbacks
 * @param {Function} callbacks.onProgress - Called with (message, percent) 
 * @param {Function} callbacks.onChunk - Called with text chunks as they arrive
 * @param {Function} callbacks.onComplete - Called with final result object
 * @param {Function} callbacks.onError - Called with error message
 */
async function sendStreamingCommand(text, sessionId, callbacks = {}) {
  const { onProgress, onChunk, onComplete, onError } = callbacks;
  
  try {
    const response = await fetch('/nova/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, session_id: sessionId }),
    });
    
    if (!response.ok) {
      const err = await response.text();
      onError?.(err);
      return;
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      
      // Parse SSE events from buffer
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Keep incomplete line in buffer
      
      let currentEvent = null;
      
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const parsed = JSON.parse(data);
            
            switch (currentEvent) {
              case 'progress':
                onProgress?.(parsed.message, parsed.percent);
                break;
              case 'chunk':
                onChunk?.(parsed.text || parsed);
                break;
              case 'complete':
                onComplete?.(parsed);
                break;
              case 'error':
                onError?.(parsed.error || 'Unknown error');
                break;
            }
          } catch (e) {
            // Non-JSON data, treat as chunk
            onChunk?.(data);
          }
          currentEvent = null;
        }
      }
    }
  } catch (error) {
    onError?.(error.message || 'Connection failed');
  }
}

/**
 * Smart command sender - uses streaming for long operations, regular POST otherwise.
 * 
 * @param {string} text - Command text
 * @param {string} sessionId - Session ID
 * @param {Function} onResult - Callback with result
 * @param {Object} options - Options
 * @param {Function} options.onProgress - Progress callback for streaming commands
 */
async function sendCommand(text, sessionId, onResult, options = {}) {
  // Commands that benefit from streaming
  const streamingCommands = ['#quest-compose'];
  
  const shouldStream = streamingCommands.some(cmd => text.startsWith(cmd));
  
  if (shouldStream && options.onProgress) {
    // Use streaming
    await sendStreamingCommand(text, sessionId, {
      onProgress: options.onProgress,
      onComplete: onResult,
      onError: (err) => onResult({ ok: false, error: err, text: `Error: ${err}` }),
    });
  } else {
    // Regular POST
    try {
      const response = await fetch('/nova', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: sessionId }),
      });
      const result = await response.json();
      onResult(result);
    } catch (error) {
      onResult({ ok: false, error: error.message, text: `Error: ${error.message}` });
    }
  }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { sendStreamingCommand, sendCommand };
}
