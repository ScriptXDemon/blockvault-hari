#!/usr/bin/env node
const fs = require("fs");
const circomlibjs = require("circomlibjs");

function toBigIntArray(values) {
  return values.map((value) => BigInt(value));
}

(async () => {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const poseidon = await circomlibjs.buildPoseidon();
  const F = poseidon.F;

  const treeDepth = Number(input.treeDepth);
  const targetLeafCount = 1 << treeDepth;

  function poseidon2(left, right) {
    return BigInt(F.toString(poseidon([BigInt(left), BigInt(right)])));
  }

  function buildTree(leaves) {
    const padded = toBigIntArray(leaves);
    while (padded.length < targetLeafCount) {
      padded.push(0n);
    }
    const levels = [padded];
    let current = padded;
    while (current.length > 1) {
      const next = [];
      for (let i = 0; i < current.length; i += 2) {
        next.push(poseidon2(current[i], current[i + 1]));
      }
      levels.push(next);
      current = next;
    }
    return { root: current[0], levels };
  }

  function authPath(levels, leafIndex) {
    const siblings = [];
    const directions = [];
    let index = leafIndex;
    for (let level = 0; level < treeDepth; level += 1) {
      const nodes = levels[level];
      const siblingIndex = index ^ 1;
      siblings.push(nodes[siblingIndex]);
      directions.push(index % 2);
      index = Math.floor(index / 2);
    }
    return {
      siblings: siblings.map((item) => item.toString()),
      directions: directions.map((item) => item.toString()),
    };
  }

  const originalTree = buildTree(input.originalLeafHashes);
  const redactedTree = buildTree(input.redactedLeafHashes);
  const selectedIndices = input.selectedIndices.map((item) => Number(item));
  const policyRules = toBigIntArray(input.policyRules || []);
  let chain = 0n;
  for (const rule of policyRules) {
    chain = poseidon2(chain, rule);
  }

  const response = {
    originalRoot: originalTree.root.toString(),
    redactedRoot: redactedTree.root.toString(),
    policyCommitment: chain.toString(),
    originalPaths: selectedIndices.map((index) => authPath(originalTree.levels, index)),
    redactedPaths: selectedIndices.map((index) => authPath(redactedTree.levels, index)),
  };

  process.stdout.write(JSON.stringify(response));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
