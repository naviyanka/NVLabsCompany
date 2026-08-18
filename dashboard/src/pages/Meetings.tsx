import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { Calendar, Users, Clock } from 'lucide-react';

interface Meeting {
  id: string;
  title: string;
  type: 'standup' | 'retrospective' | 'planning' | 'review';
  attendees: number;
  scheduledAt: string;
  status: 'scheduled' | 'in_progress' | 'completed';
}

const sampleMeetings: Meeting[] = [
  { id: '1', title: 'Daily Standup', type: 'standup', attendees: 8, scheduledAt: '2024-01-15T09:00:00Z', status: 'completed' },
  { id: '2', title: 'Sprint Retrospective', type: 'retrospective', attendees: 12, scheduledAt: '2024-01-15T14:00:00Z', status: 'scheduled' },
  { id: '3', title: 'Sprint Planning', type: 'planning', attendees: 10, scheduledAt: '2024-01-16T10:00:00Z', status: 'scheduled' },
  { id: '4', title: 'Architecture Review', type: 'review', attendees: 5, scheduledAt: '2024-01-16T15:00:00Z', status: 'scheduled' },
];

export function Meetings() {
  const meetings = sampleMeetings;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Meetings</h1>
        <p className="text-sm text-gray-500 mt-1">Agent coordination meetings and sync sessions</p>
      </div>

      {meetings.length === 0 ? (
        <EmptyState
          icon={<Calendar size={48} />}
          title="No meetings scheduled"
          description="Meetings will appear here when scheduled."
        />
      ) : (
        <div className="space-y-3">
          {meetings.map((meeting) => (
            <Card key={meeting.id}>
              <div className="flex items-center justify-between">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-primary-100 text-primary-600 rounded-lg flex items-center justify-center">
                    <Calendar size={16} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">{meeting.title}</h3>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                      <Badge variant="default" size="sm">{meeting.type}</Badge>
                      <span className="flex items-center gap-1">
                        <Users size={12} />
                        {meeting.attendees} attendees
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock size={12} />
                        {new Date(meeting.scheduledAt).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </div>
                <Badge
                  variant={meeting.status === 'completed' ? 'success' : meeting.status === 'in_progress' ? 'info' : 'default'}
                  size="sm"
                >
                  {meeting.status}
                </Badge>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
