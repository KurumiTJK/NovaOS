// web/sse-client.js
/**
 * NovaOS SSE Client — v0.10.2
 * 
 * Handles Server-Sent Events for long-running operations like #quest-compose.
 * 
 * v0.10.2 Changes:
 * - Added callNovaOnce() helper for safe /nova calls
 * - Never blindly calls response.json() — always validates first
 * - Checks response.ok, Content-Type, and wraps json() in try/catch
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
 * Safely call the /nova endpoint once with comprehensive error handling.
 * 
 * v0.10.2: This helper ensures we NEVER call response.json() on:
 * - Network errors (fetch throws)
 * - Non-2xx HTTP responses (which may be HTML error pages)
 * - Non-JSON content types (e.g., HTML from nginx/Cloudflare)
 * - Malformed JSON responses
 * 
 * @param {Object} payload - The request payload { text: "...", session_id: "..." }
 * @returns {Object} - Always returns an object with { ok, error?, message?, ... }
 */
async function callNovaOnce(payload) {
  let res;
  
  // Step 1: Try to fetch — catch network errors
  try {
    res = await fetch('/nova', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    // Network error (offline, DNS failure, CORS, etc.)
    console.error('[NovaOS SSE] Network error calling /nova:', err);
    return { 
      ok: false, 
      error: 'network', 
      message: `Network error calling Nova: ${err.message}`,
      text: "Nova couldn't reach the server. Please check your connection.",
    };
  }

  // Step 2: Check HTTP status — non-2xx means error (possibly HTML page)
  if (!res.ok) {
    let errorText = '';
    try {
      errorText = await res.text();
    } catch (e) {
      errorText = '(unable to read response body)';
    }
    
    console.error('[NovaOS SSE] Server error from /nova:', res.status, errorText.slice(0, 500));
    
    // Try to parse as JSON in case backend sent a JSON error envelope
    try {
      const errorJson = JSON.parse(errorText);
      // Return the backend's error response as-is
      return {
        ok: false,
        error: errorJson.error || 'server',
        message: errorJson.message || `Server error (HTTP ${res.status})`,
        text: errorJson.text || errorJson.message || `Server error (HTTP ${res.status})`,
        ...errorJson,
      };
    } catch (e) {
      // Not JSON — probably HTML error page
    }
    
    // Provide user-friendly message based on status code
    let userMessage = `Server error (HTTP ${res.status}) from /nova.`;
    if (res.status === 502 || res.status === 504) {
      userMessage = "The server may be overloaded or restarting. Please try again.";
    } else if (res.status === 503) {
      userMessage = "The service is temporarily unavailable. Please try again later.";
    }
    
    return { 
      ok: false, 
      error: 'server', 
      message: userMessage,
      text: userMessage,
      status: res.status,
    };
  }

  // Step 3: Validate Content-Type is JSON
  const contentType = (res.headers.get('content-type') || '').toLowerCase();
  if (!contentType.includes('application/json')) {
    let bodyText = '';
    try {
      bodyText = await res.text();
    } catch (e) {
      bodyText = '(unable to read response body)';
    }
    
    console.error('[NovaOS SSE] Non-JSON response from /nova. Content-Type:', contentType);
    console.error('[NovaOS SSE] Response body preview:', bodyText.slice(0, 500));
    
    return { 
      ok: false, 
      error: 'non_json', 
      message: 'Non-JSON response from /nova. The server may have returned an error page.',
      text: "Nova received a non-JSON response. Please check the server logs.",
    };
  }

  // Step 4: Parse JSON — catch malformed JSON
  try {
    const data = await res.json();
    
    // Ensure the response has an 'ok' field for consistency
    if (data.ok === undefined) {
      data.ok = true;  // Assume success if not specified
    }
    
    return data;
  } catch (err) {
    console.error('[NovaOS SSE] JSON parse error from /nova:', err);
    return { 
      ok: false, 
      error: 'json_parse', 
      message: 'Malformed JSON from /nova.',
      text: "Nova received a malformed response. Please try again.",
    };
  }
}

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
    
    // v0.10.2: Check response status before reading stream
    if (!response.ok) {
      let errText = '';
      try {
        errText = await response.text();
        // Try to parse as JSON error
        const errJson = JSON.parse(errText);
        onError?.(errJson.message || errJson.error || `Server error (HTTP ${response.status})`);
      } catch (e) {
        onError?.(`Server error (HTTP ${response.status}): ${errText.slice(0, 200)}`);
      }
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
                onError?.(parsed.message || parsed.error || 'Unknown error');
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
    console.error('[NovaOS SSE] Streaming error:', error);
    onError?.(error.message || 'Connection failed');
  }
}

/**
 * Smart command sender - uses streaming for long operations, regular POST otherwise.
 * 
 * v0.10.2: Updated to use callNovaOnce() for safe /nova calls.
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
      onError: (err) => onResult({ 
        ok: false, 
        error: err, 
        text: `Error: ${err}`,
        message: err,
      }),
    });
  } else {
    // v0.10.2: Use callNovaOnce() for safe /nova calls
    const result = await callNovaOnce({ text, session_id: sessionId });
    onResult(result);
  }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { sendStreamingCommand, sendCommand, callNovaOnce };
}
