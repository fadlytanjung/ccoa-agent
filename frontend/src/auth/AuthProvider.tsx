/**
 * Authentication — docs/07 §3.4.
 *
 * Authorization Code + PKCE against the Cognito Hosted UI, with **tokens held in memory
 * only**. Not `localStorage`, not `sessionStorage`: both are readable by any injected
 * script, and this application shows customer records.
 *
 * It also honours the backend's `AUTH_MODE=dev`. That is not a shortcut bolted on for
 * convenience — without it the local loop would need a real Cognito pool to render a
 * single screen, and the backend already refuses to start with `AUTH_MODE=dev` outside
 * `ENVIRONMENT=local` (docs/14 §3.7). The SPA mirrors the server's own answer from
 * `/api/v1/config` rather than deciding for itself, so the two can never disagree about
 * whether a request needs a token.
 *
 * Running locally against a **real** pool is the other supported mode, and it is what
 * docs/18 §7 sets up: `AUTH_MODE=cognito` with `http://localhost:5173/callback`
 * registered on the app client. Nothing here branches on hostname.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { User, UserManager } from "oidc-client-ts";

import { api, setTokenSource } from "../api/client";
import { AuthContext, type AuthContextValue, type Session } from "./context";
import { CALLBACK_PATH, buildUserManager, logoutUrl } from "./cognito";
import type { RuntimeConfig } from "../api/types";

const DEV_SESSION: Session = {
  email: "dev@localhost",
  groups: ["agent", "supervisor"],
  accessToken: null,
};

function toSession(user: User): Session {
  const claims = user.profile as Record<string, unknown>;
  const groups = claims["cognito:groups"];
  return {
    email: typeof claims.email === "string" ? claims.email : "unknown",
    groups: Array.isArray(groups) ? groups.map(String) : [],
    accessToken: user.access_token,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthContextValue["status"]>("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const manager = useRef<UserManager | null>(null);
  const configRef = useRef<RuntimeConfig | null>(null);

  // The token source is a function rather than a value so the API client always reads
  // the *current* token after a silent renew, instead of a stale closure.
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  useEffect(() => {
    setTokenSource(() => sessionRef.current?.accessToken ?? null);
  }, []);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const runtime = await api.config();
        if (cancelled) return;
        setConfig(runtime);
        configRef.current = runtime;

        if (runtime.auth_mode === "dev") {
          setSession(DEV_SESSION);
          setStatus("authenticated");
          return;
        }

        const userManager = buildUserManager(runtime);
        manager.current = userManager;

        // A silent renew replaces the access token roughly a minute before it expires.
        // Without this subscription the session object keeps the old one and every
        // request 401s the moment it lapses — a failure that only appears after an hour
        // of use, which is exactly when nobody is watching for it.
        userManager.events.addUserLoaded((user) => {
          if (!cancelled) setSession(toSession(user));
        });
        userManager.events.addSilentRenewError(() => {
          if (!cancelled) {
            setSession(null);
            setStatus("anonymous");
          }
        });

        if (window.location.pathname === CALLBACK_PATH) {
          const user = await userManager.signinRedirectCallback();
          // Consume the code immediately so no credential survives in the history entry.
          window.history.replaceState({}, "", "/");
          if (cancelled) return;
          setSession(toSession(user));
          setStatus("authenticated");
          return;
        }

        const existing = await userManager.getUser();
        if (cancelled) return;
        if (existing && !existing.expired) {
          setSession(toSession(existing));
          setStatus("authenticated");
        } else {
          setStatus("anonymous");
        }
      } catch (cause) {
        if (cancelled) return;
        // A failed callback leaves `?code=` in the address bar; a refresh would then
        // retry a code Cognito has already burned and fail again with a different error.
        if (window.location.pathname === CALLBACK_PATH) {
          window.history.replaceState({}, "", "/");
        }
        setError(cause instanceof Error ? cause.message : String(cause));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(() => {
    const userManager = manager.current;
    if (!userManager) {
      setError("Sign-in is not configured. See docs/18 §7.");
      setStatus("error");
      return;
    }

    // PKCE derives its challenge with `crypto.subtle`, which browsers expose **only in a
    // secure context**: https, or plain http on localhost/127.0.0.1 specifically. Open the
    // dev server on a LAN address — http://192.168.x.x:5173, which is exactly what you do
    // to test on a phone — and `crypto.subtle` is `undefined`, the challenge cannot be
    // generated, and the redirect never happens. Saying so beats a button that silently
    // does nothing.
    if (!window.isSecureContext || !window.crypto?.subtle) {
      setError(
        `Sign-in needs a secure context. This page is on ${window.location.origin}; ` +
          "use https, or http://localhost — browsers withhold the crypto API that PKCE " +
          "requires everywhere else.",
      );
      setStatus("error");
      return;
    }

    // Awaited, not fired and forgotten. `void signinRedirect()` discards the promise, so
    // a rejected sign-in — bad metadata, a blocked redirect, an unreachable domain —
    // produced no navigation, no message, and no console error: the button simply did
    // nothing, which is the single least debuggable failure a login screen can have.
    void userManager.signinRedirect().catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("error");
    });
  }, []);

  const signOut = useCallback(() => {
    const runtime = configRef.current;
    setSession(null);
    setStatus("anonymous");
    if (!runtime || runtime.auth_mode === "dev" || !manager.current) return;
    // Clear the local session first, then hand off to Cognito. Reversed, the redirect
    // wins the race and the local session survives a "sign out" that appeared to work.
    void manager.current.removeUser().finally(() => {
      window.location.assign(logoutUrl(runtime));
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, session, config, error, signIn, signOut }),
    [status, session, config, error, signIn, signOut],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
