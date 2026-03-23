from __future__ import annotations

import hashlib

BN254_PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
POSEIDON_T = 3
POSEIDON_RF = 8
POSEIDON_RP = 57
POSEIDON_ALPHA = 5
POSEIDON_ROUNDS = POSEIDON_RF + POSEIDON_RP


def _generate_round_constants(t: int, num_rounds: int, seed: str = "poseidon") -> list[int]:
    constants: list[int] = []
    shake = hashlib.shake_256(seed.encode("utf-8"))
    raw = shake.digest(t * num_rounds * 32)
    for index in range(t * num_rounds):
        chunk = raw[index * 32:(index + 1) * 32]
        constants.append(int.from_bytes(chunk, "big") % BN254_PRIME)
    return constants


def _generate_mds_matrix(t: int) -> list[list[int]]:
    x_values = list(range(t))
    y_values = list(range(t, 2 * t))
    matrix: list[list[int]] = []
    for row_index in range(t):
        row: list[int] = []
        for column_index in range(t):
            value = (x_values[row_index] + y_values[column_index]) % BN254_PRIME
            row.append(pow(value, BN254_PRIME - 2, BN254_PRIME))
        matrix.append(row)
    return matrix


_ROUND_CONSTANTS = _generate_round_constants(POSEIDON_T, POSEIDON_ROUNDS)
_MDS_MATRIX = _generate_mds_matrix(POSEIDON_T)


def _sbox(value: int) -> int:
    return pow(value, POSEIDON_ALPHA, BN254_PRIME)


def _add_round_constants(state: list[int], round_index: int) -> list[int]:
    offset = round_index * len(state)
    return [(state[index] + _ROUND_CONSTANTS[offset + index]) % BN254_PRIME for index in range(len(state))]


def _mds_multiply(state: list[int]) -> list[int]:
    result = [0] * len(state)
    for row_index in range(len(state)):
        accumulator = 0
        for column_index in range(len(state)):
            accumulator = (accumulator + _MDS_MATRIX[row_index][column_index] * state[column_index]) % BN254_PRIME
        result[row_index] = accumulator
    return result


def poseidon_permutation(state: list[int]) -> list[int]:
    if len(state) != POSEIDON_T:
        raise ValueError(f"Poseidon state width must be {POSEIDON_T}")

    round_index = 0
    full_rounds_each_side = POSEIDON_RF // 2

    for _ in range(full_rounds_each_side):
        state = _add_round_constants(state, round_index)
        state = [_sbox(value) for value in state]
        state = _mds_multiply(state)
        round_index += 1

    for _ in range(POSEIDON_RP):
        state = _add_round_constants(state, round_index)
        state[0] = _sbox(state[0])
        state = _mds_multiply(state)
        round_index += 1

    for _ in range(full_rounds_each_side):
        state = _add_round_constants(state, round_index)
        state = [_sbox(value) for value in state]
        state = _mds_multiply(state)
        round_index += 1

    return state


def poseidon_hash(left: int, right: int) -> int:
    if not 0 <= left < BN254_PRIME or not 0 <= right < BN254_PRIME:
        raise ValueError("Poseidon inputs must be inside the BN254 scalar field")
    return poseidon_permutation([left, right, 0])[0]


def poseidon_hash_chain(elements: list[int]) -> int:
    if not elements:
        return poseidon_hash(0, 0)
    if len(elements) == 1:
        return poseidon_hash(elements[0], 0)

    state = [0] * POSEIDON_T
    padded = list(elements)
    if len(padded) % 2:
        padded.append(0)

    for index in range(0, len(padded), 2):
        state[0] = (state[0] + padded[index]) % BN254_PRIME
        state[1] = (state[1] + padded[index + 1]) % BN254_PRIME
        state = poseidon_permutation(state)
    return state[0]


def bytes_to_field_elements(data: bytes, chunk_size: int = 31) -> list[int]:
    elements: list[int] = []
    for offset in range(0, len(data), chunk_size):
        chunk = data[offset:offset + chunk_size]
        if len(chunk) < chunk_size:
            chunk = chunk + b"\x00" * (chunk_size - len(chunk))
        elements.append(int.from_bytes(chunk, "big"))
    elements.append(len(data) % BN254_PRIME)
    return elements

