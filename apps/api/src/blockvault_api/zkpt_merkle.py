from __future__ import annotations

import math
from dataclasses import dataclass

from .zkpt_poseidon import bytes_to_field_elements, poseidon_hash, poseidon_hash_chain


@dataclass(frozen=True)
class AuthenticationPath:
    leaf_index: int
    leaf_hash: int
    siblings: list[tuple[int, int]]
    root: int


class PoseidonMerkleTree:
    ZERO_HASH = 0

    def __init__(self, leaves: list[int]):
        if not leaves:
            leaves = [self.ZERO_HASH]

        original_count = len(leaves)
        depth = max(1, math.ceil(math.log2(original_count))) if original_count > 1 else 1
        leaf_count = 2 ** depth

        self.depth = depth
        self.original_leaf_count = original_count
        self.leaf_count = leaf_count
        self.nodes = [0] * (2 * leaf_count)

        for index, leaf in enumerate(leaves):
            self.nodes[leaf_count + index] = leaf
        for index in range(original_count, leaf_count):
            self.nodes[leaf_count + index] = self.ZERO_HASH

        for index in range(leaf_count - 1, 0, -1):
            self.nodes[index] = poseidon_hash(self.nodes[index * 2], self.nodes[index * 2 + 1])

        self.root = self.nodes[1]

    def get_leaf(self, index: int) -> int:
        return self.nodes[self.leaf_count + index]

    def get_authentication_path(self, leaf_index: int) -> AuthenticationPath:
        siblings: list[tuple[int, int]] = []
        node_index = self.leaf_count + leaf_index
        for _ in range(self.depth):
            if node_index % 2 == 0:
                sibling_index = node_index + 1
                direction = 0
            else:
                sibling_index = node_index - 1
                direction = 1
            siblings.append((self.nodes[sibling_index], direction))
            node_index //= 2
        return AuthenticationPath(
            leaf_index=leaf_index,
            leaf_hash=self.get_leaf(leaf_index),
            siblings=siblings,
            root=self.root,
        )


def hash_segment(segment: bytes) -> int:
    return poseidon_hash_chain(bytes_to_field_elements(segment))
