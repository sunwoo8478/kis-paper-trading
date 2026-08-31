"use client";

import { useState } from "react";
import useSWR from "swr";
import { BookOpen, Save } from "lucide-react";
import { toast } from "sonner";
import { ApiError, getJournalEntry, type JournalEntry, saveJournalEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function TradeJournalPanel({ code }: { code: string }) {
  const journal = useSWR(["/api/journal", code], () => getJournalEntry(code));

  if (!journal.data) {
    return <section className="h-48 animate-pulse rounded-xl border border-border bg-card" aria-label="트레이딩 저널 불러오는 중" />;
  }

  return (
    <TradeJournalForm
      key={journal.data.updated_at ?? code}
      code={code}
      initial={journal.data}
      onSaved={(entry) => journal.mutate(entry, false)}
    />
  );
}

function TradeJournalForm({ code, initial, onSaved }: { code: string; initial: JournalEntry; onSaved: (entry: JournalEntry) => void }) {
  const [thesis, setThesis] = useState(initial.thesis);
  const [invalidation, setInvalidation] = useState(initial.invalidation);
  const [targetPrice, setTargetPrice] = useState(initial.target_price == null ? "" : String(initial.target_price));
  const [tags, setTags] = useState(initial.tags.join(", "));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const parsedTarget = targetPrice.trim() ? Number(targetPrice) : null;
    if (parsedTarget !== null && (!Number.isFinite(parsedTarget) || parsedTarget <= 0)) {
      toast.error("목표 가격을 확인해 주세요.");
      return;
    }
    setSaving(true);
    try {
      const result = await saveJournalEntry(code, {
        thesis,
        invalidation,
        target_price: parsedTarget,
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      onSaved(result);
      toast.success("트레이딩 저널을 저장했습니다.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "트레이딩 저널 저장 실패");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-muted-foreground" />
          <div>
            <h2 className="text-sm font-semibold">트레이딩 저널</h2>
            <p className="text-[10px] text-muted-foreground">진입 논리와 무효화 조건</p>
          </div>
        </div>
        <Button size="sm" onClick={save} disabled={saving}>
          <Save className="h-3.5 w-3.5" />
          저장
        </Button>
      </header>
      <div className="space-y-4 p-4">
        <Field label="투자 논리">
          <textarea value={thesis} onChange={(event) => setThesis(event.target.value)} placeholder="관찰 근거, 진입 조건, 예상 시나리오" rows={4} className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-xs leading-5 outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/30" />
        </Field>
        <Field label="무효화 조건">
          <textarea value={invalidation} onChange={(event) => setInvalidation(event.target.value)} placeholder="가격, 추세, 이벤트 기준" rows={3} className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-xs leading-5 outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/30" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="목표 가격"><Input type="number" min={1} value={targetPrice} onChange={(event) => setTargetPrice(event.target.value)} className="h-9 font-mono" /></Field>
          <Field label="태그"><Input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="swing, breakout" className="h-9" /></Field>
        </div>
        {initial.updated_at && <p className="text-right text-[9px] text-muted-foreground">최근 저장 {new Date(initial.updated_at).toLocaleString("ko-KR")}</p>}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-2"><span className="text-[10px] font-medium text-muted-foreground">{label}</span>{children}</label>;
}
