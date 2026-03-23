import { lazy, Suspense } from "react";
import type { ReactElement } from "react";
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { isAutomationBypassEnabled } from "@/lib/authAutomation";
import { useAuth } from "@/state/AuthContext";

const LandingPage = lazy(() => import("@/pages/LandingPage").then((module) => ({ default: module.LandingPage })));
const VaultPage = lazy(() => import("@/pages/VaultPage").then((module) => ({ default: module.VaultPage })));
const CasesPage = lazy(() => import("@/pages/CasesPage").then((module) => ({ default: module.CasesPage })));
const DocumentsPage = lazy(() => import("@/pages/DocumentsPage").then((module) => ({ default: module.DocumentsPage })));
const CaseDetailPage = lazy(() => import("@/pages/CaseDetailPage").then((module) => ({ default: module.CaseDetailPage })));
const DocumentDetailPage = lazy(() =>
  import("@/pages/DocumentDetailPage").then((module) => ({ default: module.DocumentDetailPage })),
);
const EvidencePage = lazy(() => import("@/pages/EvidencePage").then((module) => ({ default: module.EvidencePage })));

function renderLazy(element: ReactElement) {
  return <Suspense fallback={<div className="screen-center">Loading...</div>}>{element}</Suspense>;
}

function ProtectedLayout() {
  const { isAuthenticated, loading } = useAuth();
  if (loading) {
    return <div className="screen-center">Restoring session...</div>;
  }
  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

function RootEntry() {
  const { isAuthenticated, loading } = useAuth();

  if (isAutomationBypassEnabled()) {
    if (loading) {
      return <div className="screen-center">Preparing automation session...</div>;
    }
    if (isAuthenticated) {
      return <Navigate to="/app/vault" replace />;
    }
  }

  return renderLazy(<LandingPage />);
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootEntry />,
  },
  {
    path: "/app",
    element: <ProtectedLayout />,
    children: [
      { index: true, element: <Navigate to="/app/vault" replace /> },
      { path: "vault", element: renderLazy(<VaultPage />) },
      { path: "cases", element: renderLazy(<CasesPage />) },
      { path: "documents", element: renderLazy(<DocumentsPage />) },
      { path: "cases/:caseId", element: renderLazy(<CaseDetailPage />) },
      { path: "documents/:documentId", element: renderLazy(<DocumentDetailPage />) },
      { path: "evidence/:bundleId", element: renderLazy(<EvidencePage />) },
    ],
  },
]);
