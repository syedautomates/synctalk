"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, api, getStoredProfileId, uploadToPresignedUrl } from "@/lib/api";
import type { Profile } from "@/lib/types";

type Kind = "photo" | "reference_video" | "voice_sample";

const KIND_LABELS: Record<Kind, string> = {
  photo: "Zoomed-in photos (2–3 needed)",
  reference_video: "Reference video (30–60s, face + hands visible)",
  voice_sample: "Voice sample (≥30s of speech)",
};

const KIND_ACCEPT: Record<Kind, string> = {
  photo: "image/*",
  reference_video: "video/*",
  voice_sample: "audio/*",
};

// Upload `kind` values are singular (matches the API's AssetKind); the checklist's
// "photos" field is plural. Everything else lines up 1:1.
const CHECKLIST_KEY: Record<Kind, "photos" | "reference_video" | "voice_sample"> = {
  photo: "photos",
  reference_video: "reference_video",
  voice_sample: "voice_sample",
};

export default function TrainPage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<Kind | null>(null);
  const [cloning, setCloning] = useState(false);

  const profileId = getStoredProfileId();

  async function refresh() {
    if (!profileId) return;
    try {
      setProfile(await api.getProfile(profileId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load profile.");
    }
  }

  useEffect(() => {
    // Fetch-on-mount: refresh() is async, so its setState calls run in a later
    // microtask, not synchronously within this effect body — a standard pattern, not
    // the anti-pattern react-hooks/set-state-in-effect targets.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    // refresh() is also called after every mutation below (upload, consent, voice
    // clone), so it's intentionally not in the dependency array — it isn't derived
    // from props/state that would need to re-trigger this mount-only fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleUpload(kind: Kind, file: File) {
    if (!profileId) return;
    setError(null);
    setUploading(kind);
    try {
      const { upload_url, s3_key } = await api.presignUpload(
        profileId,
        kind,
        file.name,
        file.type || "application/octet-stream",
      );
      await uploadToPresignedUrl(upload_url, file);
      await api.createAsset(profileId, kind, s3_key);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(null);
    }
  }

  async function handleConsent(confirmed: boolean) {
    if (!profileId || !confirmed) return;
    setError(null);
    try {
      await api.confirmConsent(profileId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record consent.");
    }
  }

  async function handleCloneVoice() {
    if (!profileId) return;
    setError(null);
    setCloning(true);
    try {
      await api.createVoice(profileId, false);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Voice clone failed.");
    } finally {
      setCloning(false);
    }
  }

  if (!profile) {
    return <p className="text-neutral-500">{error ?? "Loading profile…"}</p>;
  }

  const { checklist } = profile;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold">Train — {profile.name}</h1>
        <p className="text-sm text-neutral-500">
          Upload your reference photos, video, and voice sample.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {(["photo", "reference_video", "voice_sample"] as Kind[]).map((kind) => {
        const item = checklist[CHECKLIST_KEY[kind]];
        const assetsOfKind = profile.assets.filter((a) => a.kind === kind);
        return (
          <div key={kind} className="rounded-lg border border-neutral-200 p-4">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">{KIND_LABELS[kind]}</h2>
              <span
                className={
                  item.ok
                    ? "rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
                    : "rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600"
                }
              >
                {item.passed}/{item.required} passed{item.ok ? " ✓" : ""}
              </span>
            </div>

            <input
              type="file"
              accept={KIND_ACCEPT[kind]}
              disabled={uploading === kind}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(kind, file);
                e.target.value = "";
              }}
              className="mt-3 text-sm"
            />
            {uploading === kind && (
              <p className="mt-1 text-sm text-neutral-500">Uploading & validating…</p>
            )}

            {assetsOfKind.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1 text-sm">
                {assetsOfKind.map((asset) => (
                  <li key={asset.id}>
                    <span
                      className={
                        asset.validation === "passed"
                          ? "text-green-700"
                          : asset.validation === "failed"
                            ? "text-red-700"
                            : "text-neutral-500"
                      }
                    >
                      {asset.validation}
                    </span>
                    {asset.validation_errors && (
                      <ul className="ml-4 list-disc text-red-600">
                        {asset.validation_errors.map((e, i) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}

      <div className="rounded-lg border border-neutral-200 p-4">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={checklist.consent}
            disabled={checklist.consent}
            onChange={(e) => handleConsent(e.target.checked)}
            className="mt-1"
          />
          <span className="text-sm">
            I confirm that the photos, video, and voice sample I&apos;m uploading are of
            myself, and that I own the rights to use my own likeness and voice in this
            application. I understand this data will be used to generate videos of me
            speaking scripts I provide.
          </span>
        </label>
      </div>

      <div className="rounded-lg border border-neutral-200 p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">Voice clone</h2>
          <span className="text-sm text-neutral-500">
            {profile.elevenlabs_voice_id ? "Cloned ✓" : "Not cloned — using default voice"}
          </span>
        </div>
        <button
          onClick={handleCloneVoice}
          disabled={!checklist.consent || !checklist.voice_sample.ok || cloning}
          className="mt-3 rounded-md bg-neutral-900 px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          {cloning ? "Cloning…" : profile.elevenlabs_voice_id ? "Re-clone voice" : "Clone my voice"}
        </button>
      </div>

      <div className="flex items-center justify-between border-t border-neutral-200 pt-6">
        <span className="text-sm text-neutral-500">
          {checklist.ready ? "Profile ready." : "Complete every step above to continue."}
        </span>
        <Link
          href="/looks"
          aria-disabled={!checklist.ready}
          className={
            checklist.ready
              ? "rounded-md bg-neutral-900 px-4 py-2 text-sm text-white"
              : "pointer-events-none rounded-md bg-neutral-200 px-4 py-2 text-sm text-neutral-400"
          }
        >
          Continue to Looks →
        </Link>
      </div>
    </div>
  );
}
