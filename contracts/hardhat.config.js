require("dotenv").config();
require("@nomicfoundation/hardhat-ethers");

const rpcUrl = process.env.BLOCKVAULT_ZKPT_ONCHAIN_RPC_URL || "";
const relayerKey = process.env.BLOCKVAULT_ZKPT_ONCHAIN_RELAYER_PRIVATE_KEY || "";
const viaIr = String(process.env.BLOCKVAULT_HARDHAT_VIA_IR || "false").toLowerCase() === "true";
const solcVersion = process.env.BLOCKVAULT_HARDHAT_SOLC_VERSION || "0.8.20";

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: solcVersion,
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
      // Generated snarkjs verifiers are more stable for local/on-chain proof checks without viaIR.
      viaIR: viaIr,
    },
  },
  paths: {
    sources: "./zkpt",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  networks: {
    blockvaultTestnet: {
      url: rpcUrl || "http://127.0.0.1:8545",
      chainId: Number(process.env.BLOCKVAULT_ZKPT_ONCHAIN_CHAIN_ID || 11155111),
      accounts: relayerKey ? [relayerKey] : [],
    },
  },
};
