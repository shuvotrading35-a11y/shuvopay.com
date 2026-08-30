"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const PROVIDERS = ["bKash", "Nagad", "Rocket", "Upay", "Dutch-Bangla Bank", "BRAC Bank", "City Bank"];

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    amount: "", provider: "bKash", receiver_account: "", time_window_minutes: "30",
  });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const data: any = await api.get(`/merchant/transactions?page=${page}&page_size=20`);
      setInvoices(data.items ?? []);
      setTotal(data.total ?? 0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [page]);

  const handleCreate = async () => {
    if (!form.amount || isNaN(Number(form.amount))) {
      setError("Enter a valid amount");
      return;
    }
    setCreating(true);
    setError("");
    try {
      await api.post("/invoice", {
        amount: Number(form.amount),
        provider: form.provider,
        receiver_account: form.receiver_account || undefined,
        time_window_minutes: Number(form.time_window_minutes),
      });
      setShowCreate(false);
      setForm({ amount: "", provider: "bKash", receiver_account: "", time_window_minutes: "30" });
      load();
    } catch (e: any) {
      setError(e.message ?? "Failed to create invoice");
    } finally {
      setCreating(false);
    }
  };

  const handleCancel = async (id: string) => {
    if (!confirm("Cancel this invoice?")) return;
    try {
      await api.patch(`/invoice/${id}/cancel`);
      load();
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Invoices</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "Cancel" : "+ New Invoice"}
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader><CardTitle className="text-base">Create Invoice</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-sm font-medium">Amount (BDT)</label>
                <Input
                  type="number"
                  placeholder="500.00"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                />
              </div>
              <div>
                <label className="text-sm font-medium">Provider</label>
                <select
                  className="w-full rounded-md border px-3 py-2 text-sm"
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                >
                  {PROVIDERS.map((p) => <option key={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className="text-sm font-medium">Receiver Account (optional)</label>
                <Input
                  placeholder="01XXXXXXXXX"
                  value={form.receiver_account}
                  onChange={(e) => setForm({ ...form, receiver_account: e.target.value })}
                />
              </div>
              <div>
                <label className="text-sm font-medium">Time Window (minutes)</label>
                <Input
                  type="number"
                  value={form.time_window_minutes}
                  onChange={(e) => setForm({ ...form, time_window_minutes: e.target.value })}
                />
              </div>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? "Creating..." : "Create Invoice"}
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                {["Invoice #", "Amount", "Provider", "Status", "Expires", "Actions"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left font-medium text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr><td colSpan={6} className="py-8 text-center text-muted-foreground">Loading...</td></tr>
              ) : invoices.length === 0 ? (
                <tr><td colSpan={6} className="py-8 text-center text-muted-foreground">No invoices yet</td></tr>
              ) : (
                invoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-muted/30">
                    <td className="px-4 py-3 font-mono text-xs">{inv.invoice_number}</td>
                    <td className="px-4 py-3 font-semibold">BDT {Number(inv.amount).toLocaleString()}</td>
                    <td className="px-4 py-3">{inv.provider}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={inv.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {new Date(inv.expires_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      {inv.status === "pending" && (
                        <Button size="sm" variant="ghost" onClick={() => handleCancel(inv.id)}
                          className="text-red-600 hover:text-red-700">
                          Cancel
                        </Button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {total > 20 && (
            <div className="flex items-center justify-between border-t px-4 py-3">
              <span className="text-sm text-muted-foreground">{total} total</span>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
                <Button size="sm" variant="outline" disabled={page * 20 >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    paid: "bg-green-100 text-green-700",
    pending: "bg-yellow-100 text-yellow-700",
    review_required: "bg-orange-100 text-orange-700",
    unmatched: "bg-gray-100 text-gray-700",
    cancelled: "bg-red-100 text-red-600",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls[status] ?? ""}`}>{status.replace(/_/g, " ")}</span>;
}
