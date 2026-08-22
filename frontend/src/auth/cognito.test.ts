/**
 * Cognito URL construction — docs/07 §3.4, docs/18 §7.
 *
 * Worth testing precisely because it cannot be exercised locally without a real user
 * pool: every mistake here surfaces as a redirect to a browser error page in a deployed
 * environment, which is the most expensive place to discover it.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { buildUserManager, logoutUrl, redirectUri } from "./cognito";
import type { RuntimeConfig } from "../api/types";

function config(domain: string | null): RuntimeConfig {
  return {
    auth_mode: "cognito",
    environment: "dev",
    cognito: {
      user_pool_id: "ap-southeast-1_Example",
      client_id: "exampleclientid",
      region: "ap-southeast-1",
      domain,
    },
  };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("the hosted UI domain", () => {
  it("expands a bare prefix to the regional host", () => {
    // The console's "Domain name" page shows only the prefix. Treating it as a host
    // yields https://ccoa-dev, which does not resolve.
    const url = logoutUrl(config("ccoa-dev"));
    expect(url).toContain("https://ccoa-dev.auth.ap-southeast-1.amazoncognito.com/logout");
  });

  it("accepts a full host unchanged", () => {
    const url = logoutUrl(config("ccoa-dev.auth.ap-southeast-1.amazoncognito.com"));
    expect(url).toContain("https://ccoa-dev.auth.ap-southeast-1.amazoncognito.com/logout");
    expect(url).not.toContain("amazoncognito.com.auth");
  });

  it("accepts a full URL, and does not double the scheme", () => {
    const url = logoutUrl(config("https://login.example.test"));
    expect(url.startsWith("https://login.example.test/logout")).toBe(true);
  });

  it("tolerates a trailing slash", () => {
    expect(logoutUrl(config("https://login.example.test/"))).toContain(
      "https://login.example.test/logout",
    );
  });

  it("fails loudly when no domain is configured", () => {
    // Better than a redirect to "https://undefined": the message names the runbook.
    expect(() => logoutUrl(config(null))).toThrow(/docs\/18/);
  });
});

describe("sign-out", () => {
  it("sends client_id and logout_uri, which is what Cognito's /logout accepts", () => {
    // Not `post_logout_redirect_uri` + `id_token_hint`: Cognito ignores the OIDC
    // parameters, and oidc-client-ts cannot do this flow at all because the pool exposes
    // no end_session_endpoint.
    const url = new URL(logoutUrl(config("ccoa-dev")));
    expect(url.searchParams.get("client_id")).toBe("exampleclientid");
    expect(url.searchParams.get("logout_uri")).toBe(window.location.origin);
    expect(url.searchParams.get("post_logout_redirect_uri")).toBeNull();
  });
});

describe("the user manager", () => {
  it("points the endpoints at the hosted UI, and the issuer at the pool", () => {
    // The two live on different hosts. Discovering them from the pool's metadata is the
    // usual approach and breaks whenever the domain is absent or added later.
    const manager = buildUserManager(config("ccoa-dev"));
    const { metadata } = manager.settings;
    expect(metadata?.authorization_endpoint).toBe(
      "https://ccoa-dev.auth.ap-southeast-1.amazoncognito.com/oauth2/authorize",
    );
    expect(metadata?.token_endpoint).toBe(
      "https://ccoa-dev.auth.ap-southeast-1.amazoncognito.com/oauth2/token",
    );
    expect(metadata?.jwks_uri).toBe(
      "https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_Example/.well-known/jwks.json",
    );
  });

  it("uses the current origin for the callback, so localhost works unchanged", () => {
    // This is what makes a real pool usable from `npm run dev`: nothing branches on
    // hostname, the URL simply has to be registered on the app client (docs/18 §7).
    const manager = buildUserManager(config("ccoa-dev"));
    expect(manager.settings.redirect_uri).toBe(`${window.location.origin}/callback`);
    expect(redirectUri()).toBe(`${window.location.origin}/callback`);
  });

  it("requests authorization code flow", () => {
    // PKCE is implied by `code` + a public client in oidc-client-ts, and an implicit
    // flow would put an access token in the address bar.
    const manager = buildUserManager(config("ccoa-dev"));
    expect(manager.settings.response_type).toBe("code");
    expect(manager.settings.scope).toContain("openid");
  });
});
