// ============================================================================
// ZKPT Sparse Redaction Circuit - v4 Design Source
// ============================================================================
//
// This circuit is the planned sparse-update successor to the current full-window
// redaction circuit. It preserves the same proof boundary,
// `canonical_segment_mask_v1`, but proves only the modified canonical segments
// plus their Merkle update paths.
//
// Intended public inputs:
//   - originalRoot
//   - redactedRoot
//   - policyCommitment
//   - documentBindingCommitment
//
// Intended witness shape:
//   - modifiedIndices[]
//   - updateMask[]
//   - originalLeafHashes[]
//   - redactedLeafHashes[]
//   - originalSiblings[][] / originalDirections[][]
//   - redactedSiblings[][] / redactedDirections[][]
//   - policyRules[]
//   - policySelector[]
//   - placeholderHash
//
// The current repo does not yet ship compiled artifacts for this circuit. This
// source exists so the runtime and build pipeline can reason about the sparse
// proof model explicitly before the full witness/prover integration lands.
// ============================================================================

pragma circom 2.1.6;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/mux1.circom";

template MerklePathVerifier(depth) {
    signal input leaf;
    signal input root;
    signal input siblings[depth];
    signal input directions[depth];

    signal intermediate[depth + 1];
    intermediate[0] <== leaf;

    component hashers[depth];
    component muxLeft[depth];
    component muxRight[depth];

    for (var i = 0; i < depth; i++) {
        directions[i] * (directions[i] - 1) === 0;

        muxLeft[i] = Mux1();
        muxLeft[i].c[0] <== intermediate[i];
        muxLeft[i].c[1] <== siblings[i];
        muxLeft[i].s <== directions[i];

        muxRight[i] = Mux1();
        muxRight[i].c[0] <== siblings[i];
        muxRight[i].c[1] <== intermediate[i];
        muxRight[i].s <== directions[i];

        hashers[i] = Poseidon(2);
        hashers[i].inputs[0] <== muxLeft[i].out;
        hashers[i].inputs[1] <== muxRight[i].out;
        intermediate[i + 1] <== hashers[i].out;
    }

    root === intermediate[depth];
}

template DistinctIndices(count) {
    signal input indices[count];
    component neq[count][count];

    for (var i = 0; i < count; i++) {
        for (var j = i + 1; j < count; j++) {
            neq[i][j] = IsEqual();
            neq[i][j].in[0] <== indices[i];
            neq[i][j].in[1] <== indices[j];
            neq[i][j].out === 0;
        }
    }
}

template ZKPTRedactionSparse(NUM_UPDATES, TREE_DEPTH, NUM_POLICY_RULES) {
    signal input originalRoot;
    signal input redactedRoot;
    signal input policyCommitment;
    signal input documentBindingCommitment;

    signal input modifiedIndices[NUM_UPDATES];
    signal input updateMask[NUM_UPDATES];
    signal input originalLeafHashes[NUM_UPDATES];
    signal input redactedLeafHashes[NUM_UPDATES];
    signal input placeholderHash;
    signal input policyRules[NUM_POLICY_RULES];
    signal input policySelector[NUM_UPDATES];

    signal input origSiblings[NUM_UPDATES][TREE_DEPTH];
    signal input origDirections[NUM_UPDATES][TREE_DEPTH];
    signal input redSiblings[NUM_UPDATES][TREE_DEPTH];
    signal input redDirections[NUM_UPDATES][TREE_DEPTH];

    component unique = DistinctIndices(NUM_UPDATES);
    component origPath[NUM_UPDATES];
    component redPath[NUM_UPDATES];
    component selectorBounds[NUM_UPDATES];

    for (var i = 0; i < NUM_UPDATES; i++) {
        unique.indices[i] <== modifiedIndices[i];
        updateMask[i] * (updateMask[i] - 1) === 0;

        origPath[i] = MerklePathVerifier(TREE_DEPTH);
        origPath[i].leaf <== originalLeafHashes[i];
        origPath[i].root <== originalRoot;
        redPath[i] = MerklePathVerifier(TREE_DEPTH);
        redPath[i].leaf <== redactedLeafHashes[i];
        redPath[i].root <== redactedRoot;

        for (var j = 0; j < TREE_DEPTH; j++) {
            origPath[i].siblings[j] <== origSiblings[i][j];
            origPath[i].directions[j] <== origDirections[i][j];
            redPath[i].siblings[j] <== redSiblings[i][j];
            redPath[i].directions[j] <== redDirections[i][j];
        }

        originalLeafHashes[i] + updateMask[i] * (placeholderHash - originalLeafHashes[i]) === redactedLeafHashes[i];

        selectorBounds[i] = LessThan(32);
        selectorBounds[i].in[0] <== policySelector[i];
        selectorBounds[i].in[1] <== NUM_POLICY_RULES;
        updateMask[i] * (1 - selectorBounds[i].out) === 0;
    }

    signal policyChain[NUM_POLICY_RULES + 1];
    policyChain[0] <== 0;
    component policyHasher[NUM_POLICY_RULES];
    for (var k = 0; k < NUM_POLICY_RULES; k++) {
        policyHasher[k] = Poseidon(2);
        policyHasher[k].inputs[0] <== policyChain[k];
        policyHasher[k].inputs[1] <== policyRules[k];
        policyChain[k + 1] <== policyHasher[k].out;
    }
    policyCommitment === policyChain[NUM_POLICY_RULES];

    signal bindingNonZero;
    bindingNonZero <== documentBindingCommitment * documentBindingCommitment;
}

component main {public [originalRoot, redactedRoot, policyCommitment, documentBindingCommitment]} = ZKPTRedactionSparse(4, 8, 8);
