import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import { getAutomationUser, isAutomationBypassEnabled } from "@/lib/authAutomation";
import { buildSiweMessage, connectBrowserWallet, readConnectedWallet, signSiweMessage } from "@/lib/wallet";

type SessionUser = {
  walletAddress: string;
  displayName: string;
};

type AuthContextValue = {
  walletAddress: string | null;
  user: SessionUser | null;
  isAuthenticated: boolean;
  loading: boolean;
  connectWallet: () => Promise<void>;
  signIn: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authenticating, setAuthenticating] = useState(false);

  useEffect(() => {
    const automationBypass = isAutomationBypassEnabled();
    const automationUser = getAutomationUser();

    readConnectedWallet()
      .then((address) => setWalletAddress(address ?? (automationBypass ? automationUser.walletAddress : null)))
      .finally(async () => {
        if (automationBypass) {
          try {
            const response = await apiRequest<{ user: SessionUser }>("/api/auth/test-login", {
              method: "POST",
              body: JSON.stringify(automationUser),
            });
            setUser(response.user);
            setWalletAddress(response.user.walletAddress);
          } catch {
            setUser(null);
          } finally {
            setLoading(false);
          }
          return;
        }

        try {
          const response = await apiRequest<{ user: SessionUser }>("/api/auth/me");
          setUser(response.user);
          setWalletAddress((current) => current ?? response.user.walletAddress);
        } catch {
          setUser(null);
        } finally {
          setLoading(false);
        }
      });
  }, []);

  async function connectWallet() {
    if (isAutomationBypassEnabled()) {
      const automationUser = getAutomationUser();
      setWalletAddress(automationUser.walletAddress);
      return;
    }
    const address = await connectBrowserWallet();
    setWalletAddress(address);
  }

  async function signIn() {
    if (isAutomationBypassEnabled()) {
      const automationUser = getAutomationUser();
      const session = await apiRequest<{ user: SessionUser }>("/api/auth/test-login", {
        method: "POST",
        body: JSON.stringify(automationUser),
      });
      setWalletAddress(session.user.walletAddress);
      setUser(session.user);
      return;
    }
    if (!walletAddress) {
      throw new Error("Connect a wallet before signing in.");
    }
    if (authenticating) {
      return;
    }
    setAuthenticating(true);
    try {
      const noncePayload = await apiRequest<{
        nonce: string;
        issuedAt: string;
        domain: string;
        uri: string;
        chainId: number;
      }>("/api/auth/siwe/nonce", {
        method: "POST",
        body: JSON.stringify({ walletAddress }),
      });
      const message = buildSiweMessage({ walletAddress, ...noncePayload });
      const signature = await signSiweMessage(message);
      const session = await apiRequest<{ user: SessionUser }>("/api/auth/siwe/verify", {
        method: "POST",
        body: JSON.stringify({ message, signature }),
      });
      setUser(session.user);
    } finally {
      setAuthenticating(false);
    }
  }

  async function logout() {
    await apiRequest("/api/auth/logout", { method: "POST" });
    setUser(null);
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      walletAddress,
      user,
      isAuthenticated: Boolean(user),
      loading: loading || authenticating,
      connectWallet,
      signIn,
      logout,
    }),
    [authenticating, loading, user, walletAddress],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
