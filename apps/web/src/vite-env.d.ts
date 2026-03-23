/// <reference types="vite/client" />

declare const __BLOCKVAULT_BUILD_ID__: string;
declare const __BLOCKVAULT_BUILD_AT__: string;
declare const __BLOCKVAULT_BUILD_GIT_SHA__: string;
declare const __BLOCKVAULT_BUILD_SOURCE_HASH__: string;

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTOMATION_BYPASS_AUTH?: string;
  readonly VITE_AUTOMATION_WALLET_ADDRESS?: string;
  readonly VITE_AUTOMATION_DISPLAY_NAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
