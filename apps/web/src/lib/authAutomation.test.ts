import { getAutomationUser, isAutomationBypassEnabled } from "./authAutomation";

describe("auth automation helpers", () => {
  it("defaults to bypass disabled with stable fallback credentials", () => {
    expect(isAutomationBypassEnabled()).toBe(false);
    expect(getAutomationUser()).toEqual({
      walletAddress: "0x1111111111111111111111111111111111111111",
      displayName: "Automation Tester",
    });
  });
});
