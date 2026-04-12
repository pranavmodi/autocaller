"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Phone,
  Users,
  Plus,
  Trash2,
  Save,
  Copy,
  Settings2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import type { SimulationScenario, ScenarioPatient, QueueInfo, Patient } from "@/types";

interface QueueRow {
  Queue: string;
  Calls: number;
  Holdtime: number;
  AvailableAgents: number;
}

interface SimulationConsoleProps {
  scenarios: SimulationScenario[];
  activeScenarioId: string | null;
  onSaveScenario: (id: string, data: {
    label?: string;
    description?: string;
    ami_connected?: boolean;
    queues?: QueueRow[];
    patients?: ScenarioPatient[];
  }) => Promise<SimulationScenario | null>;
  onCreateScenario: (data: {
    label: string;
    description?: string;
    ami_connected?: boolean;
    queues?: QueueRow[];
    patients?: ScenarioPatient[];
  }) => Promise<SimulationScenario | null>;
  onDeleteScenario: (id: string) => Promise<boolean>;
  onRefreshScenarios: () => Promise<void>;
  onAddPatientToQueue?: (data: {
    name: string;
    phone: string;
    language?: string;
    has_abandoned_before?: boolean;
    has_called_in_before?: boolean;
    ai_called_before?: boolean;
    attempt_count?: number;
  }) => Promise<{ patient: Patient; saved_to_scenario: boolean } | null>;
}

function mkQueue(Queue: string, overrides: Partial<QueueRow> = {}): QueueRow {
  return {
    Queue,
    Calls: 0,
    Holdtime: 0,
    AvailableAgents: 0,
    ...overrides,
  };
}

function mkPatient(overrides: Partial<ScenarioPatient> = {}): ScenarioPatient {
  return {
    name: "",
    phone: "",
    language: "en",
    has_abandoned_before: false,
    has_called_in_before: false,
    ai_called_before: false,
    attempt_count: 0,
    ...overrides,
  };
}

