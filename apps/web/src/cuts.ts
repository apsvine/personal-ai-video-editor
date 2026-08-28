export type Candidate = {
  cut_id: string; start: number; end: number; reason: string;
  decision: 'pending' | 'accept' | 'reject';
};
export type CutReviewData = {
  schema_version: number; project_id: string; source_cuts_checksum: string;
  override_state: 'none' | 'applied' | 'stale' | 'invalid'; override_message: string | null;
  warnings: string[]; candidates: Candidate[];
  effective: { source_duration: number; effective_duration: number; time_removed: number };
};
export const decisionLabel = (decision: Candidate['decision']) =>
  ({ pending: 'pending', accept: 'accepted', reject: 'rejected' })[decision];
