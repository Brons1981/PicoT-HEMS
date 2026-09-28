"""Lossless wire references for repeated diagnostic evidence sequences."""

from __future__ import annotations


class EvidenceSequenceEncoder:
    """Reference raw bases only: prefix + middle + suffix, without recursion."""

    def __init__(self) -> None:
        self.dictionary: dict[str, dict[str, object]] = {}
        self._references: dict[tuple[str, ...], str] = {}
        self._bases: dict[int, tuple[str, ...]] = {}

    def reference(self, sequence: tuple[str, ...]) -> str:
        if sequence in self._references:
            return self._references[sequence]
        reference = f"e{len(self._references)}"
        base = self._bases.get(len(sequence))
        prefix = suffix = 0
        if base is not None:
            while prefix < len(sequence) and sequence[prefix] == base[prefix]:
                prefix += 1
            while (suffix < len(sequence) - prefix
                   and sequence[-suffix - 1] == base[-suffix - 1]):
                suffix += 1
        if base is not None and prefix + suffix > 8:
            self.dictionary[reference] = {
                "base": self._references[base], "prefix_count": prefix,
                "middle": list(sequence[prefix:len(sequence) - suffix]),
                "suffix_start": len(base) - suffix,
            }
        else:
            self.dictionary[reference] = {"ids": list(sequence)}
            self._bases.setdefault(len(sequence), sequence)
        self._references[sequence] = reference
        return reference
