"use client";

import { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Trash2, RotateCcw, Shield } from "lucide-react";
import { useApi } from "@/hooks/useApi";

type ActionStatus = "idle" | "pending" | "success" | "error";

export default function AdminPage() {
  const api = useApi();

  const [callsStatus, setCallsStatus] = useState<ActionStatus>("idle");
  const [scenariosStatus, setScenariosStatus] = useState<ActionStatus>("idle");
  const [patientsStatus, setPatientsStatus] = useState<ActionStatus>("idle");

  const handleDeleteCalls = useCallback(async () => {
    if (!confirm("Delete all call logs and transcripts? This cannot be undone.")) return;
    setCallsStatus("pending");
    const ok = await api.deleteAllCalls();
    setCallsStatus(ok ? "success" : "error");
  }, [api]);

  const handleDeleteScenarios = useCallback(async () => {
    if (!confirm("Delete all custom simulation scenarios? Built-in scenarios will be kept.")) return;
    setScenariosStatus("pending");
    const ok = await api.deleteCustomScenarios();
    setScenariosStatus(ok ? "success" : "error");
  }, [api]);

  const handleResetPatients = useCallback(async () => {
    if (!confirm("Reset all patients to sample data? This will also clear call logs.")) return;
    setPatientsStatus("pending");
    try {
      await api.resetPatients();
      setPatientsStatus("success");
    } catch {
      setPatientsStatus("error");
    }
  }, [api]);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b bg-card/80 backdrop-blur-lg">
        <div className="container mx-auto px-6 h-16 flex items-center">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-destructive text-destructive-foreground shadow-sm">
              <Shield className="h-4 w-4" />
            </div>
            <div className="leading-tight">
              <h1 className="text-base font-semibold tracking-tight">Admin</h1>
              <p className="text-xs text-muted-foreground">Data management</p>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8 max-w-2xl space-y-6">
        {api.error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            {api.error}
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Danger Zone</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Delete Call Logs */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Delete all call logs</p>
                <p className="text-xs text-muted-foreground">
                  Removes all call records and transcripts from the database
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={callsStatus} />
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDeleteCalls}
                  disabled={callsStatus === "pending"}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                  Delete
                </Button>
              </div>
            </div>

            <Separator />

            {/* Delete Custom Scenarios */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Delete custom scenarios</p>
                <p className="text-xs text-muted-foreground">
                  Removes custom simulation scenarios (built-in ones are kept)
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={scenariosStatus} />
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDeleteScenarios}
                  disabled={scenariosStatus === "pending"}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                  Delete
                </Button>
              </div>
            </div>

            <Separator />

            {/* Reset Patients */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Reset patients to sample data</p>
                <p className="text-xs text-muted-foreground">
                  Clears all patients and call logs, re-seeds with sample data
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={patientsStatus} />
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleResetPatients}
                  disabled={patientsStatus === "pending"}
                >
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                  Reset
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

function StatusBadge({ status }: { status: ActionStatus }) {
  if (status === "idle") return null;
  if (status === "pending") return <Badge variant="secondary">Working...</Badge>;
  if (status === "success") return <Badge variant="success">Done</Badge>;
  return <Badge variant="destructive">Failed</Badge>;
}
