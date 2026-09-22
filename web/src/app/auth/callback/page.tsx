"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

/** Google redirects here with the tokens in the URL *fragment* (never sent to any server or logged). */
export default function OAuthCallback() {
  const { acceptTokens } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const access_token = params.get("access_token");
    const refresh_token = params.get("refresh_token");
    window.history.replaceState(null, "", window.location.pathname); // scrub tokens from the address bar / history
    if (!access_token || !refresh_token) {
      setError("Sign-in didn't complete. Please try again.");
      return;
    }
    acceptTokens({ access_token, refresh_token }).then(() => router.replace("/"), () => setError("Sign-in failed. Please try again."));
  }, [acceptTokens, router]);

  return <div className="login">{error ? <div className="error" role="alert">{error}</div> : <span className="muted">Signing you in…</span>}</div>;
}
