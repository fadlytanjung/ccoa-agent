import { Link, Navigate, Route, Routes } from "react-router-dom";
import { Loader2, LogIn, ShieldAlert } from "lucide-react";

import { AssistantLayout } from "./components/AssistantLayout";
import { BrandMark } from "./components/Brand";
import { Button } from "@/components/ui/button";
import { useAuth } from "./auth/useAuth";

/**
 * Routing and the authentication gate — docs/07 §3.3, §3.10.
 *
 * Everything behind the gate is one workspace, but a **conversation is addressable**:
 * `/threads/:threadId` is what makes it bookmarkable and shareable, and what removes
 * thread selection from React state where a late list refresh could race it.
 *
 * `/callback` is consumed inside `AuthProvider` before anything renders — the route
 * exists here so a full page load on that path is not a 404 while the code is exchanged.
 */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid h-full place-items-center bg-background px-md">
      <div className="w-full max-w-[24rem] text-center">{children}</div>
    </div>
  );
}

function SignIn() {
  const { signIn } = useAuth();
  return (
    <Shell>
      <BrandMark className="mx-auto size-12" />
      <h1 className="mt-md text-heading-4 text-foreground">CCOA Assistant</h1>
      <p className="mt-xxs text-body-sm text-text-secondary">
        Sign in with your contact-centre account to continue.
      </p>
      <Button className="mt-lg w-full" onClick={signIn} data-testid="sign-in">
        <LogIn />
        Sign in
      </Button>
    </Shell>
  );
}

export default function App() {
  const { status, error } = useAuth();

  if (status === "loading") {
    return (
      <Shell>
        <Loader2
          className="mx-auto size-6 animate-spin text-text-tertiary motion-reduce:animate-none"
          aria-hidden
        />
        <p className="mt-sm text-body-sm text-text-secondary" data-testid="loading">
          Starting…
        </p>
      </Shell>
    );
  }

  if (status === "error") {
    return (
      <Shell>
        <div role="alert">
          <ShieldAlert className="mx-auto size-6 text-semantic-danger" aria-hidden />
          <p className="mt-sm text-body-medium text-foreground">
            The assistant could not start.
          </p>
          <p className="mt-xxs text-body-sm text-text-secondary">{error}</p>
          {/* Not a dead end. Most causes here are transient or fixed elsewhere — the
              backend was still starting, a pool was created a moment ago — and a reload
              is the honest retry for all of them. */}
          <Button
            variant="secondary"
            className="mt-lg"
            onClick={() => window.location.assign("/")}
            data-testid="retry"
          >
            Try again
          </Button>
        </div>
      </Shell>
    );
  }

  if (status === "anonymous") return <SignIn />;

  return (
    <Routes>
      <Route path="/" element={<AssistantLayout />} />
      <Route path="/threads/:threadId" element={<AssistantLayout />} />
      {/* The code has already been consumed by now; land the agent in the workspace. */}
      <Route path="/callback" element={<Navigate to="/" replace />} />
      <Route
        path="*"
        element={
          <Shell>
            <BrandMark className="mx-auto size-10" />
            {/* Still an h1 named for the product: it is the heading every route shares,
                and the one screen-reader users navigate by. */}
            <h1 className="mt-md text-heading-5 text-foreground">CCOA Assistant</h1>
            <p className="mt-xxs text-body-sm text-text-secondary">
              That page does not exist.
            </p>
            <Button asChild variant="secondary" className="mt-lg">
              <Link to="/">Back to the assistant</Link>
            </Button>
          </Shell>
        }
      />
    </Routes>
  );
}
