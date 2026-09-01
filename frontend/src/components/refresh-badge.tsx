"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function RefreshBadge({
  hasError,
  isValidating,
  onRefresh,
}: {
  hasError: boolean;
  isValidating: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      {hasError && <Badge variant="destructive">마지막 갱신 실패, 기존 데이터 표시 중</Badge>}
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={isValidating}>
        <RefreshCw className={isValidating ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        새로고침
      </Button>
    </div>
  );
}
