"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Power,
  Clock,
  SlidersHorizontal,
  CheckCircle,
  XCircle,
  Save,
  ShieldAlert,
  PhoneCall,
  Monitor,
  Plus,
  Trash2,
  Radio,
  Users,
  Layers,
  CalendarDays,
  ChevronDown,
  MessageSquare,
} from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import type {
  SystemSettings,
  BusinessHours,
  HolidayEntry,
  QueueThresholds,
  DispatcherSettings,
  SimulationScenario,
} from "@/types";

interface OperatorConsoleProps {
  settings: SystemSettings | null;
  timezones: string[];
  callMode: string;
  scenarios: SimulationScenario[];
  onCallModeChange: (mode: string) => void;
  onSetSystemEnabled: (enabled: boolean) => Promise<void>;
  onUpdateBusinessHours: (businessHours: BusinessHours) => Promise<void>;
  onUpdateQueueThresholds: (thresholds: QueueThresholds) => Promise<void>;
  onUpdateDispatcherSettings: (dispatcherSettings: DispatcherSettings) => Promise<void>;
  onSetMockMode: (enabled: boolean, mockPhone: string) => Promise<void>;
  onUpdateDailyReport: (config: { enabled: boolean; webhook_url: string; hour: number; timezone: string }) => Promise<void>;
  onSendTestDailyReport: () => Promise<{ sent: boolean } | null>;
  onSetQueueSource: (source: string) => Promise<void>;
  onSetPatientSource: (source: string) => Promise<void>;
  onSetActiveScenario: (id: string) => Promise<void>;
}

