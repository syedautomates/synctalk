import type { JobOut, Look, Profile, VideoRequestT } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const TOKEN_KEY = "synctalk_token";
const PROFILE_ID_KEY = "synctalk_profile_id";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(PROFILE_ID_KEY);
}

export function getStoredProfileId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(PROFILE_ID_KEY);
}

export function setStoredProfileId(id: string): void {
  localStorage.setItem(PROFILE_ID_KEY, id);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && typeof options.body === "string") {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ? JSON.stringify(body.detail) : detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function uploadToPresignedUrl(url: string, file: File): Promise<void> {
  const res = await fetch(url, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type },
  });
  if (!res.ok) {
    throw new ApiError(res.status, `Upload to storage failed: ${res.statusText}`);
  }
}

export const api = {
  login: (email: string) =>
    request<{ access_token: string; token_type: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  createProfile: (name: string) =>
    request<Profile>("/api/v1/profiles", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  getProfile: (id: string) => request<Profile>(`/api/v1/profiles/${id}`),

  presignUpload: (profileId: string, kind: string, filename: string, contentType: string) =>
    request<{ upload_url: string; s3_key: string }>(
      `/api/v1/profiles/${profileId}/uploads/presign`,
      {
        method: "POST",
        body: JSON.stringify({ kind, filename, content_type: contentType }),
      },
    ),

  createAsset: (profileId: string, kind: string, s3Key: string) =>
    request<Profile>(`/api/v1/profiles/${profileId}/assets`, {
      method: "POST",
      body: JSON.stringify({ kind, s3_key: s3Key }),
    }),

  confirmConsent: (profileId: string) =>
    request<Profile>(`/api/v1/profiles/${profileId}/consent`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    }),

  createVoice: (profileId: string, useReferenceVideo: boolean) =>
    request<Profile>(`/api/v1/profiles/${profileId}/voice`, {
      method: "POST",
      body: JSON.stringify({ use_reference_video: useReferenceVideo }),
    }),

  createLook: (profileId: string, prompt: string) =>
    request<{ look_id: string; job_id: string }>(`/api/v1/profiles/${profileId}/looks`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),

  getLook: (lookId: string) => request<Look>(`/api/v1/looks/${lookId}`),

  approveLook: (lookId: string, candidateKey: string) =>
    request<Look>(`/api/v1/looks/${lookId}/approve`, {
      method: "POST",
      body: JSON.stringify({ candidate_key: candidateKey }),
    }),

  getJob: (jobId: string) => request<JobOut>(`/api/v1/jobs/${jobId}`),

  createVideo: (profileId: string, lookId: string, emotionBrief: string, script: string) =>
    request<{ video_request_id: string; job_id: string }>("/api/v1/videos", {
      method: "POST",
      body: JSON.stringify({
        profile_id: profileId,
        look_id: lookId,
        emotion_brief: emotionBrief,
        script,
      }),
    }),

  getVideo: (videoId: string) => request<VideoRequestT>(`/api/v1/videos/${videoId}`),
};
