export type Word = { text: string; start: number; end: number; confidence: number | null };
export type Segment = {
  segment_id: string; start: number; end: number; text: string; raw_text: string;
  edited: boolean; words?: Word[];
};
export type Review = {
  schema_version: number; project_id: string; source_transcript_checksum: string;
  language: string; timing_quality: string;
  override_state: 'none' | 'applied' | 'stale' | 'invalid'; override_message: string | null;
  segments: Segment[];
};

export function activeSegment(segments: Segment[], time: number) {
  // Half-open intervals keep gaps unhighlighted and adjacent boundaries unambiguous.
  return segments.find(s => s.start <= time && time < s.end)?.segment_id ?? null;
}

export function timedWords(segment: Segment): Word[] {
  const words = segment.words;
  let previous = segment.start;
  if (!words?.length || !words.every(word => {
    const valid = Number.isFinite(word.start) && Number.isFinite(word.end)
      && previous <= word.start && word.start <= word.end && word.end <= segment.end;
    previous = word.end;
    return valid;
  })) return [];
  return words;
}

export function seekVideo(video: HTMLVideoElement | null, time: number) {
  if (!video || !Number.isFinite(time) || time < 0) return;
  video.currentTime = Number.isFinite(video.duration) ? Math.min(time, video.duration) : time;
}
