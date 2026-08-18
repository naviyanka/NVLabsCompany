import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Settings as SettingsIcon } from 'lucide-react';

export function Settings() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-1">System configuration and preferences</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">API Configuration</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">API Base URL</label>
              <input
                type="text"
                defaultValue="http://localhost:8000"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Polling Interval (seconds)</label>
              <input
                type="number"
                defaultValue={30}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
          </div>
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Display Preferences</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-900">Auto-refresh</p>
                <p className="text-xs text-gray-500">Automatically refresh dashboard data</p>
              </div>
              <input type="checkbox" defaultChecked className="h-4 w-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500" />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-900">Show notifications</p>
                <p className="text-xs text-gray-500">Display in-app notification alerts</p>
              </div>
              <input type="checkbox" defaultChecked className="h-4 w-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500" />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-900">Compact mode</p>
                <p className="text-xs text-gray-500">Reduce spacing and card sizes</p>
              </div>
              <input type="checkbox" className="h-4 w-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500" />
            </div>
          </div>
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">System</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Version</span>
              <span className="text-sm text-gray-900 font-mono">0.1.0</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Environment</span>
              <span className="text-sm text-gray-900 font-mono">development</span>
            </div>
          </div>
          <div className="mt-4 pt-4 border-t border-gray-200">
            <Button variant="secondary" size="sm" icon={<SettingsIcon size={14} />}>
              Reset to Defaults
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
