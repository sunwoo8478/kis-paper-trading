"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CandlestickChart } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { StockCommandMenu } from "@/components/stock-command-menu";

const LINKS = [
  { href: "/", label: "대시보드" },
  { href: "/market", label: "시장" },
  { href: "/screener", label: "종목검색" },
  { href: "/watchlist", label: "관심종목" },
  { href: "/risk", label: "리스크" },
  { href: "/alerts", label: "알림" },
  { href: "/orders", label: "주문내역" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-40 border-b border-border bg-background/92 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1760px] items-center justify-between gap-4 px-4 sm:px-6 xl:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-border bg-card">
            <CandlestickChart className="h-4.5 w-4.5 text-foreground" />
          </div>
          <div className="leading-tight">
            <span className="block text-[13px] font-semibold tracking-tight">모의투자</span>
            <span className="block text-[11px] text-muted-foreground">KOSPI / KOSDAQ workspace</span>
          </div>
        </div>

        <StockCommandMenu />

        <div className="ml-auto hidden items-center gap-1 md:flex">
          {LINKS.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-full px-3 py-2 text-sm transition",
                  active
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 text-xs text-muted-foreground lg:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            데이터 연결
          </div>
          <ThemeToggle />
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto border-t border-border px-3 py-1.5 md:hidden">
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "shrink-0 rounded-md px-3 py-1.5 text-xs",
              (link.href === "/" ? pathname === "/" : pathname.startsWith(link.href)) ? "bg-foreground text-background" : "text-muted-foreground"
            )}
          >
            {link.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
