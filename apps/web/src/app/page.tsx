"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  getStoredProfileId,
  getToken,
  setStoredProfileId,
  setToken,
} from "@/lib/api";

export default function SetupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  // Must default to false on both server and client — localStorage doesn't exist during
  // SSR, so reading it in a lazy initializer would make the client's first hydration
  // render diverge from the server-rendered HTML. The real value is set from the
  // post-mount effect below instead.
  const [loggedIn, setLoggedIn] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [existingProfileId, setExistingProfileId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // SSR-safe: real localStorage value is only knowable post-mount, see initializer comment above
    if (getToken()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoggedIn(true);
    }
    if (getToken() && getStoredProfileId()) {
      router.replace("/train");
    }
  }, [router]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { access_token } = await api.login(email);
      setToken(access_token);
      setLoggedIn(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateProfile(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const profile = await api.createProfile(profileName);
      setStoredProfileId(profile.id);
      router.push("/train");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create profile.");
    } finally {
      setBusy(false);
    }
  }

  async function handleUseExisting(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.getProfile(existingProfileId.trim());
      setStoredProfileId(existingProfileId.trim());
      router.push("/train");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load that profile.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-8 px-6">
      <div>
        <h1 className="text-2xl font-semibold">SyncTalk</h1>
        <p className="mt-1 text-sm text-neutral-500">Avatar Studio — talking-head video pipeline.</p>
      </div>

      {error && (
        <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {!loggedIn ? (
        <form onSubmit={handleLogin} className="flex flex-col gap-3">
          <label className="text-sm font-medium">Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-2"
            placeholder="you@example.com"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50"
          >
            {busy ? "Logging in…" : "Log in"}
          </button>
        </form>
      ) : (
        <div className="flex flex-col gap-6">
          <form onSubmit={handleCreateProfile} className="flex flex-col gap-3">
            <label className="text-sm font-medium">Create a new avatar profile</label>
            <input
              required
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              className="rounded-md border border-neutral-300 px-3 py-2"
              placeholder="Profile name"
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50"
            >
              {busy ? "Creating…" : "Create profile"}
            </button>
          </form>

          <div className="flex items-center gap-3 text-xs text-neutral-400">
            <div className="h-px flex-1 bg-neutral-200" />
            or
            <div className="h-px flex-1 bg-neutral-200" />
          </div>

          <form onSubmit={handleUseExisting} className="flex flex-col gap-3">
            <label className="text-sm font-medium">Use an existing profile ID</label>
            <input
              required
              value={existingProfileId}
              onChange={(e) => setExistingProfileId(e.target.value)}
              className="rounded-md border border-neutral-300 px-3 py-2 font-mono text-sm"
              placeholder="00000000-0000-0000-0000-000000000000"
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-md border border-neutral-300 px-4 py-2 disabled:opacity-50"
            >
              {busy ? "Loading…" : "Continue"}
            </button>
          </form>
        </div>
      )}
    </main>
  );
}
