"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { Bot, ChevronDown, CornerDownLeft, Maximize2, Minimize2, ShieldCheck, Sparkles, X } from "lucide-react";
import {
  ApiError,
  askKisCopilot,
  type CopilotChatMessage,
  getAgentCandidates,
  getAgentRuns,
  getAgentStatus,
  getExperimentStatus,
  getOrders,
  getPortfolioRisk,
  placeKisOrder,
  streamCopilot,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useAccountSource } from "@/components/account-source-provider";
import { cn } from "@/lib/utils";

type CopilotAction = "screen" | "risk" | "market" | "orders";
type PanelRect = { x: number; y: number; width: number; height: number };
type ResizeCorner = "nw" | "ne" | "sw" | "se";

const PANEL_STORAGE_KEY = "trading-ai-copilot-rect";
const QUICK_ACTION_PROMPTS: Record<CopilotAction, string> = {
  screen: "현재 화면 상황을 요약해줘",
  risk: "포트폴리오 위험을 분석해줘",
  market: "시장 후보를 스캔해서 알려줘",
  orders: "주문 상태를 검토해줘",
};

export function AiCopilot() {
  const pathname = usePathname();
  const { source: accountSource } = useAccountSource();
  const isKis = accountSource === "kis";
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<CopilotChatMessage[]>([
    { role: "assistant", content: "현재 화면과 계좌 데이터를 기준으로 운용 정보를 정리할 수 있습니다." },
  ]);
  const [thinking, setThinking] = useState(false);
  const [kisSubmitting, setKisSubmitting] = useState<number | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const rectRef = useRef<PanelRect | null>(null);
  const restoreRectRef = useRef<PanelRect | null>(null);
  const experimentIdRef = useRef<number | null>(null);
  const risk = useSWR(open ? "/api/portfolio/risk:copilot" : null, getPortfolioRisk, { refreshInterval: 10000 });
  const candidates = useSWR(open ? "/api/agent/candidates:copilot" : null, getAgentCandidates, { refreshInterval: 15000 });
  const runs = useSWR(open ? "/api/agent/runs:copilot" : null, getAgentRuns, { refreshInterval: 15000 });
  const orders = useSWR(open ? "/api/orders:copilot" : null, getOrders, { refreshInterval: 10000 });
  const status = useSWR(open ? "/api/agent/status:copilot" : null, getAgentStatus, { refreshInterval: 15000 });
  const experiment = useSWR(open ? "/api/agent/experiment:copilot" : null, getExperimentStatus, { refreshInterval: 10000 });
  const stockCode = pathname.match(/^\/stocks\/(\d{6})/)?.[1] ?? null;
  const scope = stockCode ? `종목 ${stockCode}` : routeLabel(pathname);

  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener("open-ai-copilot", show);
    return () => window.removeEventListener("open-ai-copilot", show);
  }, []);

  useEffect(() => {
    if (!open || !panelRef.current) return;
    const saved = loadPanelRect();
    const rect = clampPanelRect(saved ?? defaultPanelRect());
    rectRef.current = rect;
    applyPanelRect(panelRef.current, rect);

    const keepInViewport = () => {
      if (!panelRef.current || !rectRef.current) return;
      const next = clampPanelRect(rectRef.current);
      rectRef.current = next;
      applyPanelRect(panelRef.current, next);
      persistPanelRect(next);
    };
    window.addEventListener("resize", keepInViewport);
    return () => window.removeEventListener("resize", keepInViewport);
  }, [open]);

  const context = useMemo(() => ({
    risk: risk.data,
    candidates: candidates.data ?? [],
    runs: runs.data ?? [],
    orders: orders.data ?? [],
    scope,
    stockCode,
  }), [risk.data, candidates.data, runs.data, orders.data, scope, stockCode]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages, thinking]);

  useEffect(() => {
    const nextId = experiment.data?.experiment?.id ?? null;
    if (nextId === null || experimentIdRef.current === nextId) return;
    experimentIdRef.current = nextId;
    setMessages([
      { role: "assistant", content: `새 AI 운용 실험이 시작되었습니다. 실험 #${nextId} 이후의 계좌 데이터만 기준으로 답변합니다.` },
    ]);
  }, [experiment.data?.experiment?.id]);

  const ask = async (question: string, fallbackAction: CopilotAction) => {
    const history = messages;
    setMessages((prev) => [...prev, { role: "user", content: question }]);

    const kisResult = isKis ? await askKisCopilot(question).catch(() => null) : null;
    if (kisResult?.proposal) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: kisResult.answer, kisProposal: kisResult.proposal },
      ]);
      return;
    }

    if (!status.data?.model_connected) {
      setMessages((prev) => [...prev, { role: "assistant", content: buildResponse(fallbackAction, context) }]);
      return;
    }

    setThinking(true);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    try {
      const result = await streamCopilot(question, scope, stockCode, history, (visibleText) => {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { role: "assistant", content: visibleText };
          return next;
        });
      });
      const executedNote =
        result.order_ids.length > 0 ? `\n\n체결된 주문: ${result.order_ids.join(", ")}` : "";
      const blockedNote =
        result.blocked.length > 0
          ? `\n\n차단된 판단: ${result.blocked
              .map((b) => `${String(b.decision.code ?? "?")}(${b.reason})`)
              .join(", ")}`
          : "";
      if (executedNote || blockedNote) {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: "assistant",
            content: next[next.length - 1].content + executedNote + blockedNote,
          };
          return next;
        });
      }
      if (result.order_ids.length > 0) {
        orders.mutate();
        risk.mutate();
      }
    } catch (error) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          content: error instanceof ApiError ? `로컬 모델 오류: ${error.message}` : "로컬 모델 호출 중 오류가 발생했습니다.",
        };
        return next;
      });
    } finally {
      setThinking(false);
    }
  };

  const confirmKisOrder = async (index: number) => {
    const proposal = messages[index]?.kisProposal;
    if (!proposal) return;
    setKisSubmitting(index);
    try {
      const result = await placeKisOrder(proposal);
      const sideLabel = proposal.side === "buy" ? "매수" : "매도";
      setMessages((prev) => {
        const next = [...prev];
        next[index] = { ...next[index], kisProposal: null };
        next.push({
          role: "assistant",
          content: `주문 전송 완료: ${proposal.name}(${proposal.code}) ${proposal.quantity}주 ${sideLabel}, 브로커 주문번호 ${result.broker_order_id ?? result.order_id}`,
        });
        return next;
      });
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: error instanceof ApiError ? `주문 실패: ${error.message}` : "주문 전송 중 오류가 발생했습니다.",
        },
      ]);
    } finally {
      setKisSubmitting(null);
    }
  };
  const cancelKisOrder = (index: number) => {
    setMessages((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], kisProposal: null };
      return next;
    });
  };

  const run = (action: CopilotAction) => ask(QUICK_ACTION_PROMPTS[action], action);
  const submit = () => {
    const value = prompt.trim();
    if (!value) return;
    const normalized = value.toLowerCase();
    const fallbackAction: CopilotAction = normalized.includes("위험") || normalized.includes("리스크") ? "risk" : normalized.includes("주문") || normalized.includes("매수") || normalized.includes("매도") ? "orders" : normalized.includes("시장") || normalized.includes("후보") ? "market" : "screen";
    ask(value, fallbackAction);
    setPrompt("");
  };
  const toggleExpanded = () => {
    if (!panelRef.current) return;
    if (expanded) {
      const next = clampPanelRect(restoreRectRef.current ?? loadPanelRect() ?? defaultPanelRect());
      rectRef.current = next;
      applyPanelRect(panelRef.current, next);
      persistPanelRect(next);
      setExpanded(false);
      return;
    }
    restoreRectRef.current = rectRef.current;
    const next = clampPanelRect({ x: 8, y: 8, width: window.innerWidth - 16, height: window.innerHeight - 16 });
    rectRef.current = next;
    applyPanelRect(panelRef.current, next);
    setExpanded(true);
  };
  const startDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (expanded || event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
    beginPanelInteraction(event, "drag", panelRef, rectRef, () => setExpanded(false));
  };
  const startResize = (corner: ResizeCorner, event: ReactPointerEvent<HTMLButtonElement>) => {
    if (expanded || event.button !== 0) return;
    event.stopPropagation();
    beginPanelInteraction(event, corner, panelRef, rectRef, () => setExpanded(false));
  };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-xl border border-border bg-foreground px-3 py-2.5 text-xs font-medium text-background shadow-lg transition hover:opacity-90 active:translate-y-px" aria-label="AI 운용 코파일럿 열기">
        <Bot className="h-4 w-4" /><span className="hidden sm:inline">AI 코파일럿</span>
      </button>
    );
  }

  return (
    <aside ref={panelRef} className="fixed z-40 flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl" aria-label="AI 운용 코파일럿">
      <header onPointerDown={startDrag} className={cn("flex min-h-14 touch-none items-center justify-between border-b border-border px-4", expanded ? "cursor-default" : "cursor-grab active:cursor-grabbing")}>
        <div className="flex items-center gap-2.5"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"><Bot className="h-4 w-4" /></span><div><p className="text-sm font-semibold">운용 코파일럿 · {isKis ? "KIS 모의계좌" : "로컬 시뮬레이터"}</p><p className="text-[9px] text-muted-foreground">{scope} 컨텍스트</p></div></div>
        <div className="flex items-center gap-1"><Button variant="ghost" size="icon-sm" onClick={toggleExpanded} aria-label={expanded ? "코파일럿 축소" : "코파일럿 확대"}>{expanded ? <Minimize2 /> : <Maximize2 />}</Button><Button variant="ghost" size="icon-sm" onClick={() => setOpen(false)} aria-label="코파일럿 닫기"><X /></Button></div>
      </header>

      <div className="grid grid-cols-2 border-b border-border bg-muted/20 text-[9px]"><div className="border-r border-border px-3 py-2"><span className="text-muted-foreground">모델 연결</span><p className={cn("mt-0.5 font-medium", status.data?.model_connected ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400")}>{status.data?.model_connected ? `${status.data.provider} / ${status.data.model}${status.data.context7_connected ? " · Context7" : ""}` : "연결 대기"}</p></div><div className="px-3 py-2"><span className="text-muted-foreground">자동 주문 권한</span><p className={cn("mt-0.5 font-medium", status.data?.auto_execution_enabled ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400")}>{status.data?.auto_execution_enabled ? "모의 자동운용" : "안전 잠금"}</p></div></div>

      <div className="grid grid-cols-2 gap-1.5 border-b border-border p-3">
        <QuickAction label="현재 화면 요약" onClick={() => run("screen")} disabled={thinking} /><QuickAction label="포트폴리오 위험" onClick={() => run("risk")} disabled={thinking} /><QuickAction label="시장 후보 스캔" onClick={() => run("market")} disabled={thinking} /><QuickAction label="주문 상태 검토" onClick={() => run("orders")} disabled={thinking} />
      </div>

      <div ref={logRef} className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-3">
          {messages.map((message, index) => (
            <div key={index} className={cn("flex gap-2", message.role === "user" && "flex-row-reverse")}>
              {message.role === "assistant" && (
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              )}
              <div
                className={cn(
                  "max-w-[85%] rounded-lg px-3 py-2 text-sm leading-6 whitespace-pre-line",
                  message.role === "user" ? "bg-foreground text-background" : "bg-muted/40"
                )}
              >
                {message.content ||
                  (thinking && index === messages.length - 1 ? "로컬 모델이 생각하는 중..." : "")}
                {message.kisProposal && (
                  <div className="mt-2 flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => confirmKisOrder(index)}
                      disabled={kisSubmitting === index}
                    >
                      확인
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => cancelKisOrder(index)}
                      disabled={kisSubmitting === index}
                    >
                      취소
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 border border-border bg-muted/20 p-3"><div className="flex items-center gap-2 text-[10px] font-medium"><ShieldCheck className="h-3.5 w-3.5" />안전 게이트</div><p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">종목 비중 {status.data?.safety.max_position_pct ?? 20}% 이내, 일 손실 {status.data?.safety.max_daily_loss_pct ?? 3}% 이내{status.data?.safety.human_approval_required === false ? " 조건으로 자동 승인" : ", 사용자 승인 후 주문"}하도록 연결됩니다.</p></div>
      </div>

      <form className="border-t border-border p-3" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        <div className="flex items-end gap-2 rounded-lg border border-input bg-background p-2 focus-within:ring-2 focus-within:ring-ring/40"><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={2} placeholder="위험·주문 질문 또는 /docs next.js 질문" className="min-h-10 flex-1 resize-none bg-transparent text-xs leading-5 outline-none placeholder:text-muted-foreground" disabled={thinking} /><Button type="submit" size="icon-sm" disabled={!prompt.trim() || thinking} aria-label="질문 보내기"><CornerDownLeft /></Button></div>
        <button type="button" onClick={() => setOpen(false)} className="mt-2 flex w-full items-center justify-center gap-1 text-[9px] text-muted-foreground hover:text-foreground"><ChevronDown className="h-3 w-3" />작업 공간으로 돌아가기</button>
      </form>
      {!expanded && <>
        <ResizeHandle corner="nw" onPointerDown={(event) => startResize("nw", event)} />
        <ResizeHandle corner="ne" onPointerDown={(event) => startResize("ne", event)} />
        <ResizeHandle corner="sw" onPointerDown={(event) => startResize("sw", event)} />
        <ResizeHandle corner="se" onPointerDown={(event) => startResize("se", event)} />
      </>}
    </aside>
  );
}

function ResizeHandle({ corner, onPointerDown }: { corner: ResizeCorner; onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void }) {
  const position = { nw: "left-0 top-0 cursor-nwse-resize", ne: "right-0 top-0 cursor-nesw-resize", sw: "bottom-0 left-0 cursor-nesw-resize", se: "bottom-0 right-0 cursor-nwse-resize" }[corner];
  const border = { nw: "border-l border-t", ne: "border-r border-t", sw: "border-b border-l", se: "border-b border-r" }[corner];
  return <button type="button" aria-label={`코파일럿 ${corner} 모서리 크기 조절`} onPointerDown={onPointerDown} className={cn("absolute z-10 h-5 w-5 touch-none border-border/70", position, border)} />;
}

function beginPanelInteraction(event: ReactPointerEvent<HTMLElement>, mode: "drag" | ResizeCorner, panelRef: React.RefObject<HTMLElement | null>, rectRef: React.MutableRefObject<PanelRect | null>, finish: () => void) {
  const panel = panelRef.current;
  const initial = rectRef.current;
  if (!panel || !initial) return;
  event.preventDefault();
  const pointerId = event.pointerId;
  event.currentTarget.setPointerCapture?.(pointerId);
  const startX = event.clientX;
  const startY = event.clientY;
  const previousUserSelect = document.body.style.userSelect;
  document.body.style.userSelect = "none";

  const move = (moveEvent: PointerEvent) => {
    if (moveEvent.pointerId !== pointerId) return;
    const dx = moveEvent.clientX - startX;
    const dy = moveEvent.clientY - startY;
    let next: PanelRect;
    if (mode === "drag") {
      next = { ...initial, x: initial.x + dx, y: initial.y + dy };
    } else {
      const west = mode === "nw" || mode === "sw";
      const north = mode === "nw" || mode === "ne";
      next = {
        x: west ? initial.x + dx : initial.x,
        y: north ? initial.y + dy : initial.y,
        width: initial.width + (west ? -dx : dx),
        height: initial.height + (north ? -dy : dy),
      };
    }
    next = clampPanelRect(next, mode);
    rectRef.current = next;
    applyPanelRect(panel, next);
  };
  const end = (endEvent: PointerEvent) => {
    if (endEvent.pointerId !== pointerId) return;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    document.body.style.userSelect = previousUserSelect;
    if (rectRef.current) persistPanelRect(rectRef.current);
    finish();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
}

function defaultPanelRect(): PanelRect {
  const width = Math.min(400, window.innerWidth - 16);
  const height = Math.min(640, window.innerHeight - 16);
  return { x: window.innerWidth - width - 16, y: window.innerHeight - height - 16, width, height };
}

function clampPanelRect(rect: PanelRect, anchor: "drag" | ResizeCorner = "drag"): PanelRect {
  const gap = 8;
  const minWidth = Math.min(340, window.innerWidth - gap * 2);
  const minHeight = Math.min(420, window.innerHeight - gap * 2);
  const maxWidth = window.innerWidth - gap * 2;
  const maxHeight = window.innerHeight - gap * 2;
  const width = Math.min(maxWidth, Math.max(minWidth, rect.width));
  const height = Math.min(maxHeight, Math.max(minHeight, rect.height));
  let x = rect.x;
  let y = rect.y;
  if ((anchor === "nw" || anchor === "sw") && width !== rect.width) x = rect.x + rect.width - width;
  if ((anchor === "nw" || anchor === "ne") && height !== rect.height) y = rect.y + rect.height - height;
  x = Math.min(window.innerWidth - width - gap, Math.max(gap, x));
  y = Math.min(window.innerHeight - height - gap, Math.max(gap, y));
  return { x, y, width, height };
}

function applyPanelRect(panel: HTMLElement, rect: PanelRect) {
  panel.style.left = `${rect.x}px`;
  panel.style.top = `${rect.y}px`;
  panel.style.width = `${rect.width}px`;
  panel.style.height = `${rect.height}px`;
}

function persistPanelRect(rect: PanelRect) {
  localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(rect));
}

function loadPanelRect(): PanelRect | null {
  try {
    const value = JSON.parse(localStorage.getItem(PANEL_STORAGE_KEY) ?? "null") as Partial<PanelRect> | null;
    return value && [value.x, value.y, value.width, value.height].every((item) => typeof item === "number" && Number.isFinite(item)) ? value as PanelRect : null;
  } catch {
    return null;
  }
}

function QuickAction({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) { return <button type="button" onClick={onClick} disabled={disabled} className="rounded-lg border border-border bg-background px-2.5 py-2 text-left text-[10px] font-medium transition hover:bg-muted active:translate-y-px disabled:opacity-50">{label}</button>; }

function routeLabel(pathname: string) { if (pathname === "/") return "AI 운용 콘솔"; if (pathname.startsWith("/market")) return "시장"; if (pathname.startsWith("/risk")) return "리스크"; if (pathname.startsWith("/orders")) return "주문"; if (pathname.startsWith("/alerts")) return "알림"; if (pathname.startsWith("/screener")) return "종목 탐색"; if (pathname.startsWith("/watchlist")) return "관심종목"; return "현재 화면"; }

function buildResponse(action: CopilotAction, context: { risk?: Awaited<ReturnType<typeof getPortfolioRisk>>; candidates: Awaited<ReturnType<typeof getAgentCandidates>>; runs: Awaited<ReturnType<typeof getAgentRuns>>; orders: Awaited<ReturnType<typeof getOrders>>; scope: string; stockCode: string | null }) {
  const { risk, candidates, runs, orders, scope, stockCode } = context;
  if (!risk) return "계좌 데이터를 불러오는 중입니다. 잠시 후 다시 실행해 주세요.";
  if (action === "risk") return `총 수익률은 ${risk.total_return_pct.toFixed(2)}%, 투자 비중은 ${risk.invested_ratio_pct.toFixed(1)}%입니다. 최대 종목 비중은 ${risk.max_position_weight_pct.toFixed(1)}%이며 현재 위험 신호는 ${risk.risk_flags.length}건입니다.${risk.risk_flags[0] ? `\n우선 확인: ${risk.risk_flags[0].message}` : "\n즉시 조치가 필요한 위험 신호는 없습니다."}`;
  if (action === "market") { const ranked = [...candidates].filter((item) => item.change_pct !== null).sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0)).slice(0, 3); return `분석 가능한 후보는 ${candidates.length}개입니다.${ranked.length ? `\n변동성 상위: ${ranked.map((item) => `${item.name} ${item.change_pct?.toFixed(2)}%`).join(", ")}` : "\n후보 가격 데이터가 아직 충분하지 않습니다."}`; }
  if (action === "orders") { const pending = orders.filter((order) => order.status === "pending"); const linked = runs[0]?.order_ids.length ?? 0; return `대기 주문은 ${pending.length}건, 최근 AI 판단에 연결된 주문은 ${linked}건입니다.${pending[0] ? `\n먼저 검토할 주문: ${pending[0].code} ${pending[0].side === "buy" ? "매수" : "매도"} ${pending[0].quantity}주` : "\n현재 체결을 기다리는 주문은 없습니다."}`; }
  const stock = stockCode ? candidates.find((item) => item.code === stockCode) : null;
  return `${scope}을 기준으로 분석했습니다. 계좌 투자 비중은 ${risk.invested_ratio_pct.toFixed(1)}%, 위험 신호는 ${risk.risk_flags.length}건, 분석 후보는 ${candidates.length}개입니다.${stock ? `\n${stock.name}은 현재 AI 후보군에 포함되어 있으며 최근 변동률은 ${stock.change_pct?.toFixed(2) ?? "-"}%입니다.` : ""}`;
}
