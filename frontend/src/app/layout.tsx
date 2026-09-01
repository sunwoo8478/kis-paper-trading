import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/theme-provider";
import { MarketTape } from "@/components/market-tape";
import { AiCopilot } from "@/components/ai-copilot";
import { AccountSourceProvider } from "@/components/account-source-provider";

export const metadata: Metadata = {
  title: "국내주식 모의투자",
  description: "KOSPI/KOSDAQ 모의투자 대시보드",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ko"
      suppressHydrationWarning
      className="h-full antialiased"
    >
      <body className="min-h-full bg-background text-foreground">
        <ThemeProvider>
          <AccountSourceProvider>
            <div className="flex min-h-full flex-col">
              <Nav />
              <MarketTape />
              <main className="mx-auto w-full max-w-[1760px] flex-1 px-4 py-6 sm:px-6 xl:px-8">
                <div className="space-y-6">{children}</div>
              </main>
            </div>
            <AiCopilot />
            <Toaster />
          </AccountSourceProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
