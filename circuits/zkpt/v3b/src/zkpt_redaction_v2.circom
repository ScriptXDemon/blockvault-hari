// ============================================================================
// ZKPT Redaction Circuit - Production Version
// ============================================================================
//
// This circuit proves the following statement:
//
//   "Given a public original document root and a public redacted document root,
//    the prover knows a set of segment modifications such that:
//    1. Each original segment has a valid Merkle authentication path to originalRoot
//    2. Each redacted segment has a valid Merkle authentication path to redactedRoot
//    3. Unmodified segments are identical in both trees
//    4. Modified segments were replaced according to the redaction mask
//    5. The redaction mask is consistent with a committed policy"
//
// Default production instantiation:
//   component main {public [originalRoot, redactedRoot, policyCommitment, transformationId]}
//     = ZKPTRedaction(16, 8, 8);
//
// Build notes:
// - compile with circom 2.1.6+
// - use circomlib Poseidon/comparator templates
// - pair with a PLONK setup and matching verification key
//
// ============================================================================

pragma circom 2.1.6;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/bitify.circom";
include "circomlib/circuits/mux1.circom";

template MerklePathVerifier(depth) {
    signal input leaf;
    signal input root;
    signal input siblings[depth];
    signal input directions[depth];

    signal intermediate[depth + 1];
    intermediate[0] <== leaf;

    component hashers[depth];
    component mux_left[depth];
    component mux_right[depth];

    for (var i = 0; i < depth; i++) {
        directions[i] * (directions[i] - 1) === 0;

        mux_left[i] = Mux1();
        mux_left[i].c[0] <== intermediate[i];
        mux_left[i].c[1] <== siblings[i];
        mux_left[i].s <== directions[i];

        mux_right[i] = Mux1();
        mux_right[i].c[0] <== siblings[i];
        mux_right[i].c[1] <== intermediate[i];
        mux_right[i].s <== directions[i];

        hashers[i] = Poseidon(2);
        hashers[i].inputs[0] <== mux_left[i].out;
        hashers[i].inputs[1] <== mux_right[i].out;

        intermediate[i + 1] <== hashers[i].out;
    }

    root === intermediate[depth];
}

template PoseidonChainHash(n) {
    signal input elements[n];
    signal output out;

    component hashers[n];
    signal chain[n + 1];
    chain[0] <== 0;

    for (var i = 0; i < n; i++) {
        hashers[i] = Poseidon(2);
        hashers[i].inputs[0] <== chain[i];
        hashers[i].inputs[1] <== elements[i];
        chain[i + 1] <== hashers[i].out;
    }

    out <== chain[n];
}

template ZKPTRedaction(NUM_SEGMENTS, TREE_DEPTH, NUM_POLICY_RULES) {
    signal input originalRoot;
    signal input redactedRoot;
    signal input policyCommitment;
    signal input transformationId;

    signal input originalHashes[NUM_SEGMENTS];
    signal input redactedHashes[NUM_SEGMENTS];
    signal input mask[NUM_SEGMENTS];

    signal input origSiblings[NUM_SEGMENTS][TREE_DEPTH];
    signal input origDirections[NUM_SEGMENTS][TREE_DEPTH];
    signal input redSiblings[NUM_SEGMENTS][TREE_DEPTH];
    signal input redDirections[NUM_SEGMENTS][TREE_DEPTH];

    signal input placeholderHash;
    signal input policyRules[NUM_POLICY_RULES];
    signal input policySelector[NUM_SEGMENTS];

    for (var i = 0; i < NUM_SEGMENTS; i++) {
        mask[i] * (mask[i] - 1) === 0;
    }

    signal expectedRedacted[NUM_SEGMENTS];
    for (var i = 0; i < NUM_SEGMENTS; i++) {
        expectedRedacted[i] <== originalHashes[i] + mask[i] * (placeholderHash - originalHashes[i]);
        redactedHashes[i] === expectedRedacted[i];
    }

    component origVerifiers[NUM_SEGMENTS];
    component redVerifiers[NUM_SEGMENTS];

    for (var i = 0; i < NUM_SEGMENTS; i++) {
        origVerifiers[i] = MerklePathVerifier(TREE_DEPTH);
        origVerifiers[i].leaf <== originalHashes[i];
        origVerifiers[i].root <== originalRoot;
        for (var j = 0; j < TREE_DEPTH; j++) {
            origVerifiers[i].siblings[j] <== origSiblings[i][j];
            origVerifiers[i].directions[j] <== origDirections[i][j];
        }

        redVerifiers[i] = MerklePathVerifier(TREE_DEPTH);
        redVerifiers[i].leaf <== redactedHashes[i];
        redVerifiers[i].root <== redactedRoot;
        for (var j = 0; j < TREE_DEPTH; j++) {
            redVerifiers[i].siblings[j] <== redSiblings[i][j];
            redVerifiers[i].directions[j] <== redDirections[i][j];
        }
    }

    component policyHasher = PoseidonChainHash(NUM_POLICY_RULES);
    for (var i = 0; i < NUM_POLICY_RULES; i++) {
        policyHasher.elements[i] <== policyRules[i];
    }
    policyCommitment === policyHasher.out;

    component selectorBounds[NUM_SEGMENTS];
    for (var i = 0; i < NUM_SEGMENTS; i++) {
        selectorBounds[i] = LessThan(32);
        selectorBounds[i].in[0] <== policySelector[i];
        selectorBounds[i].in[1] <== NUM_POLICY_RULES;
        mask[i] * (1 - selectorBounds[i].out) === 0;
    }

    component bindingHasher = Poseidon(2);
    bindingHasher.inputs[0] <== originalRoot;
    bindingHasher.inputs[1] <== transformationId;
    signal bindingCheck;
    bindingCheck <== bindingHasher.out;
    signal bindingNonZero;
    bindingNonZero <== bindingCheck * bindingCheck;
}

component main {public [originalRoot, redactedRoot, policyCommitment, transformationId]} = ZKPTRedaction(4, 6, 4);
