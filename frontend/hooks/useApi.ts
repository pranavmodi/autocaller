"use client";

import { useState, useCallback, useMemo } from "react";
import type { SystemStatus, Patient, CallLog, QueueState, SystemSettings, BusinessHours, QueueThresholds, DispatcherSettings, SimulationScenario, ScenarioPatient, TodayKpis, TimePerformance } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getStatus = useCallback(async (): Promise<SystemStatus | null> => {
    setLoading(true);
    setError(null);
    try {
      return await fetchApi<SystemStatus>("/api/status");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const getQueueState = useCallback(async (): Promise<QueueState | null> => {
    try {
      return await fetchApi<QueueState>("/api/queue");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const getPatients = useCallback(async (): Promise<Patient[]> => {
    try {
      const data = await fetchApi<{ patients: Patient[] }>("/api/patients");
      return data.patients;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return [];
    }
  }, []);

  const getOutboundQueue = useCallback(async (): Promise<Patient[]> => {
    try {
      const data = await fetchApi<{ queue: Patient[] }>("/api/patients/queue");
      return data.queue;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return [];
    }
  }, []);

  const getCalls = useCallback(async (limit: number = 25, offset: number = 0): Promise<{ calls: CallLog[]; total: number }> => {
    try {
      const data = await fetchApi<{ calls: CallLog[]; total: number }>(`/api/calls?limit=${limit}&offset=${offset}`);
      return { calls: data.calls, total: data.total };
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return { calls: [], total: 0 };
    }
  }, []);

  const getCall = useCallback(async (callId: string): Promise<CallLog | null> => {
    try {
      return await fetchApi<CallLog>(`/api/calls/${callId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const getTodayKpis = useCallback(async (): Promise<TodayKpis | null> => {
    try {
      return await fetchApi<TodayKpis>(`/api/statistics/today`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const simulateBusyQueue = useCallback(async (): Promise<QueueState | null> => {
    try {
      const data = await fetchApi<{ queue_state: QueueState }>("/api/queue/simulate/busy", {
        method: "POST",
      });
      return data.queue_state;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const simulateQuietQueue = useCallback(async (): Promise<QueueState | null> => {
    try {
      const data = await fetchApi<{ queue_state: QueueState }>("/api/queue/simulate/quiet", {
        method: "POST",
      });
      return data.queue_state;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const simulateAmiFailure = useCallback(async (): Promise<QueueState | null> => {
    try {
      const data = await fetchApi<{ queue_state: QueueState }>("/api/queue/simulate/ami-failure", {
        method: "POST",
      });
      return data.queue_state;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const simulateAmiRecovery = useCallback(async (): Promise<QueueState | null> => {
    try {
      const data = await fetchApi<{ queue_state: QueueState }>("/api/queue/simulate/ami-recovery", {
        method: "POST",
      });
      return data.queue_state;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const resetPatients = useCallback(async (): Promise<void> => {
    try {
      await fetchApi("/api/patients/reset", { method: "POST" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    }
  }, []);

  const addPatient = useCallback(async (data: {
    name: string;
    phone: string;
    language?: string;
    has_abandoned_before?: boolean;
    has_called_in_before?: boolean;
    ai_called_before?: boolean;
    attempt_count?: number;
  }): Promise<{ patient: Patient; saved_to_scenario: boolean } | null> => {
    try {
      const params = new URLSearchParams();
      params.set("name", data.name);
      params.set("phone", data.phone);
      if (data.language) params.set("language", data.language);
      if (data.has_abandoned_before !== undefined) params.set("has_abandoned_before", String(data.has_abandoned_before));
      if (data.has_called_in_before !== undefined) params.set("has_called_in_before", String(data.has_called_in_before));
      if (data.ai_called_before !== undefined) params.set("ai_called_before", String(data.ai_called_before));
      if (data.attempt_count !== undefined) params.set("attempt_count", String(data.attempt_count));

      const result = await fetchApi<{ status: string; patient: Patient; saved_to_scenario: boolean }>(`/api/patients?${params.toString()}`, {
        method: "POST",
      });
      return { patient: result.patient, saved_to_scenario: result.saved_to_scenario };
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const deletePatient = useCallback(async (patientId: string): Promise<{ removed_from_scenario: boolean } | null> => {
    try {
      const result = await fetchApi<{ status: string; removed_from_scenario: boolean }>(`/api/patients/${patientId}`, {
        method: "DELETE",
      });
      return { removed_from_scenario: result.removed_from_scenario };
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updatePatient = useCallback(async (patientId: string, data: {
    name?: string;
    phone?: string;
    language?: string;
    has_abandoned_before?: boolean;
    has_called_in_before?: boolean;
    ai_called_before?: boolean;
    attempt_count?: number;
  }): Promise<{ patient: Patient; updated_in_scenario: boolean } | null> => {
    try {
      const params = new URLSearchParams();
      if (data.name !== undefined) params.set("name", data.name);
      if (data.phone !== undefined) params.set("phone", data.phone);
      if (data.language !== undefined) params.set("language", data.language);
      if (data.has_abandoned_before !== undefined) params.set("has_abandoned_before", String(data.has_abandoned_before));
      if (data.has_called_in_before !== undefined) params.set("has_called_in_before", String(data.has_called_in_before));
      if (data.ai_called_before !== undefined) params.set("ai_called_before", String(data.ai_called_before));
      if (data.attempt_count !== undefined) params.set("attempt_count", String(data.attempt_count));

      const result = await fetchApi<{ status: string; patient: Patient; updated_in_scenario: boolean }>(`/api/patients/${patientId}?${params.toString()}`, {
        method: "PUT",
      });
      return { patient: result.patient, updated_in_scenario: result.updated_in_scenario };
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  // Scenarios API methods
  const getScenarios = useCallback(async (): Promise<SimulationScenario[]> => {
    try {
      return await fetchApi<SimulationScenario[]>("/api/scenarios");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return [];
    }
  }, []);

  const getScenario = useCallback(async (id: string): Promise<SimulationScenario | null> => {
    try {
      return await fetchApi<SimulationScenario>(`/api/scenarios/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const createScenario = useCallback(async (data: {
    label: string;
    description?: string;
    ami_connected?: boolean;
    queues?: Array<{ Queue: string; Calls?: number; Holdtime?: number; AvailableAgents?: number }>;
    patients?: ScenarioPatient[];
  }): Promise<SimulationScenario | null> => {
    try {
      return await fetchApi<SimulationScenario>("/api/scenarios", {
        method: "POST",
        body: JSON.stringify(data),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateScenario = useCallback(async (id: string, data: {
    label?: string;
    description?: string;
    ami_connected?: boolean;
    queues?: Array<{ Queue: string; Calls?: number; Holdtime?: number; AvailableAgents?: number }>;
    patients?: ScenarioPatient[];
  }): Promise<SimulationScenario | null> => {
    try {
      return await fetchApi<SimulationScenario>(`/api/scenarios/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const deleteScenario = useCallback(async (id: string): Promise<boolean> => {
    try {
      await fetchApi(`/api/scenarios/${id}`, { method: "DELETE" });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return false;
    }
  }, []);

  const deleteCustomScenarios = useCallback(async (): Promise<boolean> => {
    try {
      await fetchApi("/api/scenarios", { method: "DELETE" });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return false;
    }
  }, []);

  const setActiveScenario = useCallback(async (scenarioId: string): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/active-scenario", {
        method: "PUT",
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  // Settings API methods
  const getSettings = useCallback(async (): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateSettings = useCallback(async (settings: Omit<SystemSettings, 'can_make_calls' | 'is_within_business_hours'>): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(settings),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const setSystemEnabled = useCallback(async (enabled: boolean): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/system-enabled", {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateBusinessHours = useCallback(async (businessHours: BusinessHours): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/business-hours", {
        method: "PUT",
        body: JSON.stringify(businessHours),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateQueueThresholds = useCallback(async (thresholds: QueueThresholds): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/queue-thresholds", {
        method: "PUT",
        body: JSON.stringify(thresholds),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateDispatcherSettings = useCallback(async (dispatcherSettings: DispatcherSettings): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/dispatcher", {
        method: "PUT",
        body: JSON.stringify(dispatcherSettings),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const setAllowLiveCalls = useCallback(async (allowed: boolean): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/allow-live-calls", {
        method: "PUT",
        body: JSON.stringify({ allowed }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateAllowedPhones = useCallback(async (phones: string[]): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/allowed-phones", {
        method: "PUT",
        body: JSON.stringify({ phones }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const setQueueSource = useCallback(async (source: string): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/queue-source", {
        method: "PUT",
        body: JSON.stringify({ source }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const setPatientSource = useCallback(async (source: string): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/patient-source", {
        method: "PUT",
        body: JSON.stringify({ source }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const setCallMode = useCallback(async (callMode: string): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/call-mode", {
        method: "PUT",
        body: JSON.stringify({ call_mode: callMode }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const setMockMode = useCallback(async (enabled: boolean, mock_phone: string): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/mock-mode", {
        method: "PUT",
        body: JSON.stringify({ enabled, mock_phone }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const updateDailyReport = useCallback(async (config: {
    enabled: boolean;
    webhook_url: string;
    hour: number;
    timezone: string;
  }): Promise<SystemSettings | null> => {
    try {
      return await fetchApi<SystemSettings>("/api/settings/daily-report", {
        method: "PUT",
        body: JSON.stringify(config),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const sendTestDailyReport = useCallback(async (): Promise<{ sent: boolean } | null> => {
    try {
      return await fetchApi<{ sent: boolean }>(`/api/reports/daily/test`, { method: "POST" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const getTimePerformance = useCallback(async (days: number = 90): Promise<TimePerformance | null> => {
    try {
      return await fetchApi<TimePerformance>(`/api/statistics/time-performance?days=${days}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return null;
    }
  }, []);

  const deleteAllCalls = useCallback(async (): Promise<boolean> => {
    try {
      await fetchApi("/api/calls", { method: "DELETE" });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return false;
    }
  }, []);

  const getTimezones = useCallback(async (): Promise<string[]> => {
    try {
      return await fetchApi<string[]>("/api/settings/timezones");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      return [];
    }
  }, []);

  return useMemo(() => ({
    loading,
    error,
    getStatus,
    getQueueState,
    getPatients,
    getOutboundQueue,
    getCalls,
    getCall,
    getTodayKpis,
    simulateBusyQueue,
    simulateQuietQueue,
    simulateAmiFailure,
    simulateAmiRecovery,
    resetPatients,
    addPatient,
    deletePatient,
    updatePatient,
    getScenarios,
    getScenario,
    createScenario,
    updateScenario,
    deleteScenario,
    deleteCustomScenarios,
    setActiveScenario,
    getSettings,
    updateSettings,
    setSystemEnabled,
    updateBusinessHours,
    updateQueueThresholds,
    updateDispatcherSettings,
    setAllowLiveCalls,
    updateAllowedPhones,
    setQueueSource,
    setPatientSource,
    setCallMode,
    setMockMode,
    updateDailyReport,
    sendTestDailyReport,
    getTimePerformance,
    getTimezones,
    deleteAllCalls,
  }), [
    loading,
    error,
    getStatus,
    getQueueState,
    getPatients,
    getOutboundQueue,
    getCalls,
    getCall,
    getTodayKpis,
    simulateBusyQueue,
    simulateQuietQueue,
    simulateAmiFailure,
    simulateAmiRecovery,
    resetPatients,
    addPatient,
    deletePatient,
    updatePatient,
    getScenarios,
    getScenario,
    createScenario,
    updateScenario,
    deleteScenario,
    deleteCustomScenarios,
    setActiveScenario,
    getSettings,
    updateSettings,
    setSystemEnabled,
    updateBusinessHours,
    updateQueueThresholds,
    updateDispatcherSettings,
    setAllowLiveCalls,
    updateAllowedPhones,
    setQueueSource,
    setPatientSource,
    setCallMode,
    setMockMode,
    updateDailyReport,
    sendTestDailyReport,
    getTimePerformance,
    getTimezones,
    deleteAllCalls,
  ]);
}
