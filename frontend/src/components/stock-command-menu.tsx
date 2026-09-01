"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Bell, ChartNoAxesCombined, ListOrdered, Radar, Search, ShieldCheck, Star } from "lucide-react";
import { searchStocks } from "@/lib/api";
import { formatChangePct, formatPrice, changeColorClass } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

export function StockCommandMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const stocks = useSWR(open && query.trim() ? ["/api/stocks", query] : null, () => searchStocks(query.trim()));

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const select = (code: string) => {
    setOpen(false);
    setQuery("");
    router.push(`/stocks/${code}`);
  };

  const navigate = (href: string) => {
    setOpen(false);
    setQuery("");
    router.push(href);
  };

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} className="hidden h-9 min-w-48 justify-between text-xs font-normal text-muted-foreground xl:flex">
        <span className="flex items-center gap-2"><Search className="h-3.5 w-3.5" />종목 검색</span>
        <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[9px]">⌘K</kbd>
      </Button>
      <Button variant="outline" size="icon-sm" onClick={() => setOpen(true)} className="xl:hidden" aria-label="종목과 메뉴 검색">
        <Search className="h-3.5 w-3.5" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="top-[18%] max-w-xl translate-y-0 p-0" showCloseButton={false}>
          <DialogHeader className="sr-only">
            <DialogTitle>종목 빠른 검색</DialogTitle>
            <DialogDescription>종목명이나 종목코드로 상세 화면을 엽니다.</DialogDescription>
          </DialogHeader>
          <div className="relative border-b border-border">
            <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="종목명 또는 종목코드" className="h-14 rounded-none border-0 bg-transparent pl-11 pr-4 text-sm shadow-none focus-visible:ring-0" />
          </div>
          <div className="max-h-96 overflow-y-auto p-2">
            {!query.trim() ? (
              <div>
                <p className="px-3 pb-2 pt-1 text-[10px] font-medium text-muted-foreground">빠른 이동</p>
                <div className="grid grid-cols-2 gap-1">
                  {QUICK_ACTIONS.map((action) => (
                    <button key={action.href} type="button" onClick={() => navigate(action.href)} className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground active:translate-y-px">
                      <action.icon className="h-3.5 w-3.5" />
                      {action.label}
                    </button>
                  ))}
                </div>
                <p className="mt-2 border-t border-border px-3 py-3 text-[10px] text-muted-foreground">종목명이나 코드를 입력하면 상세 화면으로 이동합니다.</p>
              </div>
            ) : stocks.isLoading ? (
              <div className="space-y-2 p-2">{[0, 1, 2].map((item) => <div key={item} className="h-12 animate-pulse rounded-lg bg-muted" />)}</div>
            ) : (stocks.data ?? []).length === 0 ? (
              <p className="px-3 py-8 text-center text-xs text-muted-foreground">일치하는 종목이 없습니다.</p>
            ) : (
              (stocks.data ?? []).slice(0, 12).map((stock) => (
                <button key={stock.code} type="button" onClick={() => select(stock.code)} className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-lg px-3 py-2.5 text-left transition hover:bg-muted active:translate-y-px">
                  <div className="min-w-0"><p className="truncate text-sm font-medium">{stock.name}</p><p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{stock.code} / {stock.market}</p></div>
                  <div className="text-right"><p className="font-mono text-xs">{formatPrice(stock.last_price)}</p><p className={`font-mono text-[10px] ${changeColorClass(stock.change_pct)}`}>{formatChangePct(stock.change_pct)}</p></div>
                </button>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

const QUICK_ACTIONS = [
  { href: "/market", label: "시장 현황", icon: ChartNoAxesCombined },
  { href: "/screener", label: "종목 검색", icon: Radar },
  { href: "/watchlist", label: "관심 종목", icon: Star },
  { href: "/orders", label: "주문 내역", icon: ListOrdered },
  { href: "/risk", label: "리스크", icon: ShieldCheck },
  { href: "/alerts", label: "가격 알림", icon: Bell },
];
