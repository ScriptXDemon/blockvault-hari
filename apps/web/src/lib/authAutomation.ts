const DEFAULT_AUTOMATION_WALLET = "0x1111111111111111111111111111111111111111";
const DEFAULT_AUTOMATION_DISPLAY_NAME = "Automation Tester";

export function isAutomationBypassEnabled() {
  return import.meta.env.VITE_AUTOMATION_BYPASS_AUTH === "true";
}

export function getAutomationUser() {
  return {
    walletAddress: import.meta.env.VITE_AUTOMATION_WALLET_ADDRESS ?? DEFAULT_AUTOMATION_WALLET,
    displayName: import.meta.env.VITE_AUTOMATION_DISPLAY_NAME ?? DEFAULT_AUTOMATION_DISPLAY_NAME,
  };
}
