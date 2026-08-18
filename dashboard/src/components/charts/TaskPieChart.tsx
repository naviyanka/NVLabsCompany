import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

export interface TaskStatusData {
  name: string;
  value: number;
  color: string;
}

export interface TaskPieChartProps {
  data: TaskStatusData[];
  className?: string;
}

const DEFAULT_COLORS: Record<string, string> = {
  pending: '#f59e0b',
  in_progress: '#6366f1',
  completed: '#10b981',
  failed: '#f43f5e',
  assigned: '#3b82f6',
  cancelled: '#6b7280',
};

export function TaskPieChart({ data, className = '' }: TaskPieChartProps) {
  const chartData = data.map((item) => ({
    ...item,
    color: item.color || DEFAULT_COLORS[item.name] || '#6b7280',
  }));

  return (
    <div className={`w-full h-64 ${className}`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={80}
            paddingAngle={2}
            dataKey="value"
            nameKey="name"
          >
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
          />
          <Legend
            verticalAlign="bottom"
            height={36}
            formatter={(value: string) => (
              <span className="text-xs text-gray-600 capitalize">{value.replace('_', ' ')}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
