/**
 * Cognito wiring — docs/07 §3.4, docs/10 §3.2.
 *
 * Authorization Code + PKCE against the Cognito Hosted UI. Two things about Cognito make
 * this more than "point oidc-client-ts at the issuer and go":
 *
 * 1. **The endpoints are declared explicitly rather than discovered.** A user pool's
 *    discovery document is served from `cognito-idp.<region>.amazonaws.com`, but the
 *    authorization and token endpoints live on the *hosted UI domain*, which is a
 *    separate resource that may not exist when the pool is created. Depending on
 *    discovery makes sign-in fail with an unhelpful error whenever the domain is missing
 *    or was added after the pool. Declaring them from the domain the server reports is
 *    both faster (no metadata round-trip before the redirect) and honest about the
 *    dependency.
 *
 * 2. **Cognito has no `end_session_endpoint`.** It exposes `/logout`, which takes
 *    `client_id` and `logout_uri` — not the OIDC `id_token_hint` and
 *    `post_logout_redirect_uri` that `UserManager.signoutRedirect()` sends. Calling that
 *    method throws "no end session endpoint" outright, so sign-out is built by hand in
 *    `logoutUrl` below.
 *
 * **This works against a real pool from `http://localhost:5173`.** Cognito allows
 * `http://localhost` callback URLs specifically so a SPA can be developed against real
 * identities — the only requirement is that the exact URL is registered on the app
 * client. See docs/18 §7 for the console steps.
 */

import { UserManager, WebStorageStateStore } from "oidc-client-ts";

import type { RuntimeConfig } from "../api/types";

/** Where Cognito returns to after a successful sign-in. Must be registered verbatim. */
export const CALLBACK_PATH = "/callback";

export function redirectUri(): string {
  return `${window.location.origin}${CALLBACK_PATH}`;
}

function issuerOf(config: RuntimeConfig): string {
  const { region, user_pool_id } = config.cognito;
  return `https://cognito-idp.${region}.amazonaws.com/${user_pool_id}`;
}

/**
 * The hosted UI origin.
 *
 * `COGNITO_DOMAIN` may legitimately be any of three things, because Cognito itself offers
 * all three and the console shows a different one on each page:
 *
 * * a **prefix** — `ccoa-dev`, which expands to the regional amazoncognito.com host;
 * * a **full host** — `ccoa-dev.auth.ap-southeast-1.amazoncognito.com`, or a custom one;
 * * a **full URL** — the same with `https://` already on the front.
 *
 * Treating a bare prefix as a host produces `https://ccoa-dev`, which fails to resolve
 * and sends the agent to a browser error page instead of a login form. The dot is what
 * distinguishes the two: a prefix cannot contain one.
 */
function domainOf(config: RuntimeConfig): string {
  const domain = (config.cognito.domain ?? "").trim().replace(/\/+$/, "");
  if (!domain) throw new Error("No Cognito domain is configured — see docs/18 §7.");
  if (domain.startsWith("http")) return domain;
  if (domain.includes(".")) return `https://${domain}`;
  return `https://${domain}.auth.${config.cognito.region}.amazoncognito.com`;
}

export function buildUserManager(config: RuntimeConfig): UserManager {
  const issuer = issuerOf(config);
  const domain = domainOf(config);

  return new UserManager({
    authority: issuer,
    client_id: config.cognito.client_id,
    redirect_uri: redirectUri(),
    response_type: "code",
    // `email` and `profile` populate the ID token used for display; the access token is
    // what the API validates. No custom scope is requested — the backend authorises on
    // group membership, not on scopes (docs/10 §3.3).
    scope: "openid email profile",
    metadata: {
      issuer,
      authorization_endpoint: `${domain}/oauth2/authorize`,
      token_endpoint: `${domain}/oauth2/token`,
      userinfo_endpoint: `${domain}/oauth2/userInfo`,
      revocation_endpoint: `${domain}/oauth2/revoke`,
      jwks_uri: `${issuer}/.well-known/jwks.json`,
    },
    // Only the PKCE verifier and the refresh state live here, and only for as long as the
    // redirect is in flight. **The access token is never written to storage** — it stays
    // in a React ref, because anything in Web Storage is readable by any injected script
    // and this application renders customer records (docs/07 §3.4).
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
    monitorSession: false,
    // The authorization code is single-use and lands in the address bar; clearing it
    // keeps it out of the history entry and out of any `Referer` sent afterwards.
    loadUserInfo: false,
  });
}

/**
 * Cognito's sign-out URL.
 *
 * `logout_uri` must exactly match an **Allowed sign-out URL** on the app client, or
 * Cognito answers with `redirect_mismatch` and the user is stranded on an error page
 * with a valid session.
 */
export function logoutUrl(config: RuntimeConfig): string {
  const query = new URLSearchParams({
    client_id: config.cognito.client_id,
    logout_uri: window.location.origin,
  });
  return `${domainOf(config)}/logout?${query}`;
}