export function OperatorConsole({
  settings,
  timezones,
  callMode,
  scenarios,
  onCallModeChange,
  onSetSystemEnabled,
  onUpdateBusinessHours,
  onUpdateQueueThresholds,
  onUpdateDispatcherSettings,
  onSetMockMode,
  onUpdateDailyReport,
  onSendTestDailyReport,
  onSetQueueSource,
  onSetPatientSource,
  onSetActiveScenario,
}: OperatorConsoleProps) {
  const [businessHoursForm, setBusinessHoursForm] = useState<BusinessHours>({
    start_time: "08:00",
    end_time: "17:00",
    enabled: false,
    timezone: "America/New_York",
    days_of_week: [0, 1, 2, 3, 4],  // Mon-Fri
    holidays: [],
  });

  const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  const [thresholdsForm, setThresholdsForm] = useState<QueueThresholds>({
    calls_waiting_threshold: 1,
    holdtime_threshold_seconds: 30,
    stable_polls_required: 3,
  });

  const [dispatcherForm, setDispatcherForm] = useState<DispatcherSettings>({
    poll_interval: 10,
    dispatch_timeout: 30,
    max_attempts: 3,
    min_hours_between: 6,
  });

  const [mockPhoneInput, setMockPhoneInput] = useState(settings?.mock_phone || "");
  const [holidayEditorOpen, setHolidayEditorOpen] = useState(false);
  const [dailyReportForm, setDailyReportForm] = useState({
    enabled: settings?.daily_report?.enabled ?? false,
    webhook_url: settings?.daily_report?.webhook_url ?? "",
    hour: settings?.daily_report?.hour ?? 7,
    timezone: settings?.daily_report?.timezone ?? "America/Los_Angeles",
  });
  const [dailyReportSaving, setDailyReportSaving] = useState(false);
  const [dailyReportTestStatus, setDailyReportTestStatus] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setBusinessHoursForm(settings.business_hours);
      setThresholdsForm(settings.queue_thresholds);
      setDispatcherForm(settings.dispatcher_settings);
      setMockPhoneInput(settings.mock_phone || "");
      if (settings.daily_report) {
        setDailyReportForm({
          enabled: settings.daily_report.enabled,
          webhook_url: settings.daily_report.webhook_url,
          hour: settings.daily_report.hour,
          timezone: settings.daily_report.timezone,
        });
      }
    }
  }, [settings]);

  const handleBusinessHoursSubmit = async () => {
    await onUpdateBusinessHours(businessHoursForm);
  };

  const handleDailyReportSave = async () => {
    setDailyReportSaving(true);
    setDailyReportTestStatus(null);
    try {
      await onUpdateDailyReport(dailyReportForm);
    } finally {
      setDailyReportSaving(false);
    }
  };

  const handleDailyReportTest = async () => {
    setDailyReportTestStatus("Sending...");
    try {
      const result = await onSendTestDailyReport();
      setDailyReportTestStatus(
        result?.sent ? "Test report sent successfully" : "Failed to send (check webhook URL and logs)"
      );
    } catch {
      setDailyReportTestStatus("Failed to send test report");
    }
    setTimeout(() => setDailyReportTestStatus(null), 6000);
  };

  const handleAddHoliday = () => {
    const next: HolidayEntry = {
      date: "",
      name: "",
      recurring: true,
    };
    setBusinessHoursForm({
      ...businessHoursForm,
      holidays: [...(businessHoursForm.holidays || []), next],
    });
    setHolidayEditorOpen(true);
  };

  const handleUpdateHoliday = (index: number, patch: Partial<HolidayEntry>) => {
    const holidays = [...(businessHoursForm.holidays || [])];
    holidays[index] = { ...holidays[index], ...patch };
    setBusinessHoursForm({ ...businessHoursForm, holidays });
  };

  const handleRemoveHoliday = (index: number) => {
    const holidays = [...(businessHoursForm.holidays || [])];
    holidays.splice(index, 1);
    setBusinessHoursForm({ ...businessHoursForm, holidays });
  };

  const handleBusinessHoursEnabledChange = async (enabled: boolean) => {
    const newForm = { ...businessHoursForm, enabled };
    setBusinessHoursForm(newForm);
    await onUpdateBusinessHours(newForm);
  };

  const handleThresholdsSubmit = async () => {
    await onUpdateQueueThresholds(thresholdsForm);
  };

  const handleDispatcherSubmit = async () => {
    await onUpdateDispatcherSettings(dispatcherForm);
  };

  if (!settings) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-sm text-muted-foreground">Loading settings...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* System Control */}
      <div className="flex items-center justify-between rounded-lg border p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Power className="h-4 w-4" />
          </div>
          <div>
            <p className="text-sm font-medium flex items-center gap-1.5">
              System Status
              <InfoTooltip content="Master switch for the outbound calling system. When disabled, the dispatcher will not place any calls regardless of other settings." />
            </p>
            <p className="text-xs text-muted-foreground">
              {settings.system_enabled
                ? "Active — calls can be placed"
                : "Disabled — no calls will be placed"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {settings.can_make_calls ? (
            <Badge variant="success" className="flex items-center gap-1">
              <CheckCircle className="h-3 w-3" />
              Ready
            </Badge>
          ) : (
            <Badge variant="outline" className="flex items-center gap-1 text-muted-foreground">
              <XCircle className="h-3 w-3" />
              Blocked
            </Badge>
          )}
          <Switch
            checked={settings.system_enabled}
            onCheckedChange={onSetSystemEnabled}
          />
        </div>
      </div>

      <Separator />

      {/* Call Mode */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <PhoneCall className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-sm font-medium">Call Mode</h4>
          <InfoTooltip content="Web mode simulates calls in your browser — you speak as the patient using your microphone. Twilio mode places real phone calls to actual phone numbers." />
        </div>
        <p className="text-xs text-muted-foreground">
          Choose how outbound calls are placed. Web mode uses the browser microphone to simulate the patient. Twilio mode dials a real phone number via Twilio and streams audio between the phone and the AI.
        </p>
        <div className="flex items-center gap-4">
          <Select value={callMode} onValueChange={onCallModeChange}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="web">
                <span className="flex items-center gap-2">
                  <Monitor className="h-4 w-4" />
                  Web (Browser Audio)
                </span>
              </SelectItem>
              <SelectItem value="twilio">
                <span className="flex items-center gap-2">
                  <PhoneCall className="h-4 w-4" />
                  Twilio (Real Phone Call)
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
          {callMode === "twilio" && (
            <Badge variant="outline" className="text-orange-600 border-orange-600">
              Real calls — charges apply
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {callMode === "web"
            ? "Audio streams between your browser and OpenAI. You speak as the patient through your microphone."
            : "Twilio dials the patient's phone number. Audio streams between the phone line and OpenAI. The browser still shows transcripts and controls."}
        </p>
      </div>

      <Separator />

      {/* Queue Source */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-sm font-medium">Queue Source</h4>
          <InfoTooltip content="Determines where queue metrics (calls waiting, agents available) come from. Simulation uses mock data you control. Live connects to FreePBX/Asterisk for real call center status." />
        </div>
        <p className="text-xs text-muted-foreground">
          Choose where queue data comes from. Simulation uses a mock provider you can control manually. Live connects to the FreePBX queue status endpoint for real-time data.
        </p>
        <div className="flex items-center gap-4">
          <Select value={settings.queue_source} onValueChange={onSetQueueSource}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="simulation">
                <span className="flex items-center gap-2">
                  <Monitor className="h-4 w-4" />
                  Simulation
                </span>
              </SelectItem>
              <SelectItem value="live">
                <span className="flex items-center gap-2">
                  <Radio className="h-4 w-4" />
                  Live FreePBX
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
          {settings.queue_source === "live" && (
            <Badge variant="outline" className="text-blue-600 border-blue-600">
              Live data
            </Badge>
          )}
        </div>
      </div>

      <Separator />

      {/* Patient Source */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-sm font-medium">Patient Source</h4>
          <InfoTooltip content="Determines where the outbound call list comes from. Simulation uses mock patient data from scenarios. Live connects to RadFlow/EHR for real patients needing callbacks." />
        </div>
        <p className="text-xs text-muted-foreground">
          Choose where patient call list data comes from. Simulation uses sample patients you can control manually. Live connects to the RadFlow CallListData API for real patient data.
        </p>
        <div className="flex items-center gap-4">
          <Select value={settings.patient_source} onValueChange={onSetPatientSource}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="simulation">
                <span className="flex items-center gap-2">
                  <Monitor className="h-4 w-4" />
                  Simulation
                </span>
              </SelectItem>
              <SelectItem value="live">
                <span className="flex items-center gap-2">
                  <Users className="h-4 w-4" />
                  Live RadFlow
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
          {settings.patient_source === "live" && (
            <Badge variant="outline" className="text-blue-600 border-blue-600">
              Live data
            </Badge>
          )}
        </div>
      </div>

      {/* Active Scenario Selector - only visible when either source is simulation */}
      {(settings.queue_source === "simulation" || settings.patient_source === "simulation") && (
        <>
          <Separator />

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-muted-foreground" />
              <h4 className="text-sm font-medium">Active Scenario</h4>
              <InfoTooltip content="Selects which simulation scenario is loaded. Changing scenarios resets the patient queue, call logs, and dispatcher state. Use the Simulation tab to edit scenario details." />
            </div>
            <p className="text-xs text-muted-foreground">
              Select which simulation scenario to use. Changing the active scenario will reset mock queue/patient data, clear call logs, and restart the dispatcher.
            </p>
            <div className="flex items-center gap-4">
              <Select
                value={settings.active_scenario_id || ""}
                onValueChange={onSetActiveScenario}
              >
                <SelectTrigger className="w-64">
                  <SelectValue placeholder="Select scenario..." />
                </SelectTrigger>
                <SelectContent>
                  {scenarios.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      <span className="flex items-center gap-2">
                        {s.label}
                        {s.is_builtin && (
                          <Badge variant="outline" className="text-xs">Builtin</Badge>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </>
      )}

      <Separator />

      {/* Mock Mode */}
      <div className="space-y-4 rounded-lg border border-orange-200 bg-orange-50/50 dark:border-orange-900 dark:bg-orange-950/20 p-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-orange-600 dark:text-orange-400" />
          <h4 className="text-sm font-medium">Test Mode</h4>
          <InfoTooltip content="Route all Twilio calls and SMS to a test number instead of real patients." />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <Label htmlFor="mock-mode" className="text-sm flex items-center gap-1.5">
                Mock Mode
                <InfoTooltip content="When enabled, all Twilio calls and SMS are redirected to the mock phone number below instead of the patient's real number. Useful for end-to-end testing without calling patients." />
              </Label>
              <p className="text-xs text-muted-foreground">
                Redirect all outbound calls and SMS to a test number
              </p>
            </div>
            <Switch
              id="mock-mode"
              checked={settings.mock_mode}
              onCheckedChange={(checked) => onSetMockMode(checked, settings.mock_phone)}
            />
          </div>
          {settings.mock_mode && (
            <div className="space-y-1">
              <Label htmlFor="mock-phone" className="text-xs text-muted-foreground flex items-center gap-1.5">
                Mock Phone Number
                <InfoTooltip content="All Twilio calls and SMS will be sent to this number instead of the patient's real number. Use E.164 format (+1...)." />
              </Label>
              <Input
                id="mock-phone"
                placeholder="+15551234567"
                value={mockPhoneInput}
                onChange={(e) => setMockPhoneInput(e.target.value)}
                onBlur={() => { if (mockPhoneInput !== settings.mock_phone) onSetMockMode(settings.mock_mode, mockPhoneInput); }}
                onKeyDown={(e) => { if (e.key === "Enter" && mockPhoneInput !== settings.mock_phone) onSetMockMode(settings.mock_mode, mockPhoneInput); }}
                className="h-9"
              />
            </div>
          )}
        </div>

      </div>

      <Separator />

      {/* Daily Slack Report */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-sm font-medium">Daily Slack Report</h4>
          <InfoTooltip content="Once per day at the configured hour, posts yesterday's call summary (calls placed, transfers, voicemails, etc.) to a Slack webhook." />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label htmlFor="daily-report-enabled" className="text-sm flex items-center gap-1.5">
              Enable daily report
            </Label>
            <p className="text-xs text-muted-foreground">
              Post yesterday's stats to Slack every day
            </p>
          </div>
          <Switch
            id="daily-report-enabled"
            checked={dailyReportForm.enabled}
            onCheckedChange={(checked) => setDailyReportForm({ ...dailyReportForm, enabled: checked })}
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1 md:col-span-2">
            <Label htmlFor="daily-report-webhook" className="text-xs text-muted-foreground">
              Slack Webhook URL
            </Label>
            <Input
              id="daily-report-webhook"
              type="text"
              placeholder="https://hooks.slack.com/services/..."
              value={dailyReportForm.webhook_url}
              onChange={(e) => setDailyReportForm({ ...dailyReportForm, webhook_url: e.target.value })}
              className="h-9 font-mono text-xs"
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="daily-report-hour" className="text-xs text-muted-foreground">
              Send at (hour, 0-23)
            </Label>
            <Input
              id="daily-report-hour"
              type="number"
              min={0}
              max={23}
              value={dailyReportForm.hour}
              onChange={(e) => {
                const h = parseInt(e.target.value, 10);
                setDailyReportForm({ ...dailyReportForm, hour: isNaN(h) ? 0 : Math.max(0, Math.min(23, h)) });
              }}
              className="h-9"
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="daily-report-tz" className="text-xs text-muted-foreground">
              Timezone
            </Label>
            <Select
              value={dailyReportForm.timezone}
              onValueChange={(v) => setDailyReportForm({ ...dailyReportForm, timezone: v })}
            >
              <SelectTrigger id="daily-report-tz" className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {timezones.map((tz) => (
                  <SelectItem key={tz} value={tz}>{tz}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" onClick={handleDailyReportSave} disabled={dailyReportSaving}>
            <Save className="h-3 w-3 mr-1.5" />
            {dailyReportSaving ? "Saving..." : "Save"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={handleDailyReportTest}
            disabled={!dailyReportForm.webhook_url}
            title="Send yesterday's summary to Slack now (ignores the enable toggle)"
          >
            Send Test Now
          </Button>
          {dailyReportTestStatus && (
            <span className="text-xs text-muted-foreground">{dailyReportTestStatus}</span>
          )}
        </div>
      </div>

      <Separator />

      {/* Business Hours + Queue Thresholds side by side */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Business Hours */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <h4 className="text-sm font-medium">Business Hours</h4>
            <InfoTooltip content="Restricts outbound calls to specific hours and days. Prevents AI from calling patients outside business hours or on weekends." />
          </div>

          <div className="flex items-center justify-between">
            <Label htmlFor="business-hours-enabled" className="text-sm flex items-center gap-1.5">
              Enforce hours
              <InfoTooltip content="When enabled, calls are only allowed during the specified time window and days. When disabled, calls can be placed 24/7." />
            </Label>
            <Switch
              id="business-hours-enabled"
              checked={businessHoursForm.enabled}
              onCheckedChange={handleBusinessHoursEnabledChange}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="start-time" className="text-xs text-muted-foreground flex items-center gap-1">
                Start
                <InfoTooltip content="Earliest time calls can begin. Uses 24-hour format in the selected timezone." />
              </Label>
              <Input
                id="start-time"
                type="time"
                value={businessHoursForm.start_time}
                onChange={(e) =>
                  setBusinessHoursForm({ ...businessHoursForm, start_time: e.target.value })
                }
                disabled={!businessHoursForm.enabled}
                className="h-9"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="end-time" className="text-xs text-muted-foreground flex items-center gap-1">
                End
                <InfoTooltip content="Latest time calls can be placed. Calls in progress may continue past this time." />
              </Label>
              <Input
                id="end-time"
                type="time"
                value={businessHoursForm.end_time}
                onChange={(e) =>
                  setBusinessHoursForm({ ...businessHoursForm, end_time: e.target.value })
                }
                disabled={!businessHoursForm.enabled}
                className="h-9"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="timezone" className="text-xs text-muted-foreground flex items-center gap-1">
              Timezone
              <InfoTooltip content="All business hours are evaluated in this timezone. Make sure it matches your call center's operating timezone." />
            </Label>
            <Select
              value={businessHoursForm.timezone}
              onValueChange={(value) =>
                setBusinessHoursForm({ ...businessHoursForm, timezone: value })
              }
              disabled={!businessHoursForm.enabled}
            >
              <SelectTrigger id="timezone" className="h-9">
                <SelectValue placeholder="Select timezone" />
              </SelectTrigger>
              <SelectContent>
                {timezones.map((tz) => (
                  <SelectItem key={tz} value={tz}>
                    {tz}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground flex items-center gap-1">
              Days of Week
              <InfoTooltip content="Select which days outbound calls are allowed. Typically Mon-Fri to avoid weekend calls. Click to toggle each day." />
            </Label>
            <div className="flex flex-wrap gap-1">
              {DAY_LABELS.map((day, idx) => {
                const isSelected = businessHoursForm.days_of_week?.includes(idx) ?? false;
                return (
                  <button
                    key={day}
                    type="button"
                    disabled={!businessHoursForm.enabled}
                    onClick={() => {
                      const current = businessHoursForm.days_of_week ?? [];
                      const newDays = isSelected
                        ? current.filter((d) => d !== idx)
                        : [...current, idx].sort((a, b) => a - b);
                      setBusinessHoursForm({ ...businessHoursForm, days_of_week: newDays });
                    }}
                    className={`px-2 py-1 text-xs rounded border transition-colors ${
                      isSelected
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background text-muted-foreground border-border hover:bg-muted"
                    } ${!businessHoursForm.enabled ? "opacity-50 cursor-not-allowed" : ""}`}
                  >
                    {day}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-2 rounded-lg border p-3">
            <button
              type="button"
              onClick={() => setHolidayEditorOpen((v) => !v)}
              className="w-full flex items-center justify-between text-left"
            >
              <div className="flex items-center gap-2">
                <CalendarDays className="h-4 w-4 text-muted-foreground" />
                <p className="text-sm font-medium flex items-center gap-1.5">
                  Holiday Calendar
                  <InfoTooltip content="Calls are blocked on matching holiday dates even when business hours/day rules are otherwise valid." />
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="text-[10px]">
                  {(businessHoursForm.holidays || []).length} holiday{(businessHoursForm.holidays || []).length !== 1 ? "s" : ""}
                </Badge>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${holidayEditorOpen ? "rotate-180" : ""}`} />
              </div>
            </button>

            {holidayEditorOpen && (
              <div className="space-y-3 pt-2">
                {(businessHoursForm.holidays || []).length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No holidays configured. Add entries to block outbound calls on those dates.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {(businessHoursForm.holidays || []).map((holiday, idx) => (
                      <div key={idx} className="grid grid-cols-12 gap-2 items-center rounded border p-2">
                        <Input
                          type="date"
                          value={holiday.date}
                          onChange={(e) => handleUpdateHoliday(idx, { date: e.target.value })}
                          className="col-span-4 h-8"
                        />
                        <Input
                          placeholder="Holiday name"
                          value={holiday.name}
                          onChange={(e) => handleUpdateHoliday(idx, { name: e.target.value })}
                          className="col-span-5 h-8"
                        />
                        <div className="col-span-2 flex items-center justify-end gap-2">
                          <Label className="text-[11px] text-muted-foreground">Yearly</Label>
                          <Switch
                            checked={holiday.recurring}
                            onCheckedChange={(checked) => handleUpdateHoliday(idx, { recurring: checked })}
                          />
                        </div>
                        <div className="col-span-1 flex justify-end">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => handleRemoveHoliday(idx)}
                          >
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <Button type="button" size="sm" variant="outline" onClick={handleAddHoliday}>
                  <Plus className="h-3.5 w-3.5 mr-1.5" />
                  Add Holiday
                </Button>
                <Button type="button" size="sm" onClick={handleBusinessHoursSubmit}>
                  <Save className="h-3.5 w-3.5 mr-1.5" />
                  Save Holidays
                </Button>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Within hours:</span>
              {settings.is_within_business_hours ? (
                <Badge variant="success" className="text-xs">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-xs">No</Badge>
              )}
            </div>
            <Button size="sm" variant="outline" onClick={handleBusinessHoursSubmit}>
              <Save className="h-3 w-3 mr-1.5" />
              Save
            </Button>
          </div>
        </div>

        {/* Queue Thresholds */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
            <h4 className="text-sm font-medium">Queue Thresholds</h4>
            <InfoTooltip content="Gating conditions that must be met before placing outbound calls. Prevents AI calls when the call center is already overwhelmed with inbound calls." />
          </div>

          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="calls-waiting" className="text-xs text-muted-foreground flex items-center gap-1">
                Max calls waiting before blocking outbound
                <InfoTooltip content="If more than this many calls are waiting in the inbound queue, outbound calls are paused. Set to 0 to disable this check." />
              </Label>
              <Input
                id="calls-waiting"
                type="number"
                min="0"
                value={thresholdsForm.calls_waiting_threshold}
                onChange={(e) =>
                  setThresholdsForm({
                    ...thresholdsForm,
                    calls_waiting_threshold: parseInt(e.target.value) || 0,
                  })
                }
                className="h-9"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="oldest-wait" className="text-xs text-muted-foreground flex items-center gap-1">
                Max wait time (seconds) before blocking
                <InfoTooltip content="If any caller has been waiting longer than this, outbound calls are paused. Ensures agents handle long-waiting inbound callers first." />
              </Label>
              <Input
                id="oldest-wait"
                type="number"
                min="0"
                value={thresholdsForm.holdtime_threshold_seconds}
                onChange={(e) =>
                  setThresholdsForm({
                    ...thresholdsForm,
                    holdtime_threshold_seconds: parseInt(e.target.value) || 0,
                  })
                }
                className="h-9"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="stable-polls" className="text-xs text-muted-foreground flex items-center gap-1">
                Consecutive stable polls required
                <InfoTooltip content="How many consecutive queue checks must pass thresholds before outbound is allowed. Prevents calls during brief lulls in a busy period." />
              </Label>
              <Input
                id="stable-polls"
                type="number"
                min="1"
                value={thresholdsForm.stable_polls_required}
                onChange={(e) =>
                  setThresholdsForm({
                    ...thresholdsForm,
                    stable_polls_required: parseInt(e.target.value) || 1,
                  })
                }
                className="h-9"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button size="sm" variant="outline" onClick={handleThresholdsSubmit}>
              <Save className="h-3 w-3 mr-1.5" />
              Save
            </Button>
          </div>
        </div>
      </div>

      <Separator />

      {/* Dispatcher Settings */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-sm font-medium">Dispatcher Settings</h4>
          <InfoTooltip content="Controls how the dispatcher selects and places outbound calls. These settings affect call frequency and retry behavior." />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="poll-interval" className="text-xs text-muted-foreground flex items-center gap-1">
              Poll interval (seconds)
              <InfoTooltip content="How often the dispatcher checks queue status and attempts to place calls. Lower values = more frequent checks." />
            </Label>
            <Input
              id="poll-interval"
              type="number"
              min="1"
              value={dispatcherForm.poll_interval}
              onChange={(e) =>
                setDispatcherForm({
                  ...dispatcherForm,
                  poll_interval: parseInt(e.target.value) || 1,
                })
              }
              className="h-9"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="dispatch-timeout" className="text-xs text-muted-foreground flex items-center gap-1">
              Dispatch timeout (seconds)
              <InfoTooltip content="How long to wait for the frontend to acknowledge a dispatch request before timing out and trying again." />
            </Label>
            <Input
              id="dispatch-timeout"
              type="number"
              min="1"
              value={dispatcherForm.dispatch_timeout}
              onChange={(e) =>
                setDispatcherForm({
                  ...dispatcherForm,
                  dispatch_timeout: parseInt(e.target.value) || 1,
                })
              }
              className="h-9"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="max-attempts" className="text-xs text-muted-foreground flex items-center gap-1">
              Max attempts per patient
              <InfoTooltip content="Maximum number of call attempts for each patient. After this many tries, the patient is marked as exhausted and won't be called again." />
            </Label>
            <Input
              id="max-attempts"
              type="number"
              min="1"
              value={dispatcherForm.max_attempts}
              onChange={(e) =>
                setDispatcherForm({
                  ...dispatcherForm,
                  max_attempts: parseInt(e.target.value) || 1,
                })
              }
              className="h-9"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="min-hours-between" className="text-xs text-muted-foreground flex items-center gap-1">
              Min hours between attempts
              <InfoTooltip content="Minimum wait time before retrying a patient who didn't answer or requested a callback. Prevents calling the same person repeatedly in a short time." />
            </Label>
            <Input
              id="min-hours-between"
              type="number"
              min="0"
              value={dispatcherForm.min_hours_between}
              onChange={(e) =>
                setDispatcherForm({
                  ...dispatcherForm,
                  min_hours_between: parseInt(e.target.value) || 0,
                })
              }
              className="h-9"
            />
          </div>
        </div>

        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={handleDispatcherSubmit}>
            <Save className="h-3 w-3 mr-1.5" />
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
