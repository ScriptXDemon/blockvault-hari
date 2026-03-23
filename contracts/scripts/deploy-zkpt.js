const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const profileId = process.env.BLOCKVAULT_ZKPT_PROFILE || "v4_sparse";
  const generatedDir = path.join(__dirname, "..", "zkpt", "generated", profileId);
  const metadataPath = path.join(generatedDir, "verifier-export.json");
  if (!fs.existsSync(metadataPath)) {
    throw new Error(
      `Verifier metadata not found for profile '${profileId}'. Run 'python scripts/zkpt/export_verifier.py --profile ${profileId}' first.`
    );
  }

  const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
  const verifierContractName = metadata.contractName;
  if (!verifierContractName) {
    throw new Error(`Missing contractName in ${metadataPath}`);
  }
  const verifierSourcePath = metadata.verifierSourcePath;
  if (!verifierSourcePath) {
    throw new Error(`Missing verifierSourcePath in ${metadataPath}`);
  }
  const relativeSourcePath = path.relative(path.join(__dirname, ".."), verifierSourcePath).replace(/\\/g, "/");
  const verifierFqn = `${relativeSourcePath}:${verifierContractName}`;

  const [deployer] = await ethers.getSigners();
  const verifierFactory = await ethers.getContractFactory(verifierFqn);
  const verifier = await verifierFactory.deploy();
  await verifier.waitForDeployment();

  const registryFactory = await ethers.getContractFactory("ZKPTReceiptRegistry");
  const registry = await registryFactory.deploy(await verifier.getAddress());
  await registry.waitForDeployment();

  const output = {
    profileId,
    artifactVersion: metadata.artifactVersion,
    proofBoundary: metadata.proofBoundary,
    verifierSourcePath: relativeSourcePath,
    chainId: Number((await ethers.provider.getNetwork()).chainId),
    verifierContractName,
    verifierAddress: await verifier.getAddress(),
    registryAddress: await registry.getAddress(),
    deployer: deployer.address,
    deployedAt: new Date().toISOString(),
  };

  const deploymentsDir = path.join(__dirname, "..", "zkpt", "deployments");
  fs.mkdirSync(deploymentsDir, { recursive: true });
  const outputPath = path.join(
    deploymentsDir,
    `${hre.network.name}-${profileId}.json`,
  );
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2) + "\n", "utf8");
  console.log(JSON.stringify(output, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
