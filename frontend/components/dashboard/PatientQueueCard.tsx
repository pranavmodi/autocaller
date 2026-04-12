"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Users, Phone, RefreshCw, UserRound, Clock, RotateCcw, Pencil, Trash2 } from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import type { Patient } from "@/types";

interface PatientQueueCardProps {
  patients: Patient[];
  onCallPatient: (patientId: string) => void;
  onRefresh: () => void;
  onReloadScenario?: () => void;
  onDeletePatient?: (patientId: string) => Promise<void>;
  onUpdatePatient?: (patientId: string, data: {
    name?: string;
    phone?: string;
    language?: string;
    has_abandoned_before?: boolean;
    has_called_in_before?: boolean;
    ai_called_before?: boolean;
    attempt_count?: number;
  }) => Promise<void>;
  isCallActive: boolean;
  outboundAllowed: boolean;
  source?: "simulation" | "live";
  lastUpdated?: Date | null;
}

const priorityLabels: Record<number, string> = {
  1: "Abandoned, No AI Call",
  2: "Abandoned, AI Called",
  3: "No AI Call, Called In",
  4: "No AI Call, Never Called",
};

const priorityColors: Record<number, "destructive" | "warning" | "secondary" | "outline"> = {
  1: "destructive",
  2: "warning",
  3: "secondary",
  4: "outline",
};

function formatLastUpdated(date: Date | null | undefined): string {
  if (!date) return "";
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  return date.toLocaleTimeString();
}

export function PatientQueueCard({
  patients,
  onCallPatient,
  onRefresh,
  onReloadScenario,
  onDeletePatient,
  onUpdatePatient,
  isCallActive,
  outboundAllowed,
  source = "simulation",
  lastUpdated,
}: PatientQueueCardProps) {
  const [editingPatient, setEditingPatient] = useState<Patient | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    phone: "",
    language: "en",
    has_abandoned_before: false,
    has_called_in_before: false,
    ai_called_before: false,
    attempt_count: 0,
  });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleEditClick = (patient: Patient) => {
    setEditingPatient(patient);
    setEditForm({
      name: patient.name,
      phone: patient.phone,
      language: patient.language,
      has_abandoned_before: patient.has_abandoned_before,
      has_called_in_before: patient.has_called_in_before,
      ai_called_before: patient.ai_called_before,
      attempt_count: patient.attempt_count,
    });
  };

  const handleSaveEdit = async () => {
    if (!editingPatient || !onUpdatePatient) return;
    setSaving(true);
    try {
      await onUpdatePatient(editingPatient.patient_id, editForm);
      setEditingPatient(null);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (patientId: string) => {
    if (!onDeletePatient) return;
    if (!confirm("Delete this patient?")) return;
    setDeleting(patientId);
    try {
      await onDeletePatient(patientId);
    } finally {
      setDeleting(null);
    }
  };

  const isSimulation = source === "simulation";

  return (
    <>
      {/* Edit Patient Dialog */}
      <Dialog open={!!editingPatient} onOpenChange={(open) => !open && setEditingPatient(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Patient</DialogTitle>
            <DialogDescription>
              Update patient information. Changes will be saved to the active scenario.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="edit-name">Name</Label>
              <Input
                id="edit-name"
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-phone">Phone</Label>
              <Input
                id="edit-phone"
                value={editForm.phone}
                onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label>Language</Label>
              <Select
                value={editForm.language}
                onValueChange={(v) => setEditForm({ ...editForm, language: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="es">Spanish</SelectItem>
                  <SelectItem value="zh">Chinese</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-attempts">Attempt Count</Label>
              <Input
                id="edit-attempts"
                type="number"
                min={0}
                value={editForm.attempt_count}
                onChange={(e) => setEditForm({ ...editForm, attempt_count: parseInt(e.target.value) || 0 })}
              />
            </div>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editForm.has_abandoned_before}
                  onChange={(e) => setEditForm({ ...editForm, has_abandoned_before: e.target.checked })}
                  className="h-4 w-4"
                />
                Has abandoned
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editForm.has_called_in_before}
                  onChange={(e) => setEditForm({ ...editForm, has_called_in_before: e.target.checked })}
                  className="h-4 w-4"
                />
                Has called in
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editForm.ai_called_before}
                  onChange={(e) => setEditForm({ ...editForm, ai_called_before: e.target.checked })}
                  className="h-4 w-4"
                />
                AI called
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingPatient(null)}>
              Cancel
            </Button>
            <Button onClick={handleSaveEdit} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Main Card */}
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Users className="h-5 w-5" />
            Outbound Queue
            <InfoTooltip content="Patients awaiting outbound calls, sorted by priority. P1 = highest priority (abandoned, no AI call), P4 = lowest. Click Call to initiate." />
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant={source === "live" ? "default" : "secondary"}
              className="text-xs"
            >
              {source === "live" ? "Live RadFlow" : "Simulation"}
            </Badge>
            <Badge variant="outline" className="tabular-nums text-xs">
              {patients.length} patient{patients.length !== 1 ? "s" : ""}
            </Badge>
            {source === "simulation" && onReloadScenario && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={onReloadScenario}
                title="Reload scenario (reset patients)"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onRefresh} title="Refresh">
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        {lastUpdated && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
            <Clock className="h-3 w-3" />
            Updated {formatLastUpdated(lastUpdated)}
          </div>
        )}
      </CardHeader>
      <CardContent className="flex-1 p-0">
        <ScrollArea className="h-[400px]">
          <div className="space-y-1.5 px-6 pb-6">
            {patients.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <UserRound className="h-10 w-10 mb-3 opacity-20" />
                <p className="text-sm font-medium">No patients in queue</p>
                <p className="text-xs mt-1">Patients will appear here when added</p>
              </div>
            ) : (
              patients.map((patient, index) => (
                <div
                  key={patient.patient_id}
                  className="flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2.5 hover:bg-muted/70 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-muted-foreground tabular-nums w-5">
                        {index + 1}
                      </span>
                      <span className="text-sm font-medium truncate">{patient.name}</span>
                      <Badge variant={priorityColors[patient.priority_bucket]} className="text-[10px] px-1.5 py-0">
                        P{patient.priority_bucket}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2.5 mt-1 ml-7 text-xs text-muted-foreground">
                      <span className="font-mono">{patient.patient_id}</span>
                      <span className="tabular-nums">{patient.phone}</span>
                      <span className="uppercase font-medium">{patient.language}</span>
                      {patient.attempt_count > 0 && (
                        <span className="tabular-nums">{patient.attempt_count} attempt{patient.attempt_count !== 1 ? "s" : ""}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 ml-3 shrink-0">
                    {isSimulation && onUpdatePatient && (
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleEditClick(patient)}
                        className="h-8 w-8"
                        title="Edit patient"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    {isSimulation && onDeletePatient && (
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleDelete(patient.patient_id)}
                        disabled={deleting === patient.patient_id}
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        title="Delete patient"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onCallPatient(patient.patient_id)}
                      disabled={isCallActive || !outboundAllowed}
                      className="h-8 text-xs"
                    >
                      <Phone className="h-3 w-3 mr-1.5" />
                      Call
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
    </>
  );
}
