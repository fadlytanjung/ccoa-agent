/** Session access. Split from the provider so each module has one job. */
import { use } from "react";

import { AuthContext, type Session } from "./context";

export function useAuth() {
  const context = use(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an AuthProvider");
  return context;
}

export type { Session };
