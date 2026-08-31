"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      aria-label="화면 테마 전환"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      disabled={!mounted}
      className="rounded-full"
    >
      {mounted && resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
