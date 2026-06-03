/**
 * Pitaj VALERI (frontend-spec §5): the chat screen — session list, thread, input.
 *
 * Messages stream over SSE (tool_call → register → token → card? → done); the
 * input stays disabled while a reply is streaming. Opened from the sidebar or
 * the GlobalSearch (?q= prefills and sends the question).
 */
import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { MessageSquarePlus, Send } from "lucide-react"
import { useSearchParams } from "react-router"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { CardSkeleton, EmptyState } from "@/components/widgets/CardState"
import { useChatHistory, useChatSessions, useCreateChatSession } from "@/lib/api/queries"
import { postSSE, type ChatSSEEvent } from "@/lib/api/sse"
import type { ChatToolCall, Register } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { ChatMessage, type ChatMessageProps } from "./ChatMessage"

export function ChatPage() {
  const t = useT()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const sessions = useChatSessions()
  const createSession = useCreateChatSession()

  const [activeSession, setActiveSession] = useState<number | null>(null)
  const history = useChatHistory(activeSession)

  // Live messages appended during this visit (on top of the persisted history).
  const [liveMessages, setLiveMessages] = useState<ChatMessageProps[]>([])
  // GlobalSearch handoff: /chat?q=... prefills the input (consumed once, lazily).
  const [input, setInput] = useState(() => searchParams.get("q") ?? "")
  const [streaming, setStreaming] = useState(false)
  const threadEndRef = useRef<HTMLDivElement>(null)

  // Clear the consumed ?q= from the URL (external-system sync only).
  useEffect(() => {
    if (searchParams.get("q")) {
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [liveMessages, history.data])

  async function ensureSession(): Promise<number> {
    if (activeSession !== null) return activeSession
    const created = await createSession.mutateAsync()
    setActiveSession(created.session_id)
    return created.session_id
  }

  async function send() {
    const text = input.trim()
    if (!text || streaming) return

    setInput("")
    setStreaming(true)
    setLiveMessages((previous) => [...previous, { role: "user", content: text }])

    // The assistant reply builds up from SSE events.
    let register: Register | null = null
    let replyText = ""
    let card: ChatMessageProps["card"] = null
    let toolCalls: ChatToolCall[] = []

    const sessionId = await ensureSession()
    await postSSE(`/api/chat/sessions/${sessionId}/messages`, { text }, (event: ChatSSEEvent) => {
      if (event.type === "register") register = event.register as Register
      if (event.type === "token") replyText += String(event.text ?? "")
      if (event.type === "card") {
        card = {
          card_type: String(event.card_type),
          payload: (event.payload ?? {}) as Record<string, unknown>,
        }
      }
      if (event.type === "done") {
        toolCalls = (event.tool_calls ?? []) as ChatToolCall[]
      }
      if (event.type === "error") {
        replyText = String(event.message ?? t.app.error)
      }
    })

    setLiveMessages((previous) => [
      ...previous,
      { role: "assistant", content: replyText, register, toolCalls, card, capture: true },
    ])
    setStreaming(false)
    // CI1: capture runs in the background server-side; refresh the review queue.
    queryClient.invalidateQueries({ queryKey: ["kb", "pending"] })
  }

  function openSession(sessionId: number) {
    setActiveSession(sessionId)
    setLiveMessages([])
  }

  function newSession() {
    setActiveSession(null)
    setLiveMessages([])
  }

  const persistedMessages: ChatMessageProps[] = (history.data?.messages ?? []).map((message) => ({
    role: message.role,
    content: message.content ?? "",
    register: message.register,
    toolCalls: message.tool_calls,
  }))

  const thread = [...persistedMessages, ...liveMessages]

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">
          {t.chat.title}
        </h1>
        <p className="text-sm text-text-2">{t.chat.subtitle}</p>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-12">
        {/* Session list */}
        <Card className="hidden flex-col gap-2 overflow-y-auto p-3 lg:col-span-3 lg:flex">
          <Button variant="default" size="sm" onClick={newSession} className="justify-start gap-2">
            <MessageSquarePlus className="h-4 w-4" />
            {t.chat.new_session}
          </Button>
          {sessions.isLoading && <CardSkeleton rows={4} />}
          {sessions.data?.items.map((session) => (
            <button
              key={session.id}
              type="button"
              onClick={() => openSession(session.id)}
              className={cn(
                "flex flex-col gap-0.5 rounded-md px-3 py-2 text-left text-sm transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                activeSession === session.id
                  ? "bg-primary-soft text-primary"
                  : "text-text-2 hover:bg-surface-2",
              )}
            >
              <span className="truncate font-medium">
                {session.title ?? t.chat.untitled}
              </span>
              <span className="text-[11.5px] text-text-3">{formatDate(session.started_at)}</span>
            </button>
          ))}
        </Card>

        {/* Thread + input */}
        <Card className="flex min-h-0 flex-col lg:col-span-9">
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
            {history.isLoading && activeSession !== null && <CardSkeleton rows={4} />}
            {thread.length === 0 && !history.isLoading && (
              <EmptyState message={t.chat.empty} />
            )}
            {thread.map((message, index) => (
              <ChatMessage key={index} {...message} />
            ))}
            {streaming && (
              <ChatMessage role="assistant" content="" pending register={null} />
            )}
            <div ref={threadEndRef} />
          </div>

          <form
            className="flex items-center gap-2 border-t p-4"
            onSubmit={(event) => {
              event.preventDefault()
              void send()
            }}
          >
            <Input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={t.chat.input_placeholder}
              disabled={streaming}
              aria-label={t.chat.input_placeholder}
            />
            <Button type="submit" variant="primary" size="icon" disabled={streaming || !input.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}
