"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, api, getStoredProfileId } from "@/lib/api";
import type { JobOut, Look } from "@/lib/types";

const LOOK_ID_KEY = "synctalk_look_id";
const POLL_INTERVAL_MS = 3000;

export default function LooksPage() {
  const [prompt, setPrompt] = useState("");
  const [look, setLook] = useState<Look | null>(null);
  const [job, setJob] = useState<JobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const profileId = getStoredProfileId();

  useEffect(() => {
    const storedLookId = localStorage.getItem(LOOK_ID_KEY);
    if (storedLookId) {
      api
        .getLook(storedLookId)
        .then((l) => {
          setLook(l);
          setPrompt(l.prompt);
        })
        .catch(() => localStorage.removeItem(LOOK_ID_KEY));
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function pollJob(jobId: string, lookId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await api.getJob(jobId);
        setJob(j);
        if (j.status === "done") {
          clearInterval(pollRef.current!);
          setGenerating(false);
          setLook(await api.getLook(lookId));
        } else if (j.status === "failed") {
          clearInterval(pollRef.current!);
          setGenerating(false);
          setError(j.error ?? "Look generation failed.");
        }
      } catch (err) {
        clearInterval(pollRef.current!);
        setGenerating(false);
        setError(err instanceof ApiError ? err.message : "Lost track of the generation job.");
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (!profileId) return;
    setError(null);
    setGenerating(true);
    setJob(null);
    try {
      const { look_id, job_id } = await api.createLook(profileId, prompt);
      localStorage.setItem(LOOK_ID_KEY, look_id);
      setLook(await api.getLook(look_id));
      pollJob(job_id, look_id);
    } catch (err) {
      setGenerating(false);
      setError(err instanceof ApiError ? err.message : "Could not start generation.");
    }
  }

  async function handleApprove(candidateKey: string) {
    if (!look) return;
    setError(null);
    setApproving(candidateKey);
    try {
      setLook(await api.approveLook(look.id, candidateKey));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve candidate.");
    } finally {
      setApproving(null);
    }
  }

  const isGenerating = generating || (look?.status === "queued" && look.candidate_urls.length === 0);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold">Looks</h1>
        <p className="text-sm text-neutral-500">
          Describe the scene — e.g. &quot;tech home office, condenser mic entering from the
          left, black polo shirt.&quot;
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <form onSubmit={handleGenerate} className="flex flex-col gap-3">
        <textarea
          required
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="rounded-md border border-neutral-300 px-3 py-2"
          placeholder="Scene description…"
        />
        <button
          type="submit"
          disabled={isGenerating}
          className="self-start rounded-md bg-neutral-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {isGenerating ? "Generating…" : look ? "Reroll (generate 4 new candidates)" : "Generate 4 looks"}
        </button>
      </form>

      {isGenerating && (
        <p className="text-sm text-neutral-500">
          {job ? `Rendering… ${job.progress}%` : "Queued…"}
        </p>
      )}

      {look && look.candidate_urls.length > 0 && (
        <div className="grid grid-cols-2 gap-4">
          {look.candidate_keys.map((key, i) => {
            const url = look.candidate_urls[i];
            const isApproved = look.approved_key === key;
            return (
              <div
                key={key}
                className={
                  isApproved
                    ? "overflow-hidden rounded-lg border-2 border-green-500"
                    : "overflow-hidden rounded-lg border border-neutral-200"
                }
              >
                {/* Presigned MinIO/S3 URLs — next/image's remote-pattern allowlist
                    doesn't fit a dev setup with rotating signed query strings. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={url} alt={`Candidate ${i + 1}`} className="aspect-square w-full object-cover" />
                <div className="p-2">
                  <button
                    onClick={() => handleApprove(key)}
                    disabled={approving === key || isApproved}
                    className={
                      isApproved
                        ? "w-full rounded-md bg-green-100 px-3 py-1.5 text-sm font-medium text-green-700"
                        : "w-full rounded-md border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-50"
                    }
                  >
                    {isApproved ? "Approved ✓" : approving === key ? "Approving…" : "Approve"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between border-t border-neutral-200 pt-6">
        <span className="text-sm text-neutral-500">
          {look?.approved_key ? "Look approved." : "Approve a candidate to continue."}
        </span>
        <Link
          href="/create"
          aria-disabled={!look?.approved_key}
          className={
            look?.approved_key
              ? "rounded-md bg-neutral-900 px-4 py-2 text-sm text-white"
              : "pointer-events-none rounded-md bg-neutral-200 px-4 py-2 text-sm text-neutral-400"
          }
        >
          Continue to Create →
        </Link>
      </div>
    </div>
  );
}
