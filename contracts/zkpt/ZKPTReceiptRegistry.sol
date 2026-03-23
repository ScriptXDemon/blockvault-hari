// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IPlonkVerifier {
    function verifyProof(uint256[24] calldata proof, uint256[4] calldata pubSignals) external view returns (bool);
}

contract ZKPTReceiptRegistry {
    struct BundleMetadata {
        bytes32 manifestHash;
        bytes32 originalSha256;
        bytes32 redactedSha256;
        bytes32 canonicalOriginalSha256;
        bytes32 canonicalRedactedSha256;
        uint256 documentBindingCommitment;
        string bundleId;
        string artifactVersion;
        string profileId;
        uint8 sourceTextMode;
    }

    struct ReceiptRecord {
        bytes32 manifestHash;
        bytes32 originalSha256;
        bytes32 redactedSha256;
        bytes32 canonicalOriginalSha256;
        bytes32 canonicalRedactedSha256;
        uint256 documentBindingCommitment;
        bytes32 bundleIdHash;
        bytes32 artifactVersionHash;
        bytes32 profileIdHash;
        uint8 sourceTextMode;
        address submitter;
        uint64 submittedAt;
    }

    IPlonkVerifier public immutable verifier;
    mapping(bytes32 => ReceiptRecord) public receipts;

    event ReceiptVerified(
        bytes32 indexed receiptId,
        bytes32 indexed bundleIdHash,
        bytes32 manifestHash,
        uint256 documentBindingCommitment,
        string bundleId,
        string artifactVersion,
        string profileId,
        uint8 sourceTextMode,
        address submitter
    );

    constructor(address verifierAddress) {
        require(verifierAddress != address(0), "verifier required");
        verifier = IPlonkVerifier(verifierAddress);
    }

    function submitVerifiedBundle(
        uint256[24] calldata proof,
        uint256[4] calldata publicSignals,
        BundleMetadata calldata metadata
    ) external returns (bytes32 receiptId) {
        require(verifier.verifyProof(proof, publicSignals), "invalid proof");

        bytes32 bundleIdHash = keccak256(bytes(metadata.bundleId));
        receiptId = keccak256(abi.encodePacked(bundleIdHash, metadata.manifestHash, metadata.documentBindingCommitment));
        require(receipts[receiptId].submittedAt == 0, "receipt exists");

        receipts[receiptId] = ReceiptRecord({
            manifestHash: metadata.manifestHash,
            originalSha256: metadata.originalSha256,
            redactedSha256: metadata.redactedSha256,
            canonicalOriginalSha256: metadata.canonicalOriginalSha256,
            canonicalRedactedSha256: metadata.canonicalRedactedSha256,
            documentBindingCommitment: metadata.documentBindingCommitment,
            bundleIdHash: bundleIdHash,
            artifactVersionHash: keccak256(bytes(metadata.artifactVersion)),
            profileIdHash: keccak256(bytes(metadata.profileId)),
            sourceTextMode: metadata.sourceTextMode,
            submitter: msg.sender,
            submittedAt: uint64(block.timestamp)
        });

        emit ReceiptVerified(
            receiptId,
            bundleIdHash,
            metadata.manifestHash,
            metadata.documentBindingCommitment,
            metadata.bundleId,
            metadata.artifactVersion,
            metadata.profileId,
            metadata.sourceTextMode,
            msg.sender
        );
    }
}
