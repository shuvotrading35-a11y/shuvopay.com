"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function PendingReviewsPage() {
  const [reviews, setReviews] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [reason, setReason] = useState<Record<string, string>>({});

  const load = async () => {
    setLoading(true);
    try {
      const data: any[] = await api.get("/admin/pending-reviews");
      setReviews(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleAction = async (matchId: string, action: "approve" | "reject") => {
    const r = reason[matchId];
    if (!r?.trim()) {
      alert("Please enter a reason before taking action.");
      return;
    }
    if (!confirm(`${action === "approve" ? "Approve" : "Reject"} this match? Reason: "${r}"`)) return;

    setActionLoading(matchId);
    try {
      await api.patch(`/payment/${matchId}/${action}`, { reason: r });
      setReviews((prev) => prev.filter((rv) => rv.match_id !== matchId));
    } catch (e: any) {
      alert(e.message ?? "Action failed");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Pending Reviews</h1>
          <p className="text-sm text-muted-foreground">
            {reviews.length} match{reviews.length !== 1 ? "es" : ""} awaiting manual review
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={load}>Refresh</Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      ) : reviews.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            ✓ No pending reviews — all caught up!
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {reviews.map((rv) => (
            <Card key={rv.match_id} className="border-l-4 border-l-orange-400">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <CardTitle className="text-base">
                    {rv.invoice_number}
                    <span className="ml-2 text-sm font-normal text-muted-foreground">
                      Confidence: {(rv.confidence * 100).toFixed(1)}%
                    </span>
                  </CardTitle>
                  <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
                    Review Required
                  </span>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Side-by-side comparison */}
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-lg border p-4 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Invoice</p>
                    <p className="text-lg font-bold">BDT {rv.invoice_amount.toLocaleString()}</p>
                    <p className="text-sm text-muted-foreground">{rv.invoice_number}</p>
                  </div>
                  <div className="rounded-lg border p-4 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">SMS Match</p>
                    <p className="text-lg font-bold">BDT {rv.sms_amount?.toLocaleString() ?? "?"}</p>
                    <p className="text-sm text-muted-foreground">{rv.sms_provider} · {rv.sms_transaction_id}</p>
                  </div>
                </div>

                {/* Scoring breakdown */}
                <div className="rounded-md bg-muted/50 p-3 text-xs">
                  <p className="font-medium mb-2">Scoring Breakdown</p>
                  <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
                    {Object.entries(rv.breakdown ?? {}).map(([key, val]: [string, any]) => (
                      <div key={key} className={`rounded p-1.5 text-center ${val.matched ? "bg-green-100" : "bg-red-100"}`}>
                        <p className="font-medium">{key.replace("_", " ")}</p>
                        <p>{val.matched ? "✓" : "✗"} ({(val.score * 100).toFixed(0)}%)</p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Reason input + actions */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Enter reason (required)..."
                    value={reason[rv.match_id] ?? ""}
                    onChange={(e) => setReason((prev) => ({ ...prev, [rv.match_id]: e.target.value }))}
                    className="flex-1 rounded-md border px-3 py-2 text-sm"
                  />
                  <Button
                    size="sm"
                    onClick={() => handleAction(rv.match_id, "approve")}
                    disabled={actionLoading === rv.match_id}
                    className="bg-green-600 hover:bg-green-700 text-white"
                  >
                    {actionLoading === rv.match_id ? "…" : "Approve"}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => handleAction(rv.match_id, "reject")}
                    disabled={actionLoading === rv.match_id}
                  >
                    {actionLoading === rv.match_id ? "…" : "Reject"}
                  </Button>
                </div>

                <p className="text-xs text-muted-foreground">
                  Matched at {new Date(rv.matched_at).toLocaleString()}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
