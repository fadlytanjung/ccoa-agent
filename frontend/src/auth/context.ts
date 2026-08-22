/**
 * The auth context object, alone in its own module.
 *
 * React Fast Refresh cannot preserve state across edits in a file that exports both a
 * component and a context. Keeping them apart means editing the provider does not drop
 * the session on every save.
 */
import { createContext } from "react";

import type { RuntimeConfig } from "../api/types";

export interface Session {
  email: string;
  groups: string[];
  accessToken: string | null;
}

export interface AuthContextValue {
  status: "loading" | "authenticated" | "anonymous" | "error";
  session: Session | null;
  config: RuntimeConfig | null;
  error: string | null;
  signIn(): void;
  signOut(): void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
