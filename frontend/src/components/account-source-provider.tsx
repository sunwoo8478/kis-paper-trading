"use client";

import { createContext, useContext, useState } from "react";

export type AccountSource = "kis" | "local";

const AccountSourceContext = createContext<{
  source: AccountSource;
  setSource: (source: AccountSource) => void;
} | null>(null);

export function AccountSourceProvider({ children }: { children: React.ReactNode }) {
  const [source, setSourceState] = useState<AccountSource>("kis");

  const setSource = (next: AccountSource) => {
    setSourceState(next);
  };

  return <AccountSourceContext.Provider value={{ source, setSource }}>{children}</AccountSourceContext.Provider>;
}

export function useAccountSource() {
  const value = useContext(AccountSourceContext);
  if (!value) throw new Error("useAccountSource must be used inside AccountSourceProvider");
  return value;
}
