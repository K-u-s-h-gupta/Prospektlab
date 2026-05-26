export interface ChatRequest {
  message: string;
  response_depth?: 'chat' | 'standard' | 'deep';
}

export interface FinalResponse {
  type: 'final';
  reply: string;
  agents_used: string[];
  rich: any;
  output_mode: string;
  response_depth: string;
  elapsed_ms: number;
}

export interface AgentEventData {
  seq: number;
  type: string;
  timestamp: string;
  payload: {
    agent?: string;
    step?: string;
    details?: string;
    status?: 'active' | 'completed' | 'planned';
    [key: string]: any;
  };
}

export const API_BASE_URL = 'http://localhost:8080';

export async function sendChatRequest(req: ChatRequest): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: req.message,
      response_depth: req.response_depth || 'standard',
    }),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }

  return response.json();
}

export function streamChatRequest(
  req: ChatRequest,
  onEvent: (event: AgentEventData) => void,
  onFinal: (final: FinalResponse) => void,
  onError: (error: any) => void
): () => void {
  const controller = new AbortController();
  
  fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: req.message,
      response_depth: req.response_depth || 'standard',
    }),
    signal: controller.signal
  })
  .then(async (response) => {
    if (!response.ok) {
      throw new Error(`API stream error: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Readable stream not supported');
    }

    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let currentEvent = '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.substring(6).trim();
        } else if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.substring(5).trim();
          try {
            const parsed = JSON.parse(dataStr);
            if (currentEvent === 'agent_event') {
              onEvent({
                seq: parsed.seq || 0,
                type: parsed.type || '',
                timestamp: parsed.timestamp || '',
                payload: parsed.payload || {}
              });
            } else if (currentEvent === 'final') {
              onFinal(parsed as FinalResponse);
            } else if (currentEvent === 'error') {
              onError(new Error(parsed.message || 'Stream processing error'));
            }
          } catch (e) {
            console.error('Failed to parse stream segment', e);
          }
        }
      }
    }
  })
  .catch((err) => {
    if (err.name !== 'AbortError') {
      onError(err);
    }
  });

  return () => controller.abort();
}
