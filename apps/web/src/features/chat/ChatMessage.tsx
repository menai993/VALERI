/**
 * ChatMessage (frontend-spec §4): one thread bubble.
 *
 * Assistant messages carry the full discipline: RegisterChip + the narrative +
 * the tool-call line + an inline card when an action ran (task draft, or the
 * M10 rule proposal with its one-tap confirm).
 */
import { Bot, CheckCircle2, User, Wrench, XCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import { useApplyRuleMutation } from "@/lib/api/queries"
import type { ChatToolCall, EffectEstimate, Register } from "@/lib/api/types"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/**
 * Inline self-config card (M10): the chat feedback_config intent produced a rule
 * proposal — show what happened (applied / pending) and offer the one-tap confirm.
 * Separate component so the mutation hook only mounts when the card exists.
 */
function RuleProposalCard({ payload }: { payload: Record<string, unknown> }) {
  const t = useT()
  const apply = useApplyRuleMutation()
  const applied = Boolean(payload.applied) || apply.isSuccess
  const effect = (payload.effect_estimate ?? null) as EffectEstimate | null

  return (
    <div
      className="flex flex-col gap-2 rounded-md bg-surface-2 p-3"
      data-testid="rule-proposal-card"
    >
      <div className="flex items-center gap-2">
        <RegisterChip register={applied ? "akcija" : "preporuka"} />
        <Badge>{applied ? t.rule_card.status_applied : t.rule_card.status_pending}</Badge>
      </div>

      {/* The Bosnian description Tier-1 wrote from the user's feedback. */}
      <span className="text-sm font-medium text-text">{String(payload.description)}</span>

      {effect && (
        <span className="text-[11.5px] text-text-3">
          {t.rule_card.effect_label}: <span className="tnum">{effect.total_signals}</span>{" "}
          {t.rule_card.effect_signals} <span className="tnum">{effect.window_days}</span>{" "}
          {t.rule_card.effect_days} · {t.app.sql_footer}
        </span>
      )}

      {applied ? (
        <span className="text-xs text-text-3">{t.rule_card.applied_note}</span>
      ) : (
        <div className="flex items-center gap-2">
          <Button
            variant="positive"
            size="sm"
            onClick={() => apply.mutate(Number(payload.learned_rule_id))}
            disabled={apply.isPending}
            data-testid="chat-apply-rule"
          >
            {t.rule_card.apply}
          </Button>
          {apply.isError && <span className="text-xs text-down">{t.rule_card.error}</span>}
        </div>
      )}
    </div>
  )
}

export interface ChatMessageProps {
  role: "user" | "assistant"
  content: string
  register?: Register | null
  toolCalls?: ChatToolCall[] | null
  card?: { card_type: string; payload: Record<string, unknown> } | null
  pending?: boolean
}

export function ChatMessage({
  role,
  content,
  register,
  toolCalls,
  card,
  pending,
}: ChatMessageProps) {
  const t = useT()
  const isUser = role === "user"

  return (
    <div
      className={cn("flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}
      data-testid={`chat-message-${role}`}
    >
      <span
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-surface-2 text-text-2" : "bg-primary-soft text-primary",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </span>

      <div
        className={cn(
          "flex max-w-[80%] flex-col gap-2 rounded-lg p-4",
          isUser ? "bg-primary text-white" : "border bg-surface shadow-card-sm",
        )}
      >
        {/* Register chip on every AI reply (principle 9). */}
        {!isUser && register && (
          <div className="flex items-center gap-2">
            <RegisterChip register={register} />
          </div>
        )}

        <p className={cn("whitespace-pre-line text-sm", !isUser && "text-text-2")}>
          {pending ? t.chat.thinking : content}
        </p>

        {/* The tool-call provenance line ("brojke iz baze · SQL" discipline). */}
        {!isUser && toolCalls && toolCalls.length > 0 && (
          <div className="flex flex-col gap-1 border-t pt-2" data-testid="tool-calls">
            {toolCalls.map((call, index) => (
              <div key={index} className="flex items-center gap-2 text-[11.5px] text-text-3">
                <Wrench className="h-3 w-3" />
                <span className="font-medium">{call.tool}</span>
                {call.ok ? (
                  <CheckCircle2 className="h-3 w-3 text-up" />
                ) : (
                  <XCircle className="h-3 w-3 text-down" />
                )}
                <span>· {t.app.sql_footer}</span>
              </div>
            ))}
          </div>
        )}

        {/* Inline task-draft card (akcija + visible status — nothing happens silently). */}
        {!isUser && card?.card_type === "task_draft" && (
          <div
            className="flex flex-col gap-2 rounded-md bg-surface-2 p-3"
            data-testid="task-draft-card"
          >
            <div className="flex items-center gap-2">
              <RegisterChip register="akcija" />
              <Badge>{String(card.payload.status)}</Badge>
            </div>
            <span className="text-sm font-medium text-text">{String(card.payload.title)}</span>
            <span className="text-xs text-text-3">
              {t.chat.task_created} · #{String(card.payload.task_id)}
            </span>
          </div>
        )}

        {/* Inline self-config rule card (M10 — visible, reversible, confirmable). */}
        {!isUser && card?.card_type === "rule_proposal" && (
          <RuleProposalCard payload={card.payload} />
        )}
      </div>
    </div>
  )
}
