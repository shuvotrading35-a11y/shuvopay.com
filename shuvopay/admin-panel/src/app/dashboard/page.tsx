"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const data = await api.get("/admin/dashboard");
      setStats(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) return (
    <div className="flex h-full items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
    </div>
  );

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">System Dashboard</h1>
          <p className="text-sm text-muted-foreground">ShuvoPay Admin — full system visibility</p>
        </div>
        <Button size="sm" onClick={load}>Refresh</Button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard title="Total Merchants" value={stats?.total_merchants} />
        <StatCard title="Active Devices" value={`${stats?.online_devices} / ${stats?.total_devices}`} label="Online" />
        <StatCard title="Total SMS" value={stats?.total_sms} />
        <StatCard title="Match Rate" value={`${stats?.match_rate}%`} color="text-green-600" />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <AlertCard
          title="Pending Reviews"
          value={stats?.pending_review}
          description="Matches awaiting manual approval"
          href="/reviews"
          severity={stats?.pending_review > 0 ? "warning" : "ok"}
        />
        <AlertCard
          title="Dead Webhooks"
          value={stats?.dead_webhooks}
          description="Webhook deliveries that exhausted all retries"
          href="/webhook-logs"
          severity={stats?.dead_webhooks > 0 ? "error" : "ok"}
        />
        <AlertCard
          title="SMS Processed"
          value={stats?.total_sms}
          description={`${stats?.matched_sms} matched successfully`}
          severity="info"
        />
      </div>
    </div>
  );
}

function StatCard({ title, value, label, color = "" }: { title: string; value: any; label?: string; color?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-sm text-muted-foreground">{title}</p>
        <p className={`text-3xl font-bold mt-1 ${color}`}>{value ?? "—"}</p>
        {label && <p className="text-xs text-muted-foreground mt-1">{label}</p>}
      </CardContent>
    </Card>
  );
}

function AlertCard({ title, value, description, href, severity }: {
  title: string; value: any; description: string; href?: string; severity: "ok" | "warning" | "error" | "info";
}) {
  const colors = {
    ok: "border-green-200 bg-green-50",
    warning: "border-yellow-200 bg-yellow-50",
    error: "border-red-200 bg-red-50",
    info: "border-blue-200 bg-blue-50",
  };
  const textColors = {
    ok: "text-green-700", warning: "text-yellow-700", error: "text-red-700", info: "text-blue-700",
  };
  return (
    <Card className={`border-2 ${colors[severity]}`}>
      <CardHeader className="pb-2">
        <CardTitle className={`text-sm font-medium ${textColors[severity]}`}>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-3xl font-bold ${textColors[severity]}`}>{value ?? 0}</p>
        <p className="text-xs text-muted-foreground mt-1">{description}</p>
        {href && value > 0 && (
          <a href={href} className={`text-xs font-medium underline mt-2 inline-block ${textColors[severity]}`}>
            Review →
          </a>
        )}
      </CardContent>
    </Card>
  );
}
