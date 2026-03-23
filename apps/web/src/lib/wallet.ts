import { BrowserProvider } from "ethers";

type EthereumProvider = {
  request(args: { method: string; params?: unknown[] | object }): Promise<unknown>;
};

export interface WalletSessionRequest {
  walletAddress: string;
  nonce: string;
  domain: string;
  uri: string;
  chainId: number;
  issuedAt: string;
}

export async function connectBrowserWallet(): Promise<string> {
  const ethereum = (window as Window & { ethereum?: EthereumProvider }).ethereum;
  if (!ethereum) {
    throw new Error("MetaMask or a compatible wallet is required.");
  }

  const provider = new BrowserProvider(ethereum);
  const accounts = await provider.send("eth_requestAccounts", []);
  return accounts[0];
}

export async function readConnectedWallet(): Promise<string | null> {
  const ethereum = (window as Window & { ethereum?: EthereumProvider }).ethereum;
  if (!ethereum) {
    return null;
  }
  const provider = new BrowserProvider(ethereum);
  const accounts = await provider.send("eth_accounts", []);
  return accounts[0] ?? null;
}

export function buildSiweMessage(payload: WalletSessionRequest): string {
  return `${payload.domain} wants you to sign in with your Ethereum account:
${payload.walletAddress}

Sign in to BlockVault.

URI: ${payload.uri}
Version: 1
Chain ID: ${payload.chainId}
Nonce: ${payload.nonce}
Issued At: ${payload.issuedAt}`;
}

export async function signSiweMessage(message: string): Promise<string> {
  const ethereum = (window as Window & { ethereum?: EthereumProvider }).ethereum;
  if (!ethereum) {
    throw new Error("Wallet provider unavailable.");
  }
  const provider = new BrowserProvider(ethereum);
  const signer = await provider.getSigner();
  return signer.signMessage(message);
}