export function SimulationConsole({
  scenarios,
  activeScenarioId,
  onSaveScenario,
  onCreateScenario,
  onDeleteScenario,
  onRefreshScenarios,
  onAddPatientToQueue,
}: SimulationConsoleProps) {
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [amiConnected, setAmiConnected] = useState(true);
  const [queues, setQueues] = useState<QueueRow[]>([]);
  const [patients, setPatients] = useState<ScenarioPatient[]>([]);
  const [isDirty, setIsDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Add patient to queue form state
  const [newPatientName, setNewPatientName] = useState("");
  const [newPatientPhone, setNewPatientPhone] = useState("");
  const [newPatientLanguage, setNewPatientLanguage] = useState("en");
  const [newPatientAbandoned, setNewPatientAbandoned] = useState(false);
  const [newPatientCalledIn, setNewPatientCalledIn] = useState(false);
  const [newPatientAiCalled, setNewPatientAiCalled] = useState(false);
  const [addingPatient, setAddingPatient] = useState(false);

  const selectedScenario = scenarios.find(s => s.id === selectedScenarioId);

  // Load scenario data when selection changes
  const loadScenario = useCallback((scenario: SimulationScenario) => {
    setLabel(scenario.label);
    setDescription(scenario.description);
    setAmiConnected(scenario.ami_connected);
    setQueues((scenario.queues || []).map(q => ({
      Queue: q.Queue || "",
      Calls: q.Calls || 0,
      Holdtime: q.Holdtime || 0,
      AvailableAgents: q.AvailableAgents || 0,
    })));
    setPatients((scenario.patients || []).map(p => ({ ...mkPatient(), ...p })));
    setIsDirty(false);
    setFeedback(null);
  }, []);

  // Initialize with first scenario or active scenario
  useEffect(() => {
    if (scenarios.length > 0 && !selectedScenarioId) {
      const initialId = activeScenarioId || scenarios[0].id;
      setSelectedScenarioId(initialId);
      const scenario = scenarios.find(s => s.id === initialId);
      if (scenario) loadScenario(scenario);
    }
  }, [scenarios, activeScenarioId, selectedScenarioId, loadScenario]);

  const handleSelectScenario = (scenarioId: string) => {
    const scenario = scenarios.find(s => s.id === scenarioId);
    if (scenario) {
      setSelectedScenarioId(scenarioId);
      loadScenario(scenario);
    }
  };

  // Queue handlers
  const updateQueue = (index: number, field: keyof QueueRow, value: string | number) => {
    setQueues(prev => prev.map((q, i) => i === index ? { ...q, [field]: value } : q));
    setIsDirty(true);
  };

  const addQueue = () => {
    setQueues(prev => [...prev, mkQueue("")]);
    setIsDirty(true);
  };

  const removeQueue = (index: number) => {
    setQueues(prev => prev.filter((_, i) => i !== index));
    setIsDirty(true);
  };

  // Patient handlers
  const updatePatient = (index: number, field: keyof ScenarioPatient, value: string | number | boolean) => {
    setPatients(prev => prev.map((p, i) => i === index ? { ...p, [field]: value } : p));
    setIsDirty(true);
  };

  const addPatient = () => {
    setPatients(prev => [...prev, mkPatient()]);
    setIsDirty(true);
  };

  const removePatient = (index: number) => {
    setPatients(prev => prev.filter((_, i) => i !== index));
    setIsDirty(true);
  };

  const handleFieldChange = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setter(e.target.value);
    setIsDirty(true);
  };

  // Save existing scenario
  const handleSave = async () => {
    if (!selectedScenarioId) return;
    setSaving(true);
    setFeedback(null);
    try {
      const result = await onSaveScenario(selectedScenarioId, {
        label,
        description,
        ami_connected: amiConnected,
        queues,
        patients,
      });
      if (result) {
        setFeedback({ type: "success", message: "Scenario saved successfully." });
        setIsDirty(false);
        await onRefreshScenarios();
      } else {
        setFeedback({ type: "error", message: "Failed to save scenario." });
      }
    } catch {
      setFeedback({ type: "error", message: "Failed to save scenario." });
    } finally {
      setSaving(false);
    }
  };

  // Save as new scenario
  const handleSaveAsNew = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const result = await onCreateScenario({
        label: label + " (Copy)",
        description,
        ami_connected: amiConnected,
        queues,
        patients,
      });
      if (result) {
        setFeedback({ type: "success", message: "New scenario created successfully." });
        await onRefreshScenarios();
        // Select the new scenario
        setSelectedScenarioId(result.id);
        setLabel(result.label);
        setIsDirty(false);
      } else {
        setFeedback({ type: "error", message: "Failed to create scenario." });
      }
    } catch {
      setFeedback({ type: "error", message: "Failed to create scenario." });
    } finally {
      setSaving(false);
    }
  };

  // Delete scenario
  const handleDelete = async () => {
    if (!selectedScenarioId) return;
    if (!confirm("Are you sure you want to delete this scenario?")) return;
    setSaving(true);
    setFeedback(null);
    try {
      const success = await onDeleteScenario(selectedScenarioId);
      if (success) {
        setFeedback({ type: "success", message: "Scenario deleted." });
        await onRefreshScenarios();
        // Select first available scenario
        const remaining = scenarios.filter(s => s.id !== selectedScenarioId);
        if (remaining.length > 0) {
          setSelectedScenarioId(remaining[0].id);
          loadScenario(remaining[0]);
        }
      } else {
        setFeedback({ type: "error", message: "Failed to delete scenario." });
      }
    } catch {
      setFeedback({ type: "error", message: "Failed to delete scenario." });
    } finally {
      setSaving(false);
    }
  };

  // Add patient to queue and scenario
  const handleAddPatientToQueue = async () => {
    if (!onAddPatientToQueue || !newPatientName.trim() || !newPatientPhone.trim()) return;
    setAddingPatient(true);
    setFeedback(null);
    try {
      const result = await onAddPatientToQueue({
        name: newPatientName.trim(),
        phone: newPatientPhone.trim(),
        language: newPatientLanguage,
        has_abandoned_before: newPatientAbandoned,
        has_called_in_before: newPatientCalledIn,
        ai_called_before: newPatientAiCalled,
        attempt_count: 0,
      });
      if (result) {
        const scenarioMsg = result.saved_to_scenario
          ? " and saved to scenario."
          : " to queue. Use 'Save As New' to create a custom scenario for persistent changes.";
        setFeedback({ type: "success", message: `Patient "${newPatientName}" added${scenarioMsg}` });

        // Add to local patients state so it shows in the table
        setPatients(prev => [...prev, {
          name: result.patient.name,
          phone: result.patient.phone,
          language: result.patient.language,
          has_abandoned_before: result.patient.has_abandoned_before,
          has_called_in_before: result.patient.has_called_in_before,
          ai_called_before: result.patient.ai_called_before,
          attempt_count: result.patient.attempt_count,
        }]);

        // Reset form
        setNewPatientName("");
        setNewPatientPhone("");
        setNewPatientLanguage("en");
        setNewPatientAbandoned(false);
        setNewPatientCalledIn(false);
        setNewPatientAiCalled(false);

        if (result.saved_to_scenario) {
          await onRefreshScenarios();
          setIsDirty(false);
        } else {
          // Mark as dirty so user knows there are unsaved changes
          setIsDirty(true);
        }
      } else {
        setFeedback({ type: "error", message: "Failed to add patient." });
      }
    } catch {
      setFeedback({ type: "error", message: "Failed to add patient." });
    } finally {
      setAddingPatient(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Feedback */}
      {feedback && (
        <div className={`rounded-md p-4 ${feedback.type === "success" ? "bg-green-500/10 text-green-700 dark:text-green-400" : "bg-destructive/10 text-destructive"}`}>
          {feedback.message}
        </div>
      )}

      {/* Scenario Selector and Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-5 w-5" />
            Scenario Editor
          </CardTitle>
          <CardDescription>
            Edit simulation scenarios. Builtins are read-only — use "Save As New" to create a custom copy.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1 space-y-1.5">
              <Label>Select Scenario</Label>
              <Select value={selectedScenarioId} onValueChange={handleSelectScenario}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a scenario..." />
                </SelectTrigger>
                <SelectContent>
                  {scenarios.map(s => (
                    <SelectItem key={s.id} value={s.id}>
                      <span className="flex items-center gap-2">
                        {s.label}
                        {s.is_builtin && <Badge variant="outline" className="text-xs">Builtin</Badge>}
                        {s.id === activeScenarioId && <Badge variant="success" className="text-xs">Active</Badge>}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="scenario-label">Label</Label>
              <Input
                id="scenario-label"
                value={label}
                onChange={handleFieldChange(setLabel)}
                disabled={false}
                placeholder="Scenario name"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5">
                AMI Connection
                <InfoTooltip content="Simulates the Asterisk Manager Interface connection status. When disconnected, all outbound calls are blocked as a safety measure." />
              </Label>
              <div className="flex items-center gap-2 pt-2">
                <Button
                  variant={amiConnected ? "default" : "outline"}
                  size="sm"
                  onClick={() => { setAmiConnected(true); setIsDirty(true); }}
                  disabled={false}
                >
                  <Wifi className="h-4 w-4 mr-1" />
                  Connected
                </Button>
                <Button
                  variant={!amiConnected ? "destructive" : "outline"}
                  size="sm"
                  onClick={() => { setAmiConnected(false); setIsDirty(true); }}
                  disabled={false}
                >
                  <WifiOff className="h-4 w-4 mr-1" />
                  Disconnected
                </Button>
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="scenario-description">Description</Label>
            <Textarea
              id="scenario-description"
              value={description}
              onChange={handleFieldChange(setDescription)}
              disabled={false}
              placeholder="Describe this scenario..."
              rows={2}
            />
          </div>
        </CardContent>
      </Card>

      {/* Queue Configuration */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Phone className="h-5 w-5" />
                Queue Configuration
              </CardTitle>
              <CardDescription>
                Simulates FreePBX/Asterisk call queues. The dispatcher checks these metrics each tick.
              </CardDescription>
            </div>
            <Badge variant="secondary">{queues.length} queues</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Queue
                      <InfoTooltip content="Queue ID (e.g., 9006, 9009, 9012). Matches FreePBX queue IDs." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Calls
                      <InfoTooltip content="Number of inbound calls currently waiting in this queue. High values block outbound calls." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Holdtime (s)
                      <InfoTooltip content="Longest wait time in seconds for any caller in this queue. High values block outbound." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Avail Agents
                      <InfoTooltip content="Number of agents logged in and available to take calls. Zero agents blocks outbound calls." />
                    </span>
                  </th>
                  <th className="pb-1"></th>
                </tr>
              </thead>
              <tbody>
                {queues.map((q, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-2 pr-2">
                      <Input
                        value={q.Queue}
                        onChange={e => updateQueue(i, "Queue", e.target.value)}
                        className="h-8"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <Input
                        type="number"
                        min={0}
                        value={q.Calls}
                        onChange={e => updateQueue(i, "Calls", parseInt(e.target.value) || 0)}
                        className="h-8 w-20"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <Input
                        type="number"
                        min={0}
                        value={q.Holdtime}
                        onChange={e => updateQueue(i, "Holdtime", parseInt(e.target.value) || 0)}
                        className="h-8 w-20"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <Input
                        type="number"
                        min={0}
                        value={q.AvailableAgents}
                        onChange={e => updateQueue(i, "AvailableAgents", parseInt(e.target.value) || 0)}
                        className="h-8 w-20"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2">
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => removeQueue(i)}>
                        <Trash2 className="h-4 w-4 text-muted-foreground" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Button variant="outline" size="sm" onClick={addQueue}>
            <Plus className="h-4 w-4 mr-1" />
            Add Queue
          </Button>
        </CardContent>
      </Card>

      {/* Patient List */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5" />
                Patient List
              </CardTitle>
              <CardDescription>
                Mock patient records for the outbound call queue.
              </CardDescription>
            </div>
            <Badge variant="secondary">{patients.length} patients</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="pb-1 pr-2">Name</th>
                  <th className="pb-1 pr-2">Phone</th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Lang
                      <InfoTooltip content="Patient's preferred language. AI greets in this language and routes to matching queue." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Aband.
                      <InfoTooltip content="Has Abandoned: Patient previously hung up before completing. Higher priority for callbacks." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Called
                      <InfoTooltip content="Has Called In: Patient has previously called the center. May indicate active engagement." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      AI
                      <InfoTooltip content="AI Called Before: Patient has received a previous AI outbound call. Affects priority bucket." />
                    </span>
                  </th>
                  <th className="pb-1 pr-2">
                    <span className="flex items-center gap-1">
                      Att.
                      <InfoTooltip content="Attempt Count: Number of call attempts made. When max attempts reached, patient is skipped." />
                    </span>
                  </th>
                  <th className="pb-1"></th>
                </tr>
              </thead>
              <tbody>
                {patients.map((p, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-2 pr-2">
                      <Input
                        value={p.name}
                        onChange={e => updatePatient(i, "name", e.target.value)}
                        className="h-8"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <Input
                        value={p.phone}
                        onChange={e => updatePatient(i, "phone", e.target.value)}
                        className="h-8 w-28"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <Select
                        value={p.language}
                        onValueChange={v => updatePatient(i, "language", v)}
                        disabled={false}
                      >
                        <SelectTrigger className="h-8 w-20">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="en">EN</SelectItem>
                          <SelectItem value="es">ES</SelectItem>
                          <SelectItem value="zh">ZH</SelectItem>
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="py-2 pr-2 text-center">
                      <input
                        type="checkbox"
                        checked={p.has_abandoned_before}
                        onChange={e => updatePatient(i, "has_abandoned_before", e.target.checked)}
                        className="h-4 w-4"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2 text-center">
                      <input
                        type="checkbox"
                        checked={p.has_called_in_before}
                        onChange={e => updatePatient(i, "has_called_in_before", e.target.checked)}
                        className="h-4 w-4"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2 text-center">
                      <input
                        type="checkbox"
                        checked={p.ai_called_before}
                        onChange={e => updatePatient(i, "ai_called_before", e.target.checked)}
                        className="h-4 w-4"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <Input
                        type="number"
                        min={0}
                        value={p.attempt_count}
                        onChange={e => updatePatient(i, "attempt_count", parseInt(e.target.value) || 0)}
                        className="h-8 w-16"
                        disabled={false}
                      />
                    </td>
                    <td className="py-2">
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => removePatient(i)}>
                        <Trash2 className="h-4 w-4 text-muted-foreground" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Add new patient inline form */}
          {onAddPatientToQueue && (
            <div className="border-t pt-4 mt-4">
              <div className="text-sm font-medium mb-3">Add New Patient</div>
              <div className="flex flex-wrap items-end gap-2">
                <Input
                  value={newPatientName}
                  onChange={e => setNewPatientName(e.target.value)}
                  placeholder="Name"
                  className="h-8 w-32"
                />
                <Input
                  value={newPatientPhone}
                  onChange={e => setNewPatientPhone(e.target.value)}
                  placeholder="Phone"
                  className="h-8 w-28"
                />
                <Select value={newPatientLanguage} onValueChange={setNewPatientLanguage}>
                  <SelectTrigger className="h-8 w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">EN</SelectItem>
                    <SelectItem value="es">ES</SelectItem>
                    <SelectItem value="zh">ZH</SelectItem>
                  </SelectContent>
                </Select>
                <label className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={newPatientAbandoned}
                    onChange={e => setNewPatientAbandoned(e.target.checked)}
                    className="h-4 w-4"
                  />
                  Aband.
                </label>
                <label className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={newPatientCalledIn}
                    onChange={e => setNewPatientCalledIn(e.target.checked)}
                    className="h-4 w-4"
                  />
                  Called
                </label>
                <label className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={newPatientAiCalled}
                    onChange={e => setNewPatientAiCalled(e.target.checked)}
                    className="h-4 w-4"
                  />
                  AI
                </label>
                <Button
                  size="sm"
                  onClick={handleAddPatientToQueue}
                  disabled={addingPatient || !newPatientName.trim() || !newPatientPhone.trim()}
                  className="h-8"
                >
                  <Plus className="h-4 w-4 mr-1" />
                  {addingPatient ? "Adding..." : "Add"}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Action Buttons */}
      <div className="flex justify-end gap-3">
        <Button variant="destructive" size="sm" onClick={handleDelete} disabled={saving}>
          <Trash2 className="h-4 w-4 mr-1" />
          Delete
        </Button>
        <Button variant="outline" onClick={handleSaveAsNew} disabled={saving}>
          <Copy className="h-4 w-4 mr-1" />
          Save As New
        </Button>
        <Button onClick={handleSave} disabled={saving || !isDirty}>
          <Save className="h-4 w-4 mr-1" />
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </div>
  );
}
