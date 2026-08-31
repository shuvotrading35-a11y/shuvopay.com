"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import { api } from "@/lib/api/client";
import { useWebSocket } from "@/lib/hooks/useWebSocket";

const COLORS = ["#22c55e", "#f59e0b", "#ef4444", "#3b82f6"];

export default function DashboardPage() {
  const [stats, setStats] = useState<any>(null);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [liveEvents, setLiveEvents] = useState<any[]>([]);

  const onWsMessage = useCallback((data: any) => {
    if (data.event === "payment.confirmed") {
      setLiveEvents((prev) => [data, ...prev].slice(0, 10));
      loadDashboard();
    }
  }, []);

  const { connected } = useWebSocket(onWsMessage);

  const loadDashboard = useCallback(async () => {
    try {
      const [statsData, txData] = await Promise.all([
        api.get("/merchant/dashboard") as Promise<any>,
        api.get("/merchant/transactions?page=1&page_size=5") as Promise<any>,
      ]);
      setStats(statsData);
      setTransactions(txData?.items ?? []);
    } catch (e) {
      console.error("Dashboard load error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  const chartData = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    return {
      date: d.toLocaleDateString("en-US", { weekday: "short" }),
      paid: Math.floor(Math.random() * 20 + 5),
      pending: Math.floor(Math.random() * 5),
    };
  });

  const pieData = [
    { name: "bKash", value: 45 },
    { name: "Nagad", value: 30 },
    { name: "Rocket", value: 15 },
    { name: "Upay", value: 10 },
  ];

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground text-sm">Real-time payment overview</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-green-500" : "bg-yellow-500"}`} />
          <span className="text-sm text-muted-foreground">{connected ? "Live" : "Connecting..."}</span>
          <Button size="sm" onClick={loadDashboard}>Refresh</Button>
        </div>
      </div>

      {/* Live event feed */}
      {liveEvents.length > 0 && (
        <Card className="border-green-500/50 bg-green-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-green-600">🔴 Live Updates</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {liveEvents.slice(0, 3).map((evt, i) => (
              <div key={i} className="text-sm">
                <span className="font-medium text-green-700">Payment confirmed</span>
                {" · "}{evt.provider} · BDT {evt.amount} · {evt.transaction_id}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Stats cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <StatCard title="Total Invoices" value={stats?.total_invoices ?? 0} />
        <StatCard title="Paid" value={stats?.paid_invoices ?? 0} color="text-green-600" />
        <StatCard title="Pending" value={stats?.pending_invoices ?? 0} color="text-yellow-600" />
        <StatCard title="SMS Received" value={stats?.total_sms_received ?? 0} />
      </div>

      {/* Charts */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Payment Volume (7 days)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Area type="monotone" dataKey="paid" stroke="#22c55e" fill="#22c55e33" name="Paid" />
                <Area type="monotone" dataKey="pending" stroke="#f59e0b" fill="#f59e0b33" name="Pending" />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Provider Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center">
            <PieChart width={160} height={160}>
              <Pie data={pieData} cx={75} cy={75} innerRadius={40} outerRadius={70} dataKey="value">
                {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
            </PieChart>
            <div className="mt-2 grid grid-cols-2 gap-1 text-xs">
              {pieData.map((p, i) => (
                <div key={p.name} className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full" style={{ background: COLORS[i] }} />
                  <span>{p.name} {p.value}%</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent transactions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Transactions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="divide-y">
            {transactions.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium">{tx.invoice_number}</p>
                  <p className="text-xs text-muted-foreground">{tx.provider} · {new Date(tx.created_at).toLocaleString()}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold">BDT {tx.amount.toLocaleString()}</span>
                  <StatusBadge status={tx.status} />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({ title, value, color = "" }: { title: string; value: number; color?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-sm text-muted-foreground">{title}</p>
        <p className={`text-3xl font-bold mt-1 ${color}`}>{value.toLocaleString()}</p>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, string> = {
    paid: "bg-green-100 text-green-700",
    pending: "bg-yellow-100 text-yellow-700",
    review_required: "bg-orange-100 text-orange-700",
    unmatched: "bg-gray-100 text-gray-700",
    cancelled: "bg-red-100 text-red-700",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${variants[status] ?? "bg-gray-100"}`}>
      {status.replace("_", " ")}
    </span>
  );
}
