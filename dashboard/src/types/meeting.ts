export interface MeetingTranscriptEntry {
  speaker: string;
  role?: string;
  avatar?: string;
  timestamp?: string;
  text: string;
}

export interface MeetingSyncItem {
  id: string;
  title: string;
  type: string;
  status: 'scheduled' | 'in_progress' | 'completed';
  scheduled_at: string;
  duration_minutes?: number;
  attendees: string[];
  summary?: string;
  action_items?: string[];
  transcript?: MeetingTranscriptEntry[];
  consensus_score?: number;
  created_at?: string;
}
