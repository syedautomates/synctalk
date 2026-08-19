"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api, getStoredProfileId } from "@/lib/api";
import type { Look, VideoRequestT } from "@/lib/types";

const LOOK_ID_KEY = "synctalk_look_id";
const POLL_INTERVAL_MS = 5000;

const STAGE_LABELS: Record<string, string> = {
  orchestrating: "Designing the delivery (Claude)…",
  tts: "Synthesizing voice (ElevenLabs)…",
  rendering: "Rendering talking-head video…",
  upscaling: "Upscaling to 4K…",
  done: "Done.",
  failed: "Failed.",
};

const STAGE_ORDER = ["orchestrating", "tts", "rendering", "upscaling", "done"];

export default function CreatePage() {
  const [emotionBrief, setEmotionBrief] = useState("");
  const [script, setScript] = useState("");
  const [video, setVideo] = useState<VideoRequestT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [elapsedS, setElapsedS] = useState(0);
  const [look, setLook] = useState<Look | null>(null);
  const [lookError, setLookError] = useState<string | null>(null);
  const [lookChecked, setLookChecked] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const profileId = getStoredProfileId();
  // Only used post-mount (see effect below) — a stored look_id alone doesn't mean the
  // look was actually approved, so this is not treated as ground truth by itself.
  const lookId = typeof window !== "undefined" ? localStorage.getItem(LOOK_ID_KEY) : null;

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (elapsedRef.current) clearInterval(elapsedRef.current);
    };
  }, []);

  useEffect(() => {
    if (!lookId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no lookId means no fetch to await; this is the "nothing to check" terminal state, set synchronously
      setLookChecked(true);
      return;
    }
    api
      .getLook(lookId)
      .then((l) => setLook(l))
      .catch((err) => {
        setLookError(err instanceof ApiError ? err.message : "Could not load the approved look.");
      })
      .finally(() => setLookChecked(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only fetch keyed on lookId, not a dependency that should re-trigger
  }, []);

  function pollVideo(videoId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const v = await api.getVideo(videoId);
        setVideo(v);
        if (v.status === "done" || v.status === "failed") {
          clearInterval(pollRef.current!);
          if (elapsedRef.current) clearInterval(elapsedRef.current);
        }
      } catch (err) {
        clearInterval(pollRef.current!);
        if (elapsedRef.current) clearInterval(elapsedRef.current);
        setError(err instanceof ApiError ? err.message : "Lost track of the video request.");
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!profileId || !lookId) return;
    setError(null);
    setSubmitting(true);
    setElapsedS(0);
    try {
      const { video_request_id } = await api.createVideo(profileId, lookId, emotionBrief, script);
      const v = await api.getVideo(video_request_id);
      setVideo(v);
      elapsedRef.current = setInterval(() => setElapsedS((s) => s + 1), 1000);
      pollVideo(video_request_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create video.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!lookChecked) {
    return <p className="text-sm text-neutral-500">Checking your approved look…</p>;
  }

  if (!lookId || !look?.approved_key) {
    return (
      <p className="text-sm text-neutral-500">
        {lookError ??
          "No approved look yet — go back to the Looks step and approve one first."}
      </p>
    );
  }

  const inProgress = video && video.status !== "done" && video.status !== "failed";

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold">Create</h1>
        <p className="text-sm text-neutral-500">
          Describe the emotion/movement, provide the script, and generate the video.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {!video && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">Emotion / movement brief</label>
            <textarea
              required
              rows={3}
              value={emotionBrief}
              onChange={(e) => setEmotionBrief(e.target.value)}
              className="rounded-md border border-neutral-300 px-3 py-2"
              placeholder="e.g. casual and funny, relaxed energy"
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium">Script</label>
            <textarea
              required
              rows={8}
              value={script}
              onChange={(e) => setScript(e.target.value)}
              className="rounded-md border border-neutral-300 px-3 py-2"
              placeholder="The exact words to speak…"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="self-start rounded-md bg-neutral-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {submitting ? "Starting…" : "Generate video"}
          </button>
        </form>
      )}

      {video && (
        <div className="flex flex-col gap-4">
          <ol className="flex flex-wrap gap-2 text-sm">
            {STAGE_ORDER.map((stage) => {
              const stageIndex = STAGE_ORDER.indexOf(video.status);
              const thisIndex = STAGE_ORDER.indexOf(stage);
              const done = video.status === "done" || thisIndex < stageIndex;
              const active = stage === video.status;
              return (
                <li
                  key={stage}
                  className={
                    active
                      ? "rounded-full bg-neutral-900 px-3 py-1 text-white"
                      : done
                        ? "rounded-full bg-green-100 px-3 py-1 text-green-700"
                        : "rounded-full bg-neutral-100 px-3 py-1 text-neutral-500"
                  }
                >
                  {STAGE_LABELS[stage] ?? stage}
                </li>
              );
            })}
          </ol>

          {inProgress && (
            <p className="text-sm text-neutral-500">
              {STAGE_LABELS[video.status] ?? video.status} — {Math.floor(elapsedS / 60)}m{" "}
              {elapsedS % 60}s elapsed. (No verified throughput benchmark yet for this
              deployment — see DECISIONS.md — so this is an honest elapsed-time counter,
              not a promised ETA. Expect several minutes.)
            </p>
          )}

          {video.status === "failed" && (
            <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
              {video.error ?? "Video generation failed."}
            </p>
          )}

          {video.status === "done" && (
            <div className="flex flex-col gap-4">
              {video.video_4k_url && (
                <video controls className="w-full rounded-lg" src={video.video_4k_url} />
              )}
              <div className="flex gap-3">
                {video.video_4k_url && (
                  <a
                    href={video.video_4k_url}
                    className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white"
                  >
                    Download 4K
                  </a>
                )}
                {video.video_720_url && (
                  <a
                    href={video.video_720_url}
                    className="rounded-md border border-neutral-300 px-4 py-2 text-sm"
                  >
                    Download 720p
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
