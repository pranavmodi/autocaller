"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  QueueStatusCard,
  PatientQueueCard,
  ActiveCallCard,
  CallHistoryCard,
  DispatcherEventsCard,
  KpiBar,
} from "@/components/dashboard";
import { SimulationConsole, OperatorConsole } from "@/components/console";
import { useApi } from "@/hooks/useApi";
import { useDashboardWS, useVoiceWS } from "@/hooks/useWebSocket";
import { useAudio } from "@/hooks/useAudio";
import {
  Phone,
  LayoutDashboard,
  Terminal,
  Settings,
  ChevronDown,
  Circle,
  History,
} from "lucide-react";
import type { Patient, CallLog, QueueState, SystemSettings, SimulationScenario, TodayKpis } from "@/types";

const PATIENT_POLL_INTERVAL_MS = 10000; // Poll patients every 10 seconds
const CALLS_PAGE_SIZE = 25;

export default function Dashboard() {
  // API hooks
  const api = useApi();

  // Dashboard WebSocket (receives queue_update + dispatch_call from backend)
  const dashboard = useDashboardWS();

  // Voice WebSocket
  const voice = useVoiceWS();

  // Audio hooks
  const audio = useAudio();

  // State
  const [queueState, setQueueState] = useState<QueueState | null>(null);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientsLastUpdated, setPatientsLastUpdated] = useState<Date | null>(null);
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [callsTotal, setCallsTotal] = useState(0);
  const [todayKpis, setTodayKpis] = useState<TodayKpis | null>(null);
  const [activeCall, setActiveCall] = useState<CallLog | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [lastCallInfo, setLastCallInfo] = useState<{ patientName: string; duration: number } | null>(null);
  const [callStartTime, setCallStartTime] = useState<number | null>(null);
  const [callingPatientName, setCallingPatientName] = useState<string>("");

  // Settings state
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [timezones, setTimezones] = useState<string[]>([]);

  // Scenarios state
  const [scenarios, setScenarios] = useState<SimulationScenario[]>([]);

  // Call mode: "web" (browser audio) or "twilio" (real phone call)
  const [callMode, setCallMode] = useState<string>("web");

  // Operator section collapsed state - collapsed by default
  const [operatorOpen, setOperatorOpen] = useState(false);

  // Load initial data - only once
  useEffect(() => {
    if (isLoaded) return;

    const loadData = async () => {
      const [status, patientList, callData, settingsData, tzList, scenarioList, kpis] = await Promise.all([
        api.getStatus(),
        api.getOutboundQueue(),
        api.getCalls(CALLS_PAGE_SIZE),
        api.getSettings(),
        api.getTimezones(),
        api.getScenarios(),
        api.getTodayKpis(),
      ]);

      if (status) {
        setQueueState(status.queue_state);
        setActiveCall(status.active_call);
      }
      setPatients(patientList);
      setPatientsLastUpdated(new Date());
      setCalls(callData.calls);
      setCallsTotal(callData.total);
      setTodayKpis(kpis);
      setSettings(settingsData);
      if (settingsData?.call_mode) {
        setCallMode(settingsData.call_mode);
      }
      setTimezones(tzList);
      setScenarios(scenarioList);
      setIsLoaded(true);
    };

    loadData();
  }, [isLoaded, api]);

  // Poll patients at regular intervals (independent of browser focus)
  useEffect(() => {
    if (!isLoaded) return;

    const pollPatients = async () => {
      try {
        const patientList = await api.getOutboundQueue();
        setPatients(patientList);
        setPatientsLastUpdated(new Date());
      } catch (e) {
        console.error("Failed to poll patients:", e);
      }
    };

    const interval = setInterval(pollPatients, PATIENT_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [isLoaded, api]);

  // Sync queue state from dashboard WebSocket (replaces REST polling)
  useEffect(() => {
    if (dashboard.queueState) setQueueState(dashboard.queueState);
  }, [dashboard.queueState]);

  // Refresh call history, patient list, and today's KPIs when a call ends (via dashboard WS)
  useEffect(() => {
    dashboard.onCallEnded.current = () => {
      api.getCalls(CALLS_PAGE_SIZE).then(({ calls: c, total: t }) => {
        setCalls(c);
        setCallsTotal(t);
      });
      api.getOutboundQueue().then((list) => {
        setPatients(list);
        setPatientsLastUpdated(new Date());
      });
      api.getTodayKpis().then((kpis) => {
        if (kpis) setTodayKpis(kpis);
      });
    };
  }, [api, dashboard.onCallEnded]);

  // Sync settings when another window/tab changes them
  useEffect(() => {
    dashboard.onSettingsUpdated.current = (newSettings: SystemSettings) => {
      setSettings(newSettings);
      if (newSettings.call_mode) {
        setCallMode(newSettings.call_mode);
      }
    };
  }, [dashboard.onSettingsUpdated]);

  // Store refs to always have latest functions
  const voiceRef = useRef(voice);
  const audioRef = useRef(audio);
  voiceRef.current = voice;
  audioRef.current = audio;

  // Set up audio callbacks - only once
  const audioSetupRef = useRef(false);
  useEffect(() => {
    if (audioSetupRef.current) return;
    audioSetupRef.current = true;

    voice.onAudioReceived((audioData) => {
      audioRef.current.playAudio(audioData);
    });

    audio.onAudioData((data) => {
      voiceRef.current.sendAudio(data);
    });
  }, [voice, audio]);

  // Handle call start
  const handleCallPatient = useCallback(async (patientId: string) => {
    const patient = patients.find(p => p.patient_id === patientId);
    const patientName = patient?.name || "Patient";
    setCallingPatientName(patientName);
    setCallStartTime(Date.now());
    setLastCallInfo(null);

    dashboard.pushEvent("voice_connecting", `Initiating ${callMode} call to ${patientName}...`);

    if (!voice.connected) {
      voice.connect();
      for (let i = 0; i < 20; i++) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        if (voiceRef.current.connected) break;
      }
    }

    if (voice.connected) {
      dashboard.pushEvent("voice_connected", "Voice WebSocket connected");
    }

    if (callMode === "web") {
      await audio.startRecording();
      await new Promise((resolve) => setTimeout(resolve, 200));
    }

    voice.startCall(patientId);
  }, [voice, audio, patients, callMode, dashboard]);

  // Stop recording when call ends
  const prevActiveRef = useRef(false);
  useEffect(() => {
    const wasActive = prevActiveRef.current;
    const nowActive = voice.isCallActive;
    prevActiveRef.current = nowActive;
    if (wasActive && !nowActive) {
      audio.stopRecording();
    }
  }, [voice.isCallActive, audio]);

  // Push voice status changes to dispatcher events
  const prevVoiceStatusRef = useRef<string | null>(null);
  useEffect(() => {
    if (voice.callStatus && voice.callStatus !== prevVoiceStatusRef.current) {
      prevVoiceStatusRef.current = voice.callStatus;
      const normalized = voice.callStatus.toLowerCase();
      // SMS status updates are already captured from dashboard status_update events.
      if (normalized.includes("sms sent") || normalized.includes("sms failed")) {
        return;
      }
      // Map status to event type
      if (normalized.includes("openai") || normalized.includes("session")) {
        dashboard.pushEvent("openai_session", voice.callStatus);
      } else if (normalized.includes("blocked") || normalized.includes("disabled")) {
        dashboard.pushEvent("twilio_blocked", voice.callStatus);
      } else if (normalized.includes("twilio") || normalized.includes("calling")) {
        dashboard.pushEvent("twilio_calling", voice.callStatus);
      } else {
        dashboard.pushEvent("voice_message", voice.callStatus);
      }
    }
  }, [voice.callStatus, dashboard]);

  // Push voice errors to dispatcher events
  const prevVoiceErrorRef = useRef<string | null>(null);
  useEffect(() => {
    if (voice.error && voice.error !== prevVoiceErrorRef.current) {
      prevVoiceErrorRef.current = voice.error;
      dashboard.pushEvent("voice_error", voice.error);
    }
  }, [voice.error, dashboard]);

  // React to backend dispatch_call commands
  useEffect(() => {
    if (!dashboard.dispatchedPatient) return;
    if (voice.isCallActive) {
      dashboard.clearDispatch();
      return;
    }
    const { patient_id } = dashboard.dispatchedPatient;
    dashboard.clearDispatch();
    handleCallPatient(patient_id);
  }, [dashboard.dispatchedPatient, dashboard.clearDispatch, voice.isCallActive, handleCallPatient]);

  // Handle call end
  const handleEndCall = useCallback(() => {
    const duration = callStartTime ? Math.floor((Date.now() - callStartTime) / 1000) : 0;
    setLastCallInfo({
      patientName: callingPatientName,
      duration,
    });

    dashboard.pushEvent("call_ended", `Call ended with ${callingPatientName} (${duration}s)`);

    voice.endCall();
    audio.stopRecording();
    setActiveCall(null);
    setCallStartTime(null);

    api.getCalls(CALLS_PAGE_SIZE).then(({ calls: c, total: t }) => {
      setCalls(c);
      setCallsTotal(t);
    });
    api.getOutboundQueue().then((list) => {
      setPatients(list);
      setPatientsLastUpdated(new Date());
    });
  }, [voice, audio, api, callStartTime, callingPatientName, dashboard]);

  // Handle mic toggle
  const handleToggleMic = useCallback(async () => {
    if (audio.isRecording) {
      audio.stopRecording();
    } else {
      await audio.startRecording();
    }
  }, [audio]);

  // Scenario handlers
  const handleRefreshScenarios = useCallback(async () => {
    const scenarioList = await api.getScenarios();
    setScenarios(scenarioList);
  }, [api]);

  const handleSetActiveScenario = useCallback(async (scenarioId: string) => {
    const newSettings = await api.setActiveScenario(scenarioId);
    if (newSettings) {
      setSettings(newSettings);
      // Refresh patients and calls since the scenario reset them
      const [patientList, callData, statusData] = await Promise.all([
        api.getOutboundQueue(),
        api.getCalls(CALLS_PAGE_SIZE),
        api.getQueueState(),
      ]);
      setPatients(patientList);
      setPatientsLastUpdated(new Date());
      setCalls(callData.calls);
      setCallsTotal(callData.total);
      if (statusData) setQueueState(statusData);
    }
  }, [api]);

  const handleSaveScenario = useCallback(async (
    id: string,
    data: {
      label?: string;
      description?: string;
      ami_connected?: boolean;
      queues?: Array<{ Queue: string; Calls?: number; Holdtime?: number; AvailableAgents?: number }>;
      patients?: Array<{
        name: string;
        phone: string;
        language: string;
        has_abandoned_before: boolean;
        has_called_in_before: boolean;
        ai_called_before: boolean;
        attempt_count: number;
      }>;
    }
  ) => {
    return await api.updateScenario(id, data);
  }, [api]);

  const handleCreateScenario = useCallback(async (data: {
    label: string;
    description?: string;
    ami_connected?: boolean;
    queues?: Array<{ Queue: string; Calls?: number; Holdtime?: number; AvailableAgents?: number }>;
    patients?: Array<{
      name: string;
      phone: string;
      language: string;
      has_abandoned_before: boolean;
      has_called_in_before: boolean;
      ai_called_before: boolean;
      attempt_count: number;
    }>;
  }) => {
    return await api.createScenario(data);
  }, [api]);

  const handleDeleteScenario = useCallback(async (id: string) => {
    return await api.deleteScenario(id);
  }, [api]);

  const handleAddPatientToQueue = useCallback(async (data: {
    name: string;
    phone: string;
    language?: string;
    has_abandoned_before?: boolean;
    has_called_in_before?: boolean;
    ai_called_before?: boolean;
    attempt_count?: number;
  }) => {
    const result = await api.addPatient(data);
    if (result) {
      // Refresh patients list
      const patientList = await api.getOutboundQueue();
      setPatients(patientList);
      setPatientsLastUpdated(new Date());
    }
    return result;
  }, [api]);

  // Settings handlers
  const handleSetSystemEnabled = useCallback(async (enabled: boolean) => {
    const newSettings = await api.setSystemEnabled(enabled);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleUpdateBusinessHours = useCallback(async (businessHours: SystemSettings["business_hours"]) => {
    const newSettings = await api.updateBusinessHours(businessHours);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleUpdateQueueThresholds = useCallback(async (thresholds: SystemSettings["queue_thresholds"]) => {
    const newSettings = await api.updateQueueThresholds(thresholds);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleUpdateDispatcherSettings = useCallback(async (dispatcherSettings: SystemSettings["dispatcher_settings"]) => {
    const newSettings = await api.updateDispatcherSettings(dispatcherSettings);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleSetMockMode = useCallback(async (enabled: boolean, mockPhone: string) => {
    const newSettings = await api.setMockMode(enabled, mockPhone);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleUpdateDailyReport = useCallback(async (config: {
    enabled: boolean;
    webhook_url: string;
    hour: number;
    timezone: string;
  }) => {
    const newSettings = await api.updateDailyReport(config);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleSendTestDailyReport = useCallback(async () => {
    return await api.sendTestDailyReport();
  }, [api]);

  const handleSetQueueSource = useCallback(async (source: string) => {
    const newSettings = await api.setQueueSource(source);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleSetPatientSource = useCallback(async (source: string) => {
    const newSettings = await api.setPatientSource(source);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  const handleSetCallMode = useCallback(async (mode: string) => {
    setCallMode(mode); // Update local state immediately for UI responsiveness
    const newSettings = await api.setCallMode(mode);
    if (newSettings) setSettings(newSettings);
  }, [api]);

  // Refresh handlers
  const handleRefreshPatients = useCallback(async () => {
    const patientList = await api.getOutboundQueue();
    setPatients(patientList);
    setPatientsLastUpdated(new Date());
  }, [api]);

  const handleDeletePatient = useCallback(async (patientId: string) => {
    await api.deletePatient(patientId);
    const patientList = await api.getOutboundQueue();
    setPatients(patientList);
    setPatientsLastUpdated(new Date());
  }, [api]);

  const handleUpdatePatient = useCallback(async (patientId: string, data: {
    name?: string;
    phone?: string;
    language?: string;
    has_abandoned_before?: boolean;
    has_called_in_before?: boolean;
    ai_called_before?: boolean;
    attempt_count?: number;
  }) => {
    await api.updatePatient(patientId, data);
    const patientList = await api.getOutboundQueue();
    setPatients(patientList);
    setPatientsLastUpdated(new Date());
  }, [api]);

  const handleRefreshCalls = useCallback(async () => {
    const { calls: c, total: t } = await api.getCalls(CALLS_PAGE_SIZE);
    setCalls(c);
    setCallsTotal(t);
  }, [api]);

  const handleLoadMoreCalls = useCallback(async () => {
    const { calls: more, total: t } = await api.getCalls(CALLS_PAGE_SIZE, calls.length);
    setCalls((prev) => [...prev, ...more]);
    setCallsTotal(t);
  }, [api, calls.length]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b bg-card/80 backdrop-blur-lg">
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
              <Phone className="h-4 w-4" />
            </div>
            <div className="leading-tight">
              <h1 className="text-base font-semibold tracking-tight">Outbound Voice AI</h1>
              <p className="text-xs text-muted-foreground">Precise Imaging</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Connection indicator */}
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {dashboard.connected ? (
                <>
                  <Circle className="h-2 w-2 fill-emerald-500 text-emerald-500 status-dot" />
                  <span className="hidden sm:inline">Connected</span>
                </>
              ) : (
                <>
                  <Circle className="h-2 w-2 fill-red-500 text-red-500" />
                  <span className="hidden sm:inline">Disconnected</span>
                </>
              )}
            </div>

            {/* Call active badge */}
            {voice.isCallActive && (
              <Badge variant="success" className="flex items-center gap-1.5 shadow-sm">
                <span className="h-1.5 w-1.5 rounded-full bg-white animate-pulse" />
                Call Active
              </Badge>
            )}

            {/* System status */}
            {settings && (
              <Badge
                variant={settings.system_enabled ? "default" : "outline"}
                className="hidden sm:flex"
              >
                {settings.system_enabled ? "System On" : "System Off"}
              </Badge>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-6 py-8">
        {/* Error Display */}
        {(api.error || voice.error || audio.error) && (
          <div className="mb-6 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive animate-in">
            {api.error || voice.error || audio.error}
          </div>
        )}

        <Tabs defaultValue="dashboard" className="space-y-8">
          <TabsList className="inline-flex h-10 rounded-lg bg-muted p-1">
            <TabsTrigger value="dashboard" className="flex items-center gap-2 rounded-md px-4 text-sm">
              <LayoutDashboard className="h-4 w-4" />
              Dashboard
            </TabsTrigger>
            <TabsTrigger value="history" className="flex items-center gap-2 rounded-md px-4 text-sm">
              <History className="h-4 w-4" />
              History
            </TabsTrigger>
            <TabsTrigger value="simulation" className="flex items-center gap-2 rounded-md px-4 text-sm">
              <Terminal className="h-4 w-4" />
              Simulation
            </TabsTrigger>
          </TabsList>

          {/* Dashboard Tab */}
          <TabsContent value="dashboard" className="space-y-6 animate-in">
            {/* KPI row — today's headline numbers */}
            <KpiBar kpis={todayKpis} />

            {/* 1. System Settings - at the top, expanded by default */}
            <Collapsible open={operatorOpen} onOpenChange={setOperatorOpen}>
              <Card>
                <CollapsibleTrigger asChild>
                  <CardHeader className="cursor-pointer select-none hover:bg-muted/50 transition-colors rounded-t-lg">
                    <div className="flex items-center justify-between">
                      <CardTitle className="flex items-center gap-2 text-lg">
                        <Settings className="h-5 w-5" />
                        System Settings
                      </CardTitle>
                      <div className="flex items-center gap-3">
                        {settings && (
                          <>
                            <Badge
                              variant={settings.queue_source === "live" ? "default" : "secondary"}
                              className="text-xs"
                            >
                              Queue: {settings.queue_source === "live" ? "Live" : "Sim"}
                            </Badge>
                            <Badge
                              variant={settings.patient_source === "live" ? "default" : "secondary"}
                              className="text-xs"
                            >
                              Patients: {settings.patient_source === "live" ? "Live" : "Sim"}
                            </Badge>
                            <Badge
                              variant={settings.system_enabled ? "success" : "outline"}
                              className="text-xs"
                            >
                              {settings.system_enabled ? "Enabled" : "Disabled"}
                            </Badge>
                          </>
                        )}
                        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${operatorOpen ? "rotate-180" : ""}`} />
                      </div>
                    </div>
                  </CardHeader>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <CardContent className="pt-0">
                    <OperatorConsole
                      settings={settings}
                      timezones={timezones}
                      callMode={callMode}
                      scenarios={scenarios}
                      onCallModeChange={handleSetCallMode}
                      onSetSystemEnabled={handleSetSystemEnabled}
                      onUpdateBusinessHours={handleUpdateBusinessHours}
                      onUpdateQueueThresholds={handleUpdateQueueThresholds}
                      onUpdateDispatcherSettings={handleUpdateDispatcherSettings}
                      onSetMockMode={handleSetMockMode}
                      onUpdateDailyReport={handleUpdateDailyReport}
                      onSendTestDailyReport={handleSendTestDailyReport}
                      onSetQueueSource={handleSetQueueSource}
                      onSetPatientSource={handleSetPatientSource}
                      onSetActiveScenario={handleSetActiveScenario}
                    />
                  </CardContent>
                </CollapsibleContent>
              </Card>
            </Collapsible>

            {/* 2. Queue Status + Patient Queue side by side */}
            <div className="grid gap-6 lg:grid-cols-2">
              <QueueStatusCard
                queueState={queueState}
                source={settings?.queue_source as "simulation" | "live" | undefined}
              />
              <PatientQueueCard
                patients={patients}
                onCallPatient={handleCallPatient}
                onRefresh={handleRefreshPatients}
                onReloadScenario={settings?.active_scenario_id ? () => handleSetActiveScenario(settings.active_scenario_id!) : undefined}
                onDeletePatient={handleDeletePatient}
                onUpdatePatient={handleUpdatePatient}
                isCallActive={voice.isCallActive}
                outboundAllowed={queueState?.outbound_allowed ?? false}
                source={settings?.patient_source as "simulation" | "live" | undefined}
                lastUpdated={patientsLastUpdated}
              />
            </div>

            {/* 3. Dispatcher Events - full width */}
            <DispatcherEventsCard events={dashboard.dispatcherEvents} />

            {/* 4. Active Call */}
            <ActiveCallCard
              call={voice.isCallActive ? ({
                call_id: "active",
                patient_id: "",
                patient_name: callingPatientName || "Patient",
                phone: "",
                order_id: null,
                priority_bucket: 0,
                started_at: callStartTime ? new Date(callStartTime).toISOString() : new Date().toISOString(),
                ended_at: null,
                duration_seconds: 0,
                outcome: "in_progress",
                call_status: "in_progress",
                call_disposition: "in_progress",
                mock_mode: false,
                transfer_attempted: false,
                transfer_success: false,
                voicemail_left: false,
                sms_sent: false,
                queue_snapshot: null,
                transcript: [],
                error_code: null,
                error_message: null,
              } as CallLog) : dashboard.activeCall}
              status={voice.isCallActive ? voice.callStatus : dashboard.lastStatus}
              transcript={voice.isCallActive ? voice.transcript : (dashboard.activeCall?.transcript ?? [])}
              isRecording={audio.isRecording}
              audioLevel={audio.audioLevel}
              onEndCall={handleEndCall}
              onToggleMic={handleToggleMic}
              lastCallInfo={lastCallInfo}
              isTwilioMode={!voice.isCallActive && !!dashboard.activeCall}
            />
          </TabsContent>

          {/* History Tab */}
          <TabsContent value="history" className="space-y-6 animate-in">
            <CallHistoryCard calls={calls} callsTotal={callsTotal} onRefresh={handleRefreshCalls} onLoadMore={handleLoadMoreCalls} hasMore={calls.length < callsTotal} />
          </TabsContent>

          {/* Simulation Tab */}
          <TabsContent value="simulation" className="animate-in">
            <SimulationConsole
              scenarios={scenarios}
              activeScenarioId={settings?.active_scenario_id || null}
              onSaveScenario={handleSaveScenario}
              onCreateScenario={handleCreateScenario}
              onDeleteScenario={handleDeleteScenario}
              onRefreshScenarios={handleRefreshScenarios}
              onAddPatientToQueue={handleAddPatientToQueue}
            />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
