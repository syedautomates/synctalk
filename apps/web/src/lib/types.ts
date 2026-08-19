export interface ChecklistItem {
  required: number;
  uploaded: number;
  passed: number;
  ok: boolean;
}

export interface ReadinessChecklist {
  photos: ChecklistItem;
  reference_video: ChecklistItem;
  voice_sample: ChecklistItem;
  consent: boolean;
  ready: boolean;
}

export interface AssetOut {
  id: string;
  kind: string;
  s3_key: string;
  meta: Record<string, unknown>;
  validation: string;
  validation_errors: string[] | null;
}

export interface Profile {
  id: string;
  user_id: string;
  name: string;
  status: string;
  consent_confirmed_at: string | null;
  elevenlabs_voice_id: string | null;
  primary_ref_image_key: string | null;
  created_at: string;
  assets: AssetOut[];
  checklist: ReadinessChecklist;
}

export interface Look {
  id: string;
  profile_id: string;
  prompt: string;
  garment_asset_id: string | null;
  candidate_keys: string[];
  candidate_urls: string[];
  approved_key: string | null;
  approved_url: string | null;
  status: string;
  created_at: string;
}

export interface JobOut {
  id: string;
  type: string;
  status: "queued" | "leased" | "running" | "done" | "failed";
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

export interface VideoRequestT {
  id: string;
  profile_id: string;
  look_id: string;
  emotion_brief: string;
  script: string;
  orchestrator_output: {
    tagged_script: string;
    style_prompt: string;
    negative_notes: string;
    emotion_summary: string;
  } | null;
  status: string;
  error: string | null;
  cost_ledger: Record<string, number>;
  created_at: string;
  video_720_url: string | null;
  video_4k_url: string | null;
}
