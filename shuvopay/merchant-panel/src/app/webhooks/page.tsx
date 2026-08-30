"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function WebhooksPage() {
  const [url, setUrl] = useState("");
  const [rotateSecret, setRotateSecret] = useState(false);
  const [saving, setSaving] = useState(false);
  const [newSecret, setNewSecret] = useState<string | null>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);

  const loadLogs = async () => {
    try {
      const data: any[] = await api.get("/webhook/logs");
      setLogs(data);
    } catch {}
  };

  useEffect(() => { loadLogs(); }, []);

  const save = async () => {
    setSaving(true);
    setNewSecret(null);
    try {
      const res: any = await api.post("/webhook/settings", {
        webhook_url: url,
        rotate_secret: rotateSecret,
      });
      if (res.secret) setNewSecret(res.secret);
      setRotateSecret(false);
      alert("Webhook settings saved");
    } catch (e: any) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.post("/webhook/test");
      setTestResult(res);
    } catch (e: any) {
      setTestResult({ success: false, error: e.message });
    } finally {
      setTesting(false);
    }
  };

  const retry = async (id: string) => {
    try {
      await api.post(`/webhook/retry/${id}`);
      loadLogs();
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-bold">Webhooks</h1>

      <Card>
        <CardHeader><CardTitle className="text-base">Configuration</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium">Webhook URL</label>
            <Input
              placeholder="https://yourserver.com/webhook"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="mt-1"
            />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={rotateSecret} onChange={(e) => setRotateSecret(e.target.checked)} />
            Rotate signing secret
          </label>
          <div className="flex gap-2">
            <Button onClick={save} disabled={saving || !url}>
              {saving ? "Saving..." : "Save"}
            </Button>
            <Button variant="outline" onClick={test} disabled={testing || !url}>
              {testing ? "Sending..." : "Send Test"}
            </Button>
          </div>

          {newSecret && (
            <div className="rounded-md bg-yellow-50 border border-yellow-200 p-3">
              <p className="text-sm font-medium text-yellow-800">⚠️ New signing secret — copy now, it won't be shown again:</p>
              <code className="mt-1 block break-all text-xs font-mono text-yellow-900">{newSecret}</code>
            </div>
          )}

          {testResult && (
            <div className={`rounded-md p-3 text-sm ${testResult.success ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
              {testResult.success
                ? `✓ Test delivered (HTTP ${testResult.status})`
                : `✗ Test failed: ${testResult.error ?? testResult.status}`}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Delivery Logs</CardTitle>
            <Button size="sm" variant="outline" onClick={loadLogs}>Refresh</Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                {["Time", "Status", "Attempts", "Response", "Actions"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left font-medium text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {logs.length === 0 ? (
                <tr><td colSpan={5} className="py-8 text-center text-muted-foreground">No webhook deliveries yet</td></tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id}>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {log.last_attempted_at ? new Date(log.last_attempted_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        log.status === "delivered" ? "bg-green-100 text-green-700" :
                        log.status === "dead" ? "bg-red-100 text-red-700" :
                        "bg-yellow-100 text-yellow-700"
                      }`}>{log.status}</span>
                    </td>
                    <td className="px-4 py-3">{log.attempt_count}</td>
                    <td className="px-4 py-3 text-xs">{log.last_response_status ?? "—"}</td>
                    <td className="px-4 py-3">
                      {log.status !== "delivered" && (
                        <Button size="sm" variant="ghost" onClick={() => retry(log.id)}>Retry</Button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Verifying Webhook Signatures</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>Every webhook delivery includes two headers:</p>
          <pre className="rounded bg-muted p-3 text-xs overflow-x-auto">{`X-ShuvoPay-Signature: sha256=<hmac_hex>
X-ShuvoPay-Timestamp: <unix_epoch>`}</pre>
          <p>Verify in Python:</p>
          <pre className="rounded bg-muted p-3 text-xs overflow-x-auto">{`import hmac, hashlib, time

def verify(body: bytes, signature: str, timestamp: str, secret: str) -> bool:
    # Reject if timestamp is >5 minutes old (replay protection)
    if abs(time.time() - int(timestamp)) > 300:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)`}</pre>
        </CardContent>
      </Card>
    </div>
  );
}
