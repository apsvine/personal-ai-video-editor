export type Caption = {
  caption_id: string; original_start: number; original_end: number;
  edited_start: number; edited_end: number; text: string;
};
export type CaptionPlan = {
  schema_version: number; project_id: string; content_checksum: string;
  items: Caption[]; removed: { start: number; end: number }[];
  warnings: { type: string; segment_id: string; word_index: number | null;
    caption_id: string | null; message: string }[];
};

export function activeCaption(plan: CaptionPlan | null, originalTime: number): Caption | null {
  if (!plan || !Number.isFinite(originalTime) || originalTime < 0
    || plan.removed.some(span => span.start <= originalTime && originalTime < span.end)) return null;
  return plan.items.find(item => item.original_start <= originalTime && originalTime < item.original_end) ?? null;
}
