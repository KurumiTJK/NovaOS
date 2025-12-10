// web/sse-client.js
/**
 * NovaOS SSE Client — v0.10.3
 * 
 * Handles Server-Sent Events for long-running operations like #quest-compose.
 * 
 * v0.10.3 Changes:
 * - Added QuestCompose wizard streaming support (wizard_log, wizard_update, wizard_complete, wizard_error)
 * - Safe /nova calls with callNovaOnce() helper
 * - Never blindly calls response.json() — always validates first
 * 
 * Usage:
 *   // For QuestCompose "generate" action at Step 3:
 *   sendQuestComposeGenerate(sessionId, {
 *     onLog: (msg) => appendLog(msg),
 *     onProgress: (msg, pct) => updateProgressBar(pct, msg),
 *     onUpdate: (content) => showPreview(content),
 *     onComplete: (result) => handleGeneratedSteps(result),
 *     onError: (err) => showError(err),
 *   });
 * 
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

// =============================================================================
// v0.10.3: QUEST COMPOSE WIZARD STREAMING
// =============================================================================

/**
 * Send a QuestCompose "generate" command via SSE streaming.
 * 
 * This is specifically for Step 3 of the QuestCompose wizard when the user
 * types "generate" to auto-generate quest steps.
 * 
 * @param {string} sessionId - Session ID
 * @param {Object} callbacks - Event callbacks
 * @param {Function} callbacks.onLog - Called with log messages from QuestCompose
 * @param {Function} callbacks.onProgress - Called with (message, percent)
 * @param {Function} callbacks.onUpdate - Called with partial content previews
 * @param {Function} callbacks.onComplete - Called with final result { ok, text, steps_count, ... }
 * @param {Function} callbacks.onError - Called with error message
 */
async function sendQuestComposeGenerate(sessionId, callbacks = {}) {
  const { onLog, onProgress, onUpdate, onComplete, onError } = callbacks;
  
  console.log('[NovaOS SSE] Starting QuestCompose streaming generation');
  
  try {
    const response = await fetch('/nova/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        text: 'generate', 
        session_id: sessionId,
        stream_mode: 'quest_compose',  // v0.10.3: Signal this is a wizard generate action
      }),
    });
    
    // v0.10.3: Check response status before reading stream
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
      if (done) {
        console.log('[NovaOS SSE] Stream complete');
        break;
      }
      
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
              // === v0.10.3: QuestCompose Wizard Events ===
              case 'wizard_log':
                console.log('[NovaOS SSE] wizard_log:', parsed.message);
                onLog?.(parsed.message);
                break;
                
              case 'wizard_update':
                console.log('[NovaOS SSE] wizard_update:', parsed.content?.slice(0, 50));
                onUpdate?.(parsed.content);
                break;
                
              case 'wizard_complete':
                console.log('[NovaOS SSE] wizard_complete:', parsed.result);
                onComplete?.(parsed.result);
                break;
                
              case 'wizard_error':
                console.error('[NovaOS SSE] wizard_error:', parsed.message);
                onError?.(parsed.message || parsed.error || 'Unknown wizard error');
                break;
              
              // === Standard Events ===
              case 'progress':
                onProgress?.(parsed.message, parsed.percent);
                break;
                
              case 'chunk':
                onUpdate?.(parsed.text || parsed);
                break;
                
              case 'complete':
                onComplete?.(parsed);
                break;
                
              case 'error':
                onError?.(parsed.error || parsed.message || 'Unknown error');
                break;
                
              default:
                console.log('[NovaOS SSE] Unknown event:', currentEvent, parsed);
            }
          } catch (e) {
            // Non-JSON data, treat as log
            console.log('[NovaOS SSE] Non-JSON data:', data);
            onLog?.(data);
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


// =============================================================================
// SAFE /nova CALL HELPER
// =============================================================================

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
    if (res.status === 502 || res.status === 504 || res.status === 524) {
      userMessage = "The server may be overloaded or timed out. Please try again.";
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


// =============================================================================
// GENERIC STREAMING COMMAND
// =============================================================================

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
              // v0.10.3: Handle wizard events in generic streaming too
              case 'wizard_log':
                onChunk?.(parsed.message);
                break;
              case 'wizard_complete':
                onComplete?.(parsed.result || parsed);
                break;
              case 'wizard_error':
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


// =============================================================================
// SMART COMMAND SENDER
// =============================================================================

/**
 * Smart command sender - uses streaming for long operations, regular POST otherwise.
 * 
 * v0.10.3: Updated to use callNovaOnce() for safe /nova calls.
 * 
 * @param {string} text - Command text
 * @param {string} sessionId - Session ID
 * @param {Function} onResult - Callback with result
 * @param {Object} options - Options
 * @param {Function} options.onProgress - Progress callback for streaming commands
 * @param {Function} options.onLog - Log callback for QuestCompose streaming
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
    // v0.10.3: Use callNovaOnce() for safe /nova calls
    const result = await callNovaOnce({ text, session_id: sessionId });
    onResult(result);
  }
}


// =============================================================================
// EXPORTS
// =============================================================================

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { 
    sendStreamingCommand, 
    sendCommand, 
    callNovaOnce,
    sendQuestComposeGenerate,  // v0.10.3
  };
}
