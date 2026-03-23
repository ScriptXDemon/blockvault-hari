import { render, screen } from "@testing-library/react";

import { LandingPage } from "./LandingPage";

vi.mock("@/state/AuthContext", () => ({
  useAuth: () => ({
    walletAddress: null,
    isAuthenticated: false,
    connectWallet: vi.fn(),
    signIn: vi.fn(),
    loading: false,
  }),
}));

describe("LandingPage", () => {
  it("renders the new v1 value proposition", () => {
    render(<LandingPage />);
    expect(screen.getByText(/legal evidence infrastructure/i)).toBeInTheDocument();
    expect(screen.getByText(/tamper-evident legal documents/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Connect MetaMask/i).length).toBeGreaterThan(0);
  });
});
