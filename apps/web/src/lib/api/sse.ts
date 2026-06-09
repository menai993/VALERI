/**
 * SSE-over-POST reader (frontend-spec §6): the chat endpoint streams
 * `data: {json}\n\n` events; this helper parses them incrementally.
 */

export interface ChatSSEEvent {
  type: "tool_call" | "register" | "token" | "card" | "capture" | "done" | "error"
  [key: string]: unknown
}

export async function postSSE(
  url: string,
  body: unknown,
  onEvent: (event: ChatSSEEvent) => void,
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

  if (!response.ok || !response.body) {
    let message = response.statusText
    try {
      const envelope = (await response.json()) as { error?: { message?: string } }
      message = envelope.error?.message ?? message
    } catch {
      // keep statusText
    }
    onEvent({ type: "error", message })
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n")
    buffer = frames.pop() ?? ""
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith("data: ")) continue
      try {
        onEvent(JSON.parse(line.slice("data: ".length)) as ChatSSEEvent)
      } catch {
        // skip malformed frames
      }
    }
  }
}
