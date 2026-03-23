import { Navigate } from "react-router-dom";

import { Button } from "@blockvault/ui";

import { isAutomationBypassEnabled } from "@/lib/authAutomation";
import { useAuth } from "@/state/AuthContext";
import styles from "./LandingPage.module.css";

function ShieldCheckIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <polyline points="9 12 11 14 15 10"/>
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
      <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
    </svg>
  );
}

function LayersIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 2 7 12 12 22 7 12 2"/>
      <polyline points="2 17 12 22 22 17"/>
      <polyline points="2 12 12 17 22 12"/>
    </svg>
  );
}

function FileTextIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  );
}

function ExportIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="17 8 12 3 7 8"/>
      <line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
  );
}

function WalletIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 12V8H6a2 2 0 0 1-2-2c0-1.1.9-2 2-2h12v4"/>
      <path d="M4 6v12c0 1.1.9 2 2 2h14v-4"/>
      <circle cx="18" cy="12" r="2"/>
    </svg>
  );
}

const FEATURES = [
  {
    icon: <LockIcon />,
    title: "Encrypted Vault",
    description: "AES-256-GCM client-side encryption before upload. Your passphrase never leaves your device.",
  },
  {
    icon: <FileTextIcon />,
    title: "Case-Based Documents",
    description: "Organize legal documents by case. Notarize originals on-chain for a tamper-evident timestamp.",
  },
  {
    icon: <ShieldCheckIcon />,
    title: "ZKPT Redaction",
    description: "Zero-knowledge proof of transformation. Redact sensitive terms without destroying evidential integrity.",
  },
  {
    icon: <ExportIcon />,
    title: "Evidence Export",
    description: "Export bundles with anchor receipts, hash manifests, and chain-of-custody timelines for court submission.",
  },
];

const STEPS = [
  { label: "Upload", detail: "Encrypt and store legal PDFs with AES-256-GCM" },
  { label: "Notarize", detail: "Anchor SHA-256 hashes to a blockchain receipt" },
  { label: "Redact", detail: "Generate zero-knowledge proofs of redaction" },
  { label: "Export", detail: "Package evidence bundles for downstream review" },
];

export function LandingPage() {
  const { walletAddress, isAuthenticated, connectWallet, signIn, loading } = useAuth();
  const automationBypass = isAutomationBypassEnabled();

  if (isAuthenticated) {
    return <Navigate to="/app/vault" replace />;
  }

  if (automationBypass && loading) {
    return <div className="screen-center">Preparing automation session...</div>;
  }

  return (
    <div className={styles.page}>
      {/* Nav */}
      <nav className={styles.nav}>
        <div className={styles.navBrand}>
          <ShieldCheckIcon />
          <span>BlockVault</span>
        </div>
        <div className={styles.navActions}>
          {!walletAddress ? (
            <Button size="sm" onClick={() => void connectWallet()}>Connect wallet</Button>
          ) : (
            <Button size="sm" disabled={loading} onClick={() => void signIn()}>
              Sign in with wallet
            </Button>
          )}
        </div>
      </nav>

      {/* Hero */}
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div className={styles.heroEyebrow}>Legal evidence infrastructure</div>
          <h1 className={styles.heroTitle}>
            Tamper-evident legal documents.<br />
            Zero-knowledge redaction.
          </h1>
          <p className={styles.heroSub}>
            BlockVault combines encrypted storage, on-chain notarization, and authoritative redaction proofs
            into a single, verifiable legal workflow — from upload to evidence export.
          </p>

          <div className={styles.heroCta}>
            {!walletAddress ? (
              <Button onClick={() => void connectWallet()}>
                <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <WalletIcon />
                  Connect MetaMask
                </span>
              </Button>
            ) : (
              <Button disabled={loading} onClick={() => void signIn()}>
                {loading ? "Signing in..." : "Sign in with Ethereum"}
              </Button>
            )}
            {walletAddress && (
              <p className={styles.walletChip}>
                <span className={styles.walletDot} />
                {walletAddress.slice(0, 6)}...{walletAddress.slice(-4)}
              </p>
            )}
          </div>

          <div className={styles.trustBadges}>
            <span className={styles.trustBadge}>AES-256-GCM</span>
            <span className={styles.trustBadge}>ZKPT Verified</span>
            <span className={styles.trustBadge}>Ethereum Anchored</span>
            <span className={styles.trustBadge}>SIWE Auth</span>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className={styles.section}>
        <div className={styles.sectionInner}>
          <div className={styles.sectionLabel}>How it works</div>
          <h2 className={styles.sectionTitle}>Four steps from upload to evidence</h2>
          <div className={styles.steps}>
            {STEPS.map((step, i) => (
              <div key={step.label} className={styles.step}>
                <div className={styles.stepNum}>{i + 1}</div>
                <div>
                  <div className={styles.stepLabel}>{step.label}</div>
                  <div className={styles.stepDetail}>{step.detail}</div>
                </div>
                {i < STEPS.length - 1 && <div className={styles.stepConnector} />}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className={styles.section} style={{ background: "var(--bv-surface-strong)" }}>
        <div className={styles.sectionInner}>
          <div className={styles.sectionLabel}>Platform features</div>
          <h2 className={styles.sectionTitle}>Built for legal professionals</h2>
          <div className={styles.features}>
            {FEATURES.map((f) => (
              <div key={f.title} className={styles.featureCard}>
                <div className={styles.featureIcon}>{f.icon}</div>
                <h3 className={styles.featureTitle}>{f.title}</h3>
                <p className={styles.featureDesc}>{f.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer CTA */}
      <section className={styles.footerCta}>
        <div className={styles.sectionInner}>
          <h2 className={styles.sectionTitle} style={{ color: "var(--bv-surface)" }}>Ready to begin?</h2>
          <p style={{ color: "color-mix(in srgb, var(--bv-surface) 70%, transparent)", marginBottom: "32px", maxWidth: "480px", margin: "0 auto 32px" }}>
            Connect your Ethereum wallet to access the encrypted vault and begin the notarization workflow.
          </p>
          {!walletAddress ? (
            <Button onClick={() => void connectWallet()}>Connect MetaMask</Button>
          ) : (
            <Button disabled={loading} onClick={() => void signIn()}>
              {loading ? "Signing in..." : "Enter BlockVault"}
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}
