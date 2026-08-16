"""
Minimal session bytecode VM for BINZ stream-cipher scheduling.

The unwrapped protection session is a small program that sets up
(seed, offset, length) segments and applies xorshift16 crypt over the
input buffer — enough for BINZ → r4Cz.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable

from .xorshift import apply_xorshift16

# F3 immediates: function-ref table indices used by the session program.
_FUN_TAB = (4, 5, 6, 7, 8, 9, 10, 11, 12)

# Host ops the session may call (by table index).
_HOST = {
    1: "crypt",
    4: "add",
    5: "sub",
    6: "min",
    8: "buflen",
    9: "xor",
    11: "or",
}

# Built-in dict keys seen across models (F4 big-endian u16 → table index).
_DEFAULT_DICT = {
    0x03C6: 1,  # crypt
    0x08AA: 2,  # lf (alloc) — stub
    0x13A2: 3,  # mf (inflate) — stub
}


@dataclass
class _Val:
    tag: int  # 2=i32, 3=u32, 5=funref, 4=buffer
    val: int


@dataclass
class SessionVM:
    code: bytes
    buf: bytearray
    dict_map: dict[int, int] = field(default_factory=lambda: dict(_DEFAULT_DICT))
    stack: list[_Val] = field(default_factory=list)
    fp: int = 0  # frame base index into stack
    call_stack: list[int] = field(default_factory=list)
    pc: int = 0
    crypt_log: list[tuple[int, int, int]] = field(default_factory=list)
    _buf_slot: int | None = None  # stack index holding the input buffer

    # --- stack helpers (mirror f_ue / f_pe / f_ye / f_we) ---

    def _slot_index(self, slot: int) -> int:
        if slot < 0:
            return len(self.stack) + slot
        # positive: relative to frame (fp_marker - 1 + slot)
        return self.fp + slot - 1

    def _get(self, slot: int) -> _Val:
        return self.stack[self._slot_index(slot)]

    def _set_local(self, slot: int) -> None:
        """TE: copy top into slot, pop."""
        top = self.stack[-1]
        idx = self._slot_index(slot)
        if idx != len(self.stack) - 1:
            self.stack[idx] = _Val(top.tag, top.val)
            if top.tag == 4:
                self._buf_slot = idx
        self.stack.pop()

    def _dup_local(self, slot: int) -> None:
        """SE: push a copy of slot."""
        v = self._get(slot)
        self.stack.append(_Val(v.tag, v.val))

    def _push_i32(self, v: int) -> None:
        self.stack.append(_Val(2, v & 0xFFFFFFFF))

    def _push_fun(self, idx: int) -> None:
        self.stack.append(_Val(5, idx & 0xFFFFFFFF))

    def _pop_n(self, n: int) -> None:
        if n:
            del self.stack[-n:]

    def _as_int(self, v: _Val) -> int:
        return v.val & 0xFFFFFFFF

    # --- host calls ---

    def _call_host(self, fun_idx: int, arity: int) -> None:
        # Function ref already popped by ``_call``.
        name = _HOST.get(fun_idx)

        if name == "crypt":
            # Args in frame slots: 2=seed, 3=offset, 4=length.
            length = self._as_int(self._get(4))
            offset = self._as_int(self._get(3))
            seed = self._as_int(self._get(2)) & 0xFFFF
            if offset + length > len(self.buf):
                length = max(0, len(self.buf) - offset)
            new_seed = apply_xorshift16(self.buf, offset, length, seed)
            self.crypt_log.append((offset, length, seed))
            self._pop_n(arity)
            self._push_i32(new_seed)
            return

        if name == "or":
            a = self._as_int(self._get(1))
            b = self._as_int(self._get(2))
            self._pop_n(arity)
            self._push_i32(a | b)
            return

        if name == "xor":
            a = self._as_int(self._get(1))
            b = self._as_int(self._get(2))
            self._pop_n(arity)
            self._push_i32(a ^ b)
            return

        if name == "add":
            a = self._as_int(self._get(1))
            b = self._as_int(self._get(2))
            self._pop_n(arity)
            self._push_i32((a + b) & 0xFFFFFFFF)
            return

        if name == "sub":
            a = self._as_int(self._get(1))
            b = self._as_int(self._get(2))
            self._pop_n(arity)
            self._push_i32((a - b) & 0xFFFFFFFF)
            return

        if name == "min":
            a = self._as_int(self._get(1))
            b = self._as_int(self._get(2))
            self._pop_n(arity)
            self._push_i32(a if a < b else b)
            return

        if name == "buflen":
            # f_hg: pop buffer-ish, push len(buf)
            self._pop_n(max(arity, 1))
            self._push_i32(len(self.buf))
            return

        if fun_idx == 2:  # lf — alloc output buffer; push buffer handle
            self._pop_n(arity)
            self.stack.append(_Val(4, 0))  # buffer tag
            self._buf_slot = len(self.stack) - 1
            return

        if fun_idx == 3:  # mf — inflate stub (not used on crypt path)
            self._pop_n(arity)
            self._push_i32(1)
            return

        raise RuntimeError(f"unimplemented host fun index {fun_idx} (arity={arity})")

    def _call(self, arity: int) -> None:
        top = self.stack[-1]
        if top.tag != 5:
            raise RuntimeError(f"CALL on non-fun tag={top.tag}")
        fun_idx = top.val
        self.stack.pop()
        # Args are the top ``arity`` values: slot 1 = deepest, slot arity = top.
        # _slot_index(k) = fp + k - 1, so fp = len(stack) - arity.
        saved_fp = self.fp
        self.fp = len(self.stack) - arity
        self._call_host(fun_idx, arity)
        self.fp = saved_fp

    # --- fetch helpers ---

    def _u8(self) -> int:
        b = self.code[self.pc]
        self.pc += 1
        return b

    def _u16(self) -> int:
        v = struct.unpack_from("<H", self.code, self.pc)[0]
        self.pc += 2
        return v

    def _i32(self) -> int:
        v = struct.unpack_from("<I", self.code, self.pc)[0]
        self.pc += 4
        return v

    def step(self) -> str | None:
        """
        Execute one opcode. Returns a status string on halt, else None.
        """
        if self.pc < 0 or self.pc >= len(self.code):
            return "pc_oob"
        op = self._u8()

        if op == 0x00:
            return None
        if op == 0x01:  # RET_BYTE
            _ = self._u8()
            return "ret_byte"
        if op == 0x02:  # POP n
            self._pop_n(self._u8())
            return None
        if op == 0x03:  # DUP_LOCAL
            self._dup_local(self._u8() - 128)
            return None
        if op == 0x04:  # SET_LOCAL
            self._set_local(self._u8() - 128)
            return None
        if op == 0x05:  # CALL
            self._call(self._u8())
            return None
        if op == 0x06:  # JUMP
            self.pc = self._u16()
            return None
        if op == 0x0A:  # JEQZ slot, tgt
            slot = self._u8() - 128
            tgt = self._u16()
            if self._as_int(self._get(slot)) == 0:
                self.pc = tgt
            return None
        if op == 0x0B:  # JNEZ
            slot = self._u8() - 128
            tgt = self._u16()
            if self._as_int(self._get(slot)) != 0:
                self.pc = tgt
            return None
        if op == 0x0C:  # GOSUB
            tgt = self._u16()
            self.call_stack.append(self.pc)
            self.pc = tgt
            return None
        if op == 0x0D:  # RETURN
            if not self.call_stack:
                return "return"
            self.pc = self.call_stack.pop()
            return None
        if 0x0E <= op <= 0x16:
            # B_h switch: slot, then (op-12) u16 targets
            slot = self._u8() - 128
            width = op - 12
            val = self._as_int(self._get(slot))
            table = [self._u16() for _ in range(width)]
            if val < width:
                self.pc = table[val]
            return None
        if op == 0xF0:
            self._push_i32(self._i32())
            return None
        if op == 0xF1:
            self.stack.append(_Val(3, self._i32()))
            return None
        if op == 0xF2:
            self.pc += 4  # skip float
            self.stack.append(_Val(1, 0))
            return None
        if op == 0xF3:
            idx = self._u8()
            self._push_fun(_FUN_TAB[idx])
            return None
        if op == 0xF4:
            key = (self._u8() << 8) | self._u8()
            fi = self.dict_map.get(key)
            if fi is None:
                raise RuntimeError(f"unknown F4 key {key:#06x}")
            self._push_fun(fi)
            return None
        if op == 0xFF:
            return "halt"

        raise RuntimeError(f"unimplemented opcode {op:#04x} at {self.pc-1:#x}")

    def run(self, max_steps: int | None = None) -> None:
        # Large model_file.binz streams need ~40–50 VM steps per KiB of
        # ciphertext (many short crypt segments). Default scales with buffer.
        if max_steps is None:
            max_steps = max(1_000_000, (len(self.buf) // 1024) * 64 + 100_000)
        for _ in range(max_steps):
            st = self.step()
            if st is not None:
                return
        raise RuntimeError(
            f"session VM: step limit exceeded ({max_steps}; "
            f"crypt_segments={len(self.crypt_log)})"
        )


def decrypt_binz_with_session(encrypted: bytes, session: bytes) -> bytes:
    """
    Apply the session-driven xorshift16 stream cipher; return r4Cz bytes.

    Init ends at ``RET_BYTE`` (PC left on the next opcode, usually a
    ``GOSUB`` into the crypt loop). A second ``run()`` resumes there.
    """
    buf = bytearray(encrypted)
    vm = SessionVM(code=session, buf=buf)
    vm.run()  # init → RET_BYTE (PC left on the resume opcode)
    vm.run()  # crypt / dispatch → RETURN
    if buf[:4] != b"r4Cz":
        raise RuntimeError(
            f"session VM decrypt did not yield r4Cz (got {bytes(buf[:4])!r}); "
            f"crypt_log={vm.crypt_log}"
        )
    return bytes(buf)
