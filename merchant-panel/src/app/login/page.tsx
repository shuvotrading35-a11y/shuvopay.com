"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000/api/v1";

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleLogin(e: FormEvent) {
    e.preventDefault();

    setLoading(true);
    setError("");

    try {
      // 1. Login
      const loginResponse = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          email,
          password,
          totp_code: totpCode || null,
        }),
      });

      const loginData = await loginResponse.json();

      if (!loginResponse.ok) {
        throw new Error(
          loginData.detail || "Invalid email or password"
        );
      }

      // 2. Save access token
      localStorage.setItem(
        "access_token",
        loginData.access_token
      );

      // 3. Get merchant information
      const merchantResponse = await fetch(
        `${API_URL}/merchant/dashboard`,
        {
          headers: {
            Authorization: `Bearer ${loginData.access_token}`,
          },
        }
      );

      const merchantData = await merchantResponse.json();

      if (!merchantResponse.ok) {
        throw new Error(
          merchantData.detail || "Merchant profile not found"
        );
      }

      // 4. Save merchant ID for WebSocket
      localStorage.setItem(
        "merchant_id",
        merchantData.merchant_id
      );

      // 5. Go to dashboard
      router.replace("/dashboard");
    } catch (err: any) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("merchant_id");

      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold">
            ShuvoPay
          </h1>

          <p className="mt-2 text-muted-foreground">
            Merchant Panel
          </p>
        </div>

        <div className="rounded-xl border bg-card p-6 shadow-sm">
          <h2 className="text-xl font-semibold">
            Sign in
          </h2>

          <p className="mt-1 text-sm text-muted-foreground">
            Sign in to your merchant account
          </p>

          {error && (
            <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <form
            onSubmit={handleLogin}
            className="mt-6 space-y-4"
          >
            <div>
              <label className="mb-1 block text-sm font-medium">
                Email
              </label>

              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                className="w-full rounded-lg border bg-background px-3 py-2 outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Password
              </label>

              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                className="w-full rounded-lg border bg-background px-3 py-2 outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                2FA Code
                <span className="ml-1 text-muted-foreground">
                  (optional)
                </span>
              </label>

              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(e) =>
                  setTotpCode(
                    e.target.value.replace(/\D/g, "")
                  )
                }
                placeholder="123456"
                className="w-full rounded-lg border bg-background px-3 py-2 outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-primary px-4 py-2.5 font-medium text-primary-foreground disabled:opacity-50"
            >
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    </main>
  );
    }
